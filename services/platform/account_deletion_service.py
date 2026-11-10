from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import (
    Account, Balance, CreditCard, CreditCardPromotion, CreditCardTransaction,
    Expense, Family, FamilyInvite, FuelRecord, HouseholdInvite, Income, IncomeChange, Loan,
    LoanPayment, LoanTermChange, MonthlyAccountBalance, Pension, PensionSnapshot,
    Plan, PlanItem, RecurringIncome, Subscription, Transaction, Trip, TripSchedule, TripTemplate,
    User, UserRecoveryCode, UserSession, Vehicle,
)
from models.family import HouseholdMembership
from models.calendar_event import CalendarEvent
from models.activities import ActivityAttendee
from models.household_tasks import HouseholdTask, TaskList
from models.rewards import RewardGoal, RewardJob, RewardPointEntry, RewardRequest
from models.expense_calendar import ExpenseCalendarEntry
from models.passkeys import PasskeyChallenge, UserPasskey
from models.settings import Settings
from services.platform.deletion_helpers import deletion_references
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
    (IncomeChange, RecurringIncome, 'recurring_income_id'),
    (PensionSnapshot, Pension, 'pension_id'),
    (PlanItem, Plan, 'plan_id'),
    (FuelRecord, Vehicle, 'vehicle_id'),
    (Trip, Vehicle, 'vehicle_id'),
    (TripSchedule, Vehicle, 'vehicle_id'),
    (TripTemplate, Vehicle, 'vehicle_id'),
    (ExpenseCalendarEntry, Expense, 'expense_id'),
)
DELETE_ORDER = (
    RewardPointEntry, RewardRequest, RewardGoal, RewardJob,
    HouseholdTask, TaskList,
    ActivityAttendee,
    CalendarEvent,
    ExpenseCalendarEntry, PlanItem, Trip, TripSchedule, TripTemplate, FuelRecord, LoanTermChange, LoanPayment,
    PensionSnapshot, CreditCardPromotion, Expense, Income, IncomeChange, CreditCardTransaction, Balance,
    MonthlyAccountBalance, Transaction, Subscription,
    RecurringIncome, Plan, Vehicle, Pension, Loan, CreditCard, Account,
    FamilyInvite, UserSession, UserRecoveryCode, PasskeyChallenge, UserPasskey,
    HouseholdMembership, User,
)


class AccountDeletionService:
    """Delete only the current user's account and owned domains, in one transaction."""

    @staticmethod
    def _check_user(user):
        if not user.is_authenticated or not user.is_active or user.id != get_current_user_id():
            raise ValueError('Sign in to delete your own account.')
        if user.is_managed_child:
            raise ValueError('Your guardian manages your account status.')
        if User.query.filter_by(guardian_id=user.id, account_type='child').first() is not None:
            raise ValueError('Transfer guardianship or release managed child accounts before deleting your account.')
        if user.is_site_admin:
            raise ValueError('Revoke your site-admin role using the server command before deleting your account.')
        owner_memberships = HouseholdMembership.query.filter_by(
            user_id=user.id, role='admin',
        ).all()
        for membership in owner_memberships:
            replacement = db.session.execute(
                select(HouseholdMembership.id)
                .join(User, User.id == HouseholdMembership.user_id)
                .where(
                    HouseholdMembership.family_id == membership.family_id,
                    HouseholdMembership.user_id != user.id,
                    HouseholdMembership.role == 'admin',
                    User.is_active.is_(True),
                )
            ).first()
            if replacement is None:
                raise ValueError('Appoint another active household owner before deleting your account.')

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
                    raise ValueError('Linked household data is inconsistent. Contact the service operator before deletion.')
                plan.setdefault(child.__table__, {})[row_id] = family_id
        memberships = db.session.execute(select(HouseholdMembership.id, HouseholdMembership.family_id).where(
            HouseholdMembership.user_id == user.id,
        ))
        plan[HouseholdMembership.__table__] = dict(memberships.all())
        plan[TaskList.__table__] = dict(db.session.execute(select(
            TaskList.id, TaskList.family_id,
        ).where(
            TaskList.creator_membership_id.in_(plan[HouseholdMembership.__table__]),
            TaskList.visibility == 'personal',
        )).all())
        task_rows = db.session.execute(select(
            HouseholdTask.id, HouseholdTask.family_id, HouseholdTask.list_id,
        ).where(HouseholdTask.list_id.in_(plan[TaskList.__table__]))).all()
        plan[HouseholdTask.__table__] = {}
        for task_id, family_id, list_id in task_rows:
            if family_id != plan[TaskList.__table__][list_id]:
                raise ValueError('Linked household data is inconsistent. Contact the service operator before deletion.')
            plan[HouseholdTask.__table__][task_id] = family_id
        plan[ActivityAttendee.__table__] = dict(db.session.execute(select(
            ActivityAttendee.id, ActivityAttendee.family_id,
        ).where(
            ActivityAttendee.membership_id.in_(plan[HouseholdMembership.__table__]),
        )).all())
        plan[CalendarEvent.__table__] = dict(db.session.execute(select(
            CalendarEvent.id, CalendarEvent.family_id,
        ).where(
            CalendarEvent.creator_membership_id.in_(plan[HouseholdMembership.__table__]),
            CalendarEvent.visibility == 'private',
        )).all())
        for model, foreign_key in (
            (FamilyInvite, 'created_by_id'), (UserSession, 'user_id'), (UserRecoveryCode, 'user_id'),
            (PasskeyChallenge, 'user_id'), (UserPasskey, 'user_id'),
        ):
            rows = db.session.execute(select(model.id).where(getattr(model, foreign_key) == user.id))
            plan[model.__table__] = {row_id: None for row_id in rows.scalars()}
        plan[User.__table__] = {user.id: user.family_id}
        return plan

    @staticmethod
    def _references(plan):
        return deletion_references(plan, [model.__table__ for model in DELETE_ORDER])

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
            family_ids = db.session.execute(select(HouseholdMembership.family_id).where(
                HouseholdMembership.user_id == user.id,
            )).scalars().all()
            if family_ids:
                db.session.execute(update(Family).where(
                    Family.id.in_(family_ids),
                ).values(id=Family.id))
            db.session.refresh(user)
            plan = AccountDeletionService._plan(user)
            if not user.check_password(data.get('password') or ''):
                raise ValueError('Your current password was not correct.')
            references = AccountDeletionService._references(plan)
            for membership_id, family_id in plan[HouseholdMembership.__table__].items():
                db.session.execute(update(RewardJob).where(
                    RewardJob.family_id == family_id, RewardJob.membership_id == membership_id,
                    RewardJob.state.in_(('open', 'submitted')),
                ).values(state='closed', review_note='The member left the household.'))
                pending = db.session.execute(select(RewardRequest).where(
                    RewardRequest.family_id == family_id, RewardRequest.membership_id == membership_id,
                    RewardRequest.state == 'pending',
                )).scalars().all()
                for reward_request in pending:
                    reward_request.state = 'declined'
                    reward_request.review_note = 'The member left the household.'
                    reward_request.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    db.session.add(RewardPointEntry(
                        family_id=family_id, membership_id=None, request_id=reward_request.id,
                        kind='returned', points=reward_request.points_cost,
                        description=reward_request.title, created_at=reward_request.reviewed_at,
                    ))
            for task_id, family_id in plan[HouseholdTask.__table__].items():
                db.session.execute(update(RewardJob).where(
                    RewardJob.family_id == family_id, RewardJob.task_id == task_id,
                    RewardJob.state.in_(('open', 'submitted')),
                ).values(state='closed', review_note='The task was removed.'))
            db.session.flush()
            from services.household.calendar_service import CalendarService
            CalendarService.remove_membership_grants(plan[HouseholdMembership.__table__])
            counts = {table.name: len(ids) for table, ids in plan.items() if ids}
            # Deletion bypasses domain delete helpers: those can erase linked shared ledger entries.
            db.session.execute(update(HouseholdInvite).where(
                HouseholdInvite.created_by_id == user.id, HouseholdInvite.used_at.is_(None),
                HouseholdInvite.revoked_at.is_(None),
            ).values(revoked_at=datetime.now(timezone.utc).replace(tzinfo=None)))
            for table, column, condition in references:
                db.session.execute(update(table).where(condition).values({column.name: None}))
            db.session.execute(delete(Settings).where(Settings.key.in_(
                (f'retirement.member.{user.id}.date_of_birth', f'retirement.member.{user.id}.retirement_age'))))
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
