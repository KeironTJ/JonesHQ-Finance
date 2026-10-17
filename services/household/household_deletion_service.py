from datetime import datetime, timezone

from flask import current_app
from sqlalchemy import delete, insert, select, update
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models import Family, SecurityEvent, User, UserSession
from services.platform.deletion_helpers import deletion_references
from utils.db_helpers import get_current_user_id


# Reviewed child-first order; new household tables must be explicitly included.
HOUSEHOLD_TABLES = (
    'expense_calendar_entries', 'plan_items', 'trips', 'fuel_records',
    'loan_term_changes', 'loan_payments', 'pension_snapshots',
    'credit_card_promotions', 'expenses', 'income', 'credit_card_transactions',
    'balances', 'monthly_account_balances', 'daily_childcare_activities',
    'monthly_childcare_summaries', 'child_activity_types', 'children',
    'mortgage_snapshots', 'mortgage_products', 'mortgage_payments',
    'property_valuation_snapshots', 'transactions', 'subscriptions',
    'expense_reimbursement_groups', 'recurring_income', 'planned_transactions',
    'budgets', 'plans', 'vehicles', 'pensions', 'loans', 'credit_cards',
    'accounts', 'vendors', 'vendor_types', 'categories', 'mortgages',
    'properties', 'childcare_records', 'net_worth', 'settings', 'tax_settings',
    'family_assignment_labels', 'family_invites',
)


class HouseholdDeletionService:
    @staticmethod
    def _check_user(user):
        if (
            not user.is_authenticated or not user.is_active
            or user.id != get_current_user_id() or not user.is_household_owner
            or user.family_id is None
        ):
            raise ValueError('Only an active household owner can delete their own household.')

    @staticmethod
    def _plan(user):
        HouseholdDeletionService._check_user(user)
        family_id = user.family_id
        tables = [db.metadata.tables[name] for name in HOUSEHOLD_TABLES]
        reviewed = set(tables) | {User.__table__, SecurityEvent.__table__}
        for table in db.metadata.tables.values():
            if 'family_id' in table.c and table not in reviewed:
                raise ValueError('Household data requires a reviewed deletion rule. Contact the service operator.')
        # Exact household scope deliberately includes every member's private records.
        plan = {
            table: dict(db.session.execute(
                select(table.c.id, table.c.family_id).where(table.c.family_id == family_id)
            ).all())
            for table in tables
        }
        plan[Family.__table__] = {family_id: family_id}
        order = tables + [Family.__table__]
        references = deletion_references(
            plan, order, allowed_family_detach=(User.__table__, SecurityEvent.__table__))
        return plan, references

    @staticmethod
    def preview(user):
        plan, _ = HouseholdDeletionService._plan(user)
        return {
            'counts': {table.name: len(ids) for table, ids in plan.items() if ids},
            'members': db.session.execute(select(User.name, User.email, User.is_active).where(
                User.family_id == user.family_id).order_by(User.id)).mappings().all(),
        }

    @staticmethod
    def delete_household(user, data):
        HouseholdDeletionService._check_user(user)
        if (data.get('confirmation') or '') != 'DELETE THIS HOUSEHOLD':
            raise ValueError('Type DELETE THIS HOUSEHOLD exactly to confirm.')
        family_id = user.family_id
        if str(data.get('family_id') or '') != str(family_id):
            raise ValueError('Your household membership changed. Review deletion again.')
        try:
            db.session.execute(update(Family).where(Family.id == family_id).values(id=Family.id))
            db.session.refresh(user)
            HouseholdDeletionService._check_user(user)
            if user.family_id != family_id:
                raise ValueError('Your household membership changed. Review deletion again.')
            if not user.check_password(data.get('password') or ''):
                raise ValueError('Your current password was not correct.')
            plan, references = HouseholdDeletionService._plan(user)
            member_ids = list(db.session.execute(select(User.id).where(
                User.family_id == family_id)).scalars())
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            db.session.execute(update(UserSession).where(
                UserSession.user_id.in_(member_ids), UserSession.revoked_at.is_(None),
            ).values(revoked_at=now))
            # Core insert bypasses request family stamping for retained audit events.
            db.session.execute(insert(SecurityEvent.__table__), [
                dict(user_id=member_id, family_id=None, event_type='household_deleted', created_at=now)
                for member_id in member_ids
            ])
            for table, column, condition in references:
                db.session.execute(update(table).where(condition).values({column.name: None}))
            db.session.execute(update(User).where(User.id.in_(member_ids)).values(
                family_id=None, role='member', allowed_sections=None, member_name=None,
                default_account_id=None, onboarding_version=0,
            ))
            # Core deletes avoid ORM cascades and domain helpers that commit separately.
            for table, ids in plan.items():
                if ids:
                    db.session.execute(delete(table).where(table.c.id.in_(ids)))
            db.session.commit()
        except (SQLAlchemyError, ValueError):
            db.session.rollback()
            raise
        db.session.expire_all()
        current_app.logger.info('HOUSEHOLD_DELETION_COMPLETED')
