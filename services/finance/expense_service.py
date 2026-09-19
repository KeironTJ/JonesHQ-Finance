import re
from datetime import datetime
from decimal import Decimal

from extensions import db
from models.expenses import Expense
from utils import db_helpers
from utils.db_helpers import family_get_or_404, family_query


class ExpenseService:
    @staticmethod
    def _date_fields(expense_date):
        if not expense_date:
            return {
                'month': None,
                'week': None,
                'day_name': None,
                'finance_year': None,
            }
        return {
            'month': expense_date.strftime('%Y-%m'),
            'week': f'{expense_date.isocalendar()[1]:02d}-{expense_date.year}',
            'day_name': expense_date.strftime('%A'),
            'finance_year': (
                f'{expense_date.year}-{expense_date.year + 1}'
                if expense_date.month >= 4
                else f'{expense_date.year - 1}-{expense_date.year}'
            ),
        }

    @staticmethod
    def create_expense(data):
        expense_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date() if data.get('date') else None
        date_fields = ExpenseService._date_fields(expense_date)
        total_cost = Decimal(data.get('total_cost') or '0')

        from services.finance.expense_reimbursement_group_service import ExpenseReimbursementGroupService
        from services.finance.expense_sync_service import ExpenseSyncService
        reimbursement_group_id = (
            int(data['reimbursement_group_id']) if data.get('reimbursement_group_id')
            else ExpenseReimbursementGroupService.get_default_group().id
        )

        expense = Expense(
            family_id=db_helpers.get_family_id(),
            date=expense_date,
            **date_fields,
            description=data.get('description'),
            expense_type=data.get('expense_type'),
            credit_card_id=int(data['credit_card_id']) if data.get('credit_card_id') else None,
            account_id=int(data['account_id']) if data.get('account_id') else None,
            covered_miles=int(data['covered_miles']) if data.get('covered_miles') else None,
            rate_per_mile=Decimal(data['rate_per_mile']) if data.get('rate_per_mile') else None,
            days=int(data.get('days') or 1),
            cost=total_cost,
            total_cost=total_cost,
            vehicle_registration=data.get('vehicle_registration') or None,
            paid_for=data.get('paid_for') == 'on',
            submitted=data.get('submitted') == 'on',
            reimbursed=data.get('reimbursed') == 'on',
            reimbursement_group_id=reimbursement_group_id,
        )
        expense.payday_period = ExpenseSyncService.get_period_key_for_expense(expense) if expense_date else None
        db.session.add(expense)
        db.session.commit()
        return expense

    @staticmethod
    def update_expense(expense_id, data):
        expense = family_get_or_404(Expense, expense_id)
        if data.get('date'):
            expense.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        for field, value in ExpenseService._date_fields(expense.date).items():
            setattr(expense, field, value)

        expense.description = data.get('description', expense.description)
        expense.expense_type = data.get('expense_type', expense.expense_type)
        expense.credit_card_id = int(data['credit_card_id']) if data.get('credit_card_id') else None
        expense.account_id = int(data['account_id']) if data.get('account_id') else None
        expense.covered_miles = int(data['covered_miles']) if data.get('covered_miles') else None
        expense.rate_per_mile = Decimal(data['rate_per_mile']) if data.get('rate_per_mile') else None
        expense.days = int(data.get('days') or expense.days or 1)
        if data.get('total_cost'):
            expense.cost = Decimal(data['total_cost'])
            expense.total_cost = Decimal(data['total_cost'])
        expense.vehicle_registration = data.get('vehicle_registration') or expense.vehicle_registration
        expense.paid_for = data.get('paid_for') == 'on'
        expense.submitted = data.get('submitted') == 'on'
        expense.reimbursed = data.get('reimbursed') == 'on'
        if data.get('reimbursement_group_id') and not expense.reimbursed:
            expense.reimbursement_group_id = int(data['reimbursement_group_id'])

        from services.finance.expense_sync_service import ExpenseSyncService
        expense.payday_period = ExpenseSyncService.get_period_key_for_expense(expense) if expense.date else None
        db.session.commit()
        return expense

    @staticmethod
    def delete_expense(expense_id):
        expense = family_get_or_404(Expense, expense_id)
        db.session.delete(expense)
        db.session.commit()

    @staticmethod
    def set_period(expense_id, period_value):
        """Manually assign (or clear) which claim period an expense belongs to.

        period_value of '' or 'auto' clears the override so the period reverts
        to being derived from the expense date. Otherwise it must be 'YYYY-MM'.
        Raises ValueError if the expense's current period is already settled/locked.
        """
        from models.transactions import Transaction
        from services.finance.expense_sync_service import ExpenseSyncService

        expense = family_get_or_404(Expense, expense_id)

        current_key = expense.claim_group or ExpenseSyncService.get_period_key_for_expense(expense)
        locked = bool(expense.reimbursed)
        if not locked and current_key:
            txn = family_query(Transaction).filter(Transaction.claim_group == current_key).first()
            if txn and txn.is_paid:
                locked = True
        if locked:
            raise ValueError("This expense's period is already settled and can't be reassigned.")

        period_value = (period_value or '').strip()
        if period_value in ('', 'auto'):
            expense.claim_group = None
        else:
            if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', period_value):
                raise ValueError('Invalid period format — expected YYYY-MM.')
            expense.claim_group = period_value

        db.session.commit()
        return expense


    @staticmethod
    def bulk_delete_expenses(expense_ids):
        deleted = 0
        for expense_id in expense_ids:
            expense = family_query(Expense).filter_by(id=expense_id).first()
            if expense:
                db.session.delete(expense)
                deleted += 1
        db.session.commit()
        return deleted
