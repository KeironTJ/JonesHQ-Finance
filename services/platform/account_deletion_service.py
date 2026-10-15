from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import (
    Account, Balance, CreditCard, CreditCardPromotion, CreditCardTransaction,
    Expense, Family, FamilyInvite, FuelRecord, HouseholdInvite, Income, Loan,
    LoanPayment, LoanTermChange, MonthlyAccountBalance, Pension, PensionSnapshot,
    Plan, PlanItem, RecurringIncome, Subscription, Transaction, Trip, User,
    UserRecoveryCode, UserSession, Vehicle,
)
from models.expense_calendar import ExpenseCalendarEntry
from utils.db_helpers import get_current_user_id


OWNED_MODELS = (Account, CreditCard, Expense, Income, RecurringIncome, Loan, Pension, Plan, Vehicle)
DOMAIN_CHILDREN = (
    (Balance, Account, 'account_id'),
    (MonthlyAccountBalance, Account, 'account_id'),
    (Transaction, Account, 'account_id'),
    (CreditCardPromotion, CreditCard, 'credit_card_id'),
    (CreditCardTransaction, CreditCard, 'credit_card_id'),
    (Subscription, Account, 'account_id'),
    (Subscription, CreditCard, 'credit_card_id'),
    (LoanPayment, Loan, 'loan_id'),
    (LoanTermChange, Loan, 'loan_id'),
    (PensionSnapshot, Pension, 'pension_id'),
    (PlanItem, Plan, 'plan_id'),
    (FuelRecord, Vehicle, 'vehicle_id'),
    (Trip, Vehicle, 'vehicle_id'),
    (ExpenseCalendarEntry, Expense, 'expense_id'),
)
DELETE_ORDER = (
    ExpenseCalendarEntry, PlanItem, Trip, FuelRecord, LoanTermChange, LoanPayment,
    PensionSnapshot, CreditCardPromotion, Expense, Income, CreditCardTransaction, Balance,
    MonthlyAccountBalance, Transaction, Subscription,
    RecurringIncome, Plan, Vehicle, Pension, Loan, CreditCard, Account,
    FamilyInvite, UserSession, UserRecoveryCode, User,
)


class AccountDeletionService:
    """Delete only the current user's account and owned domains, in one transaction."""

    @staticmethod
    def _check_user(user):
        if not user.is_authenticated or not user.is_active or user.id != get_current_user_id():
            raise ValueError('Sign in to delete your own account.')
        if user.is_site_admin:
            raise ValueError('Revoke your site-admin role using the server command before deleting your account.')
        if user.family_id is not None and user.role == 'admin':
            replacement = db.session.execute(select(User.id).where(
                User.family_id == user.family_id, User.id != user.id,
                User.role == 'admin', User.is_active.is_(True),
            )).first()
            if replacement is None:
                raise ValueError('Appoint another active household administrator before deleting your account.')

    @staticmethod
    def _plan(user):
        AccountDeletionService._check_user(user)
        plan = {}
        # Exact ownership is deliberate: removed members can still own records in a former household.
        for model in OWNED_MODELS:
            rows = db.session.execute(select(model.id, model.family_id).where(model.owner_id == user.id))
            plan[model.__table__] = dict(rows.all())
        for child, parent, foreign_key in DOMAIN_CHILDREN:
            parents = plan[parent.__table__]
            if not parents:
                continue
            rows = db.session.execute(select(
                child.id, child.family_id, getattr(child, foreign_key),
            ).where(getattr(child, foreign_key).in_(parents)))
            for row_id, family_id, parent_id in rows:
                if family_id != parents[parent_id]:
                    raise ValueError('Linked household data is inconsistent. Contact the site administrator before deletion.')
                plan.setdefault(child.__table__, {})[row_id] = family_id
        for model, foreign_key in (
            (FamilyInvite, 'created_by_id'), (UserSession, 'user_id'), (UserRecoveryCode, 'user_id'),
        ):
            rows = db.session.execute(select(model.id).where(getattr(model, foreign_key) == user.id))
            plan[model.__table__] = {row_id: None for row_id in rows.scalars()}
        plan[User.__table__] = {user.id: user.family_id}
        return plan

    @staticmethod
    def _references(plan):
        """Validate incoming foreign keys before detaching any nullable references."""
        references = []
        delete_order = {model.__table__: index for index, model in enumerate(DELETE_ORDER)}
        for table in db.metadata.tables.values():
            for column in table.columns:
                for foreign_key in column.foreign_keys:
                    targets = plan.get(foreign_key.column.table, {})
                    if not targets:
                        continue
                    condition = column.in_(targets)
                    deleting = plan.get(table, {})
                    rows = db.session.execute(select(table).where(condition)).mappings().all()
                    if not rows:
                        continue
                    surviving = [row for row in rows if row['id'] not in deleting]
                    if not column.nullable:
                        if surviving:
                            raise ValueError('Linked records prevent safe account deletion. Contact the site administrator.')
                        continue
                    if surviving and column.name == 'owner_id' and foreign_key.column.table == User.__table__:
                        raise ValueError('Private records require a reviewed deletion rule. Contact the site administrator.')
                    if foreign_key.column.table != User.__table__:
                        for row in surviving:
                            if 'family_id' in row and row['family_id'] != targets[row[column.name]]:
                                raise ValueError('Linked household data is inconsistent. Contact the site administrator before deletion.')
                    if table in delete_order and delete_order[table] < delete_order[foreign_key.column.table]:
                        # Rows deleted first need no detachment (subscriptions require a funding target).
                        condition &= table.c.id.not_in(deleting)
                    references.append((table, column, condition))
        return references

    @staticmethod
    def preview(user):
        plan = AccountDeletionService._plan(user)
        AccountDeletionService._references(plan)
        return {table.name: len(ids) for table, ids in plan.items() if ids}

    @staticmethod
    def delete_account(user, data):
        AccountDeletionService._check_user(user)
        if (data.get('confirmation') or '') != 'DELETE MY ACCOUNT':
            raise ValueError('Type DELETE MY ACCOUNT exactly to confirm.')
        try:
            # Serialize household self-deletions before checking the last-admin rule (also on SQLite).
            if user.family_id is not None:
                db.session.execute(update(Family).where(Family.id == user.family_id).values(id=Family.id))
            db.session.refresh(user)
            plan = AccountDeletionService._plan(user)
            if not user.check_password(data.get('password') or ''):
                raise ValueError('Your current password was not correct.')
            references = AccountDeletionService._references(plan)
            counts = {table.name: len(ids) for table, ids in plan.items() if ids}
            # Deletion bypasses domain delete helpers: those can erase linked shared ledger entries.
            db.session.execute(update(HouseholdInvite).where(
                HouseholdInvite.created_by_id == user.id, HouseholdInvite.used_at.is_(None),
                HouseholdInvite.revoked_at.is_(None),
            ).values(revoked_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            for table, column, condition in references:
                db.session.execute(update(table).where(condition).values({column.name: None}))
            for model in DELETE_ORDER:
                ids = plan.get(model.__table__, {})
                if ids:
                    db.session.execute(delete(model.__table__).where(model.id.in_(ids)))
            db.session.commit()
        except (SQLAlchemyError, ValueError):
            db.session.rollback()
            raise
        current_app.logger.info('ACCOUNT_DELETION_COMPLETED')
        return counts
