from datetime import datetime, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from extensions import db
from models.transactions import Transaction
from models.credit_card_transactions import CreditCardTransaction
from models.expenses import Expense
from models.loan_payments import LoanPayment
from models.accounts import Account
from models.categories import Category
from models.vendors import Vendor
from services.payday_service import PaydayService
from utils import db_helpers
from utils.db_helpers import family_get, family_get_or_404, family_query


class TransactionService:
    @staticmethod
    def _int_value(data, key):
        value = data.get(key)
        return int(value) if value not in (None, '') else None

    @staticmethod
    def _adjust_working_day(transaction_date, direction):
        while transaction_date.weekday() >= 5:
            transaction_date += timedelta(days=1 if direction == 'next' else -1)
        return transaction_date

    @staticmethod
    def create_transactions(data):
        transaction_date = datetime.strptime(
            data['transaction_date'], '%Y-%m-%d'
        ).date()
        is_recurring = data.get('is_recurring') == 'on'
        occurrences = int(data.get('occurrences') or 1) if is_recurring else 1
        if occurrences < 1:
            raise ValueError('Number of occurrences must be at least 1')

        frequency = data.get('frequency', 'monthly')
        adjust_working_days = data.get('adjust_working_days') == 'on'
        weekend_adjustment = data.get('weekend_adjustment', 'previous')
        transactions = []
        amount = float(data['amount'])

        for occurrence in range(occurrences):
            current_date = transaction_date
            if occurrence:
                offsets = {
                    'weekly': {'weeks': occurrence},
                    '4weekly': {'weeks': occurrence * 4},
                    'monthly': {'months': occurrence},
                    'quarterly': {'months': occurrence * 3},
                    'yearly': {'years': occurrence},
                }
                current_date += relativedelta(**offsets.get(frequency, {}))
            if adjust_working_days:
                current_date = TransactionService._adjust_working_day(
                    current_date, weekend_adjustment
                )

            year_month = current_date.strftime('%Y-%m')
            week_year = f'{current_date.isocalendar()[1]:02d}-{current_date.year}'
            day_name = current_date.strftime('%a')
            payday_period = PaydayService.get_period_for_date(current_date)
            if occurrence == 0:
                year_month = data.get('year_month', '').strip() or year_month
                week_year = data.get('week_year', '').strip() or week_year
                day_name = data.get('day_name', '').strip() or day_name
                payday_period = (
                    data.get('payday_period_override', '').strip()
                    or payday_period
                )

            transactions.append(Transaction(
                family_id=db_helpers.get_family_id(),
                account_id=TransactionService._int_value(data, 'account_id'),
                category_id=TransactionService._int_value(data, 'category_id'),
                vendor_id=(
                    int(data['vendor_id']) if data.get('vendor_id') else None
                ),
                amount=amount,
                transaction_date=current_date,
                description=data.get('description', ''),
                item=data.get('item', ''),
                assigned_to=data.get('assigned_to', ''),
                payment_type=data.get('payment_type', ''),
                is_paid=data.get('is_paid') == '1',
                year_month=year_month,
                week_year=week_year,
                day_name=day_name,
                payday_period=payday_period,
            ))

        db.session.add_all(transactions)
        db.session.commit()
        return transactions

    @staticmethod
    def update_transaction(transaction_id, data):
        transaction = family_get_or_404(Transaction, transaction_id)
        old_account_id = transaction.account_id
        transaction.account_id = TransactionService._int_value(data, 'account_id')
        transaction.category_id = TransactionService._int_value(data, 'category_id')
        transaction.vendor_id = TransactionService._int_value(data, 'vendor_id')
        transaction.amount = float(data.get('amount'))
        transaction.transaction_date = datetime.strptime(
            data.get('transaction_date'), '%Y-%m-%d'
        ).date()
        transaction.description = data.get('description', '')
        transaction.item = data.get('item', '')
        transaction.assigned_to = data.get('assigned_to', '')
        transaction.payment_type = data.get('payment_type', '')
        transaction.is_paid = data.get('is_paid') == '1'
        transaction.is_fixed = data.get('txn_fixed') == '1'

        transaction.year_month = data.get('year_month', '').strip() or transaction.transaction_date.strftime('%Y-%m')
        transaction.week_year = data.get('week_year', '').strip() or (
            f'{transaction.transaction_date.isocalendar()[1]:02d}-{transaction.transaction_date.year}'
        )
        transaction.day_name = data.get('day_name', '').strip() or transaction.transaction_date.strftime('%a')
        transaction.payday_period = data.get('payday_period_override', '').strip() or PaydayService.get_period_for_date(transaction.transaction_date)
        transaction.updated_at = datetime.now()

        linked_account_id = None
        if transaction.linked_transaction_id:
            linked_transaction = family_get(Transaction, transaction.linked_transaction_id)
            if linked_transaction:
                linked_account_id = linked_transaction.account_id
                linked_transaction.amount = -transaction.amount
                linked_transaction.transaction_date = transaction.transaction_date
                linked_transaction.item = transaction.item
                linked_transaction.is_paid = transaction.is_paid
                direction = 'from' if transaction.amount < 0 else 'to'
                account_name = transaction.account.name if transaction.account else 'Unknown'
                linked_transaction.description = f'Transfer {direction} {account_name}'
                linked_transaction.year_month = transaction.transaction_date.strftime('%Y-%m')
                linked_transaction.week_year = (
                    f'{transaction.transaction_date.isocalendar()[1]:02d}-{transaction.transaction_date.year}'
                )
                linked_transaction.day_name = transaction.transaction_date.strftime('%a')
                linked_transaction.payday_period = PaydayService.get_period_for_date(
                    transaction.transaction_date
                )
                linked_transaction.updated_at = datetime.now()

        db.session.commit()
        return transaction, old_account_id, linked_account_id

    @staticmethod
    def delete_transaction(transaction_id):
        transaction = family_get_or_404(Transaction, transaction_id)
        account_id = transaction.account_id
        account_name = transaction.account.name if transaction.account else 'Unknown'
        linked_card_id = None
        linked_transfer_account_id = None

        if transaction.credit_card_id:
            linked_payment = family_query(CreditCardTransaction).filter_by(
                bank_transaction_id=transaction.id
            ).first()
            if linked_payment:
                linked_card_id = linked_payment.credit_card_id
                db.session.delete(linked_payment)

        if transaction.linked_transaction_id:
            linked_transaction = family_get(Transaction, transaction.linked_transaction_id)
            if linked_transaction:
                linked_transfer_account_id = linked_transaction.account_id
                db.session.delete(linked_transaction)

        linked_expenses = family_query(Expense).filter(
            (Expense.bank_transaction_id == transaction_id)
            | (Expense.credit_card_transaction_id == transaction_id)
        ).all()
        for expense in linked_expenses:
            if expense.bank_transaction_id == transaction_id:
                expense.bank_transaction_id = None
            if expense.credit_card_transaction_id == transaction_id:
                expense.credit_card_transaction_id = None

        db.session.delete(transaction)
        db.session.commit()
        return account_id, account_name, linked_card_id, linked_transfer_account_id

    @staticmethod
    def toggle_paid(transaction_id):
        transaction = family_get_or_404(Transaction, transaction_id)
        transaction.is_paid = not transaction.is_paid
        transaction.updated_at = datetime.now()

        if transaction.loan_id:
            loan_payment = family_query(LoanPayment).filter_by(
                bank_transaction_id=transaction.id
            ).first()
            if loan_payment:
                loan_payment.is_paid = transaction.is_paid

        if transaction.credit_card_id:
            card_payment = family_query(CreditCardTransaction).filter_by(
                bank_transaction_id=transaction.id
            ).first()
            if card_payment:
                card_payment.is_paid = transaction.is_paid

        if transaction.linked_transaction_id:
            linked_transaction = family_get(Transaction, transaction.linked_transaction_id)
            if linked_transaction:
                linked_transaction.is_paid = transaction.is_paid
                linked_transaction.updated_at = datetime.now()

        expense = family_query(Expense).filter_by(
            bank_transaction_id=transaction.id
        ).first()
        if expense:
            expense.paid_for = transaction.is_paid

        db.session.commit()
        return transaction

    @staticmethod
    def create_transfer(data):
        from_account_id = int(data['from_account_id'])
        to_account_id = int(data['to_account_id'])
        amount = abs(float(data['amount']))
        transfer_date = datetime.strptime(data['transaction_date'], '%Y-%m-%d').date()
        occurrences = int(data.get('occurrences') or 1) if data.get('is_recurring') == 'on' else 1
        if from_account_id == to_account_id:
            raise ValueError('Cannot transfer to the same account')
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')
        if occurrences < 1:
            raise ValueError('Number of occurrences must be at least 1')

        from_account = family_get(Account, from_account_id)
        to_account = family_get(Account, to_account_id)
        if not from_account or not to_account:
            raise ValueError('Invalid account selected')

        from_vendor = family_query(Vendor).filter_by(name=to_account.name).first()
        if not from_vendor:
            from_vendor = Vendor(family_id=db_helpers.get_family_id(), name=to_account.name)
            db.session.add(from_vendor)
            db.session.flush()
        to_vendor = family_query(Vendor).filter_by(name=from_account.name).first()
        if not to_vendor:
            to_vendor = Vendor(family_id=db_helpers.get_family_id(), name=from_account.name)
            db.session.add(to_vendor)
            db.session.flush()

        category = None
        if data.get('category_id'):
            category = family_get(Category, int(data['category_id']))
            if not category:
                raise ValueError('Invalid category selected')
        else:
            category = family_query(Category).filter_by(
                head_budget='Transfer', sub_budget='Account Transfer'
            ).first()
            if not category:
                category = Category(
                    family_id=db_helpers.get_family_id(),
                    name='Account Transfer',
                    head_budget='Transfer',
                    sub_budget='Account Transfer',
                    category_type='Transfer',
                )
                db.session.add(category)
                db.session.flush()

        frequency = data.get('frequency', 'monthly')
        transactions = []
        for occurrence in range(occurrences):
            offsets = {
                'weekly': {'weeks': occurrence},
                'monthly': {'months': occurrence},
                'yearly': {'years': occurrence},
            }
            current_date = transfer_date + relativedelta(**offsets.get(frequency, {}))
            fields = {
                'family_id': db_helpers.get_family_id(),
                'category_id': category.id,
                'item': data.get('description', 'Transfer'),
                'payment_type': 'Transfer',
                'is_paid': data.get('is_paid') == '1',
                'year_month': current_date.strftime('%Y-%m'),
                'week_year': f'{current_date.isocalendar()[1]:02d}-{current_date.year}',
                'day_name': current_date.strftime('%a'),
                'payday_period': PaydayService.get_period_for_date(current_date),
                'transaction_date': current_date,
            }
            outgoing = Transaction(
                **fields, account_id=from_account_id, vendor_id=from_vendor.id,
                amount=-amount, description=f'Transfer to {to_account.name}'
            )
            incoming = Transaction(
                **fields, account_id=to_account_id, vendor_id=to_vendor.id,
                amount=amount, description=f'Transfer from {from_account.name}'
            )
            db.session.add_all([outgoing, incoming])
            db.session.flush()
            outgoing.linked_transaction_id = incoming.id
            incoming.linked_transaction_id = outgoing.id
            transactions.extend([outgoing, incoming])
        db.session.commit()
        return transactions, from_account, to_account

    @staticmethod
    def bulk_edit(transaction_ids, data):
        category_id = data.get('bulk_category_id')
        vendor_id = data.get('bulk_vendor_id')
        payment_type = data.get('bulk_payment_type')
        assigned_to = data.get('bulk_assigned_to')
        paid_value = data.get('bulk_is_paid')
        is_paid = True if paid_value == '1' else False if paid_value == '0' else None
        operation = data.get('bulk_amount_operation')
        operation_value = None
        if operation and data.get('bulk_amount_value'):
            operation_value = Decimal(str(data['bulk_amount_value']))
        affected_accounts = set()
        updated = 0

        for transaction_id in transaction_ids:
            transaction = family_get(Transaction, transaction_id)
            if not transaction:
                continue
            affected_accounts.add(transaction.account_id)
            if category_id:
                transaction.category_id = int(category_id)
            if vendor_id:
                transaction.vendor_id = int(vendor_id)
            if payment_type:
                transaction.payment_type = payment_type
            if assigned_to:
                transaction.assigned_to = assigned_to
            if is_paid is not None:
                transaction.is_paid = is_paid
                if transaction.linked_transaction_id:
                    linked = family_get(Transaction, transaction.linked_transaction_id)
                    if linked:
                        linked.is_paid = is_paid
                        affected_accounts.add(linked.account_id)

            if operation and operation_value is not None:
                current = Decimal(str(transaction.amount))
                if operation == 'set':
                    transaction.amount = operation_value
                elif operation == 'multiply':
                    transaction.amount = current * operation_value / Decimal('100')
                elif operation == 'add':
                    transaction.amount = current + operation_value

                if transaction.linked_transaction_id:
                    linked = family_get(Transaction, transaction.linked_transaction_id)
                    if linked:
                        if operation == 'set':
                            linked.amount = -operation_value
                        elif operation == 'multiply':
                            linked.amount = Decimal(str(linked.amount)) * operation_value / Decimal('100')
                        elif operation == 'add':
                            linked.amount = Decimal(str(linked.amount)) + operation_value
                        affected_accounts.add(linked.account_id)

                if transaction.credit_card_id:
                    card_payment = family_query(CreditCardTransaction).filter_by(
                        bank_transaction_id=transaction.id
                    ).first()
                    if card_payment:
                        if operation == 'set':
                            card_payment.amount = operation_value
                        elif operation == 'multiply':
                            card_payment.amount = Decimal(str(card_payment.amount)) * operation_value / Decimal('100')
                        elif operation == 'add':
                            card_payment.amount = Decimal(str(card_payment.amount)) + operation_value
                if transaction.loan_id:
                    loan_payment = family_query(LoanPayment).filter_by(
                        bank_transaction_id=transaction.id
                    ).first()
                    if loan_payment:
                        if operation == 'set':
                            loan_payment.amount = operation_value
                        elif operation == 'multiply':
                            loan_payment.amount = Decimal(str(loan_payment.amount)) * operation_value / Decimal('100')
                        elif operation == 'add':
                            loan_payment.amount = Decimal(str(loan_payment.amount)) + operation_value
            transaction.updated_at = datetime.now()
            updated += 1

        db.session.commit()
        return updated, affected_accounts

    @staticmethod
    def bulk_delete(transaction_ids):
        deleted = 0
        affected_accounts = set()
        cards_to_recalculate = set()
        for transaction_id in transaction_ids:
            transaction = family_get(Transaction, transaction_id)
            if not transaction:
                continue
            affected_accounts.add(transaction.account_id)
            if transaction.credit_card_id:
                linked_payment = family_query(CreditCardTransaction).filter_by(
                    bank_transaction_id=transaction.id
                ).first()
                if linked_payment:
                    cards_to_recalculate.add(linked_payment.credit_card_id)
                    db.session.delete(linked_payment)
            linked_expenses = family_query(Expense).filter(
                (Expense.bank_transaction_id == transaction_id)
                | (Expense.credit_card_transaction_id == transaction_id)
            ).all()
            for expense in linked_expenses:
                if expense.bank_transaction_id == transaction_id:
                    expense.bank_transaction_id = None
                if expense.credit_card_transaction_id == transaction_id:
                    expense.credit_card_transaction_id = None
            db.session.delete(transaction)
            deleted += 1
        db.session.commit()
        return deleted, affected_accounts, cards_to_recalculate
