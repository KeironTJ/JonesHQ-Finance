"""
Expense Reimbursement Group Service
====================================
CRUD for ExpenseReimbursementGroup plus the lazy "every family always has a
default group" guarantee that the rest of the expense/income sync code relies on.
"""
from extensions import db
from models.expense_reimbursement_group import ExpenseReimbursementGroup
from models.recurring_income import RecurringIncome
from utils import db_helpers
from utils.db_helpers import family_query, family_get_or_404


class ExpenseReimbursementGroupService:

    @staticmethod
    def get_default_group():
        """Return the current family's default group, creating it if missing."""
        group = family_query(ExpenseReimbursementGroup).filter_by(is_default=True).first()
        if group:
            return group
        group = ExpenseReimbursementGroup(
            family_id=db_helpers.get_family_id(),
            name='Default',
            mode='separate',
            is_default=True,
        )
        db.session.add(group)
        db.session.commit()
        return group

    @staticmethod
    def list_groups():
        return family_query(ExpenseReimbursementGroup).order_by(
            ExpenseReimbursementGroup.is_default.desc(), ExpenseReimbursementGroup.name
        ).all()

    @staticmethod
    def get_folded_group_for_recurring_income(recurring_income_id):
        """Return the (single, by convention) folded group tied to this job, if any."""
        if not recurring_income_id:
            return None
        return family_query(ExpenseReimbursementGroup).filter_by(
            recurring_income_id=recurring_income_id, mode='folded'
        ).first()

    @staticmethod
    def set_folding_for_recurring_income(recurring_income_id, enabled):
        """
        Simple on/off toggle used from the recurring-income form: creates (or
        re-enables) a single folded group for this job when enabled, or reverts it
        to 'separate' mode when disabled. Avoids the user ever having to visit the
        Reimbursement Groups page just to set up the common one-job case.
        """
        existing = ExpenseReimbursementGroupService.get_folded_group_for_recurring_income(recurring_income_id)
        if enabled:
            if existing:
                return existing
            recurring = family_query(RecurringIncome).filter_by(id=recurring_income_id).first()
            name = f'{recurring.person} payslip' if recurring else 'Payslip'
            group = ExpenseReimbursementGroup(
                family_id=db_helpers.get_family_id(),
                name=name,
                mode='folded',
                recurring_income_id=recurring_income_id,
            )
            db.session.add(group)
            db.session.commit()
            return group
        else:
            if existing:
                existing.mode = 'separate'
                existing.recurring_income_id = None
                db.session.commit()
            return None

    @staticmethod
    def create_group(data):
        mode = data.get('mode') or 'separate'
        recurring_income_id = int(data['recurring_income_id']) if data.get('recurring_income_id') else None
        if mode == 'folded' and not recurring_income_id:
            raise ValueError('Select which income/job this group folds reimbursements into.')
        if recurring_income_id and not family_query(RecurringIncome).filter_by(id=recurring_income_id).first():
            raise ValueError('Invalid income/job selected.')
        group = ExpenseReimbursementGroup(
            family_id=db_helpers.get_family_id(),
            name=(data.get('name') or '').strip() or 'Untitled group',
            mode=mode,
            recurring_income_id=recurring_income_id if mode == 'folded' else None,
        )
        db.session.add(group)
        db.session.commit()
        return group

    @staticmethod
    def update_group(group_id, data):
        group = family_get_or_404(ExpenseReimbursementGroup, group_id)
        mode = data.get('mode') or group.mode
        recurring_income_id = int(data['recurring_income_id']) if data.get('recurring_income_id') else None
        if mode == 'folded' and not recurring_income_id:
            raise ValueError('Select which income/job this group folds reimbursements into.')
        if recurring_income_id and not family_query(RecurringIncome).filter_by(id=recurring_income_id).first():
            raise ValueError('Invalid income/job selected.')
        if data.get('name'):
            group.name = data['name'].strip()
        group.mode = mode
        group.recurring_income_id = recurring_income_id if mode == 'folded' else None
        db.session.commit()
        return group

    @staticmethod
    def delete_group(group_id):
        group = family_get_or_404(ExpenseReimbursementGroup, group_id)
        if group.is_default:
            raise ValueError('The default group cannot be deleted.')
        from models.expenses import Expense
        in_use = family_query(Expense).filter_by(reimbursement_group_id=group.id).count()
        if in_use:
            raise ValueError(f'{in_use} expense(s) still use this group — reassign them first.')
        db.session.delete(group)
        db.session.commit()
