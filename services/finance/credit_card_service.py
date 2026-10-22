"""Card management, manual transactions, and payment/bank synchronization.

Amounts follow the card sign convention: negative amounts increase debt and
positive amounts reduce it. Statement chains and interest calculation belong
to :mod:`services.finance.credit_card_statement_service`.
"""
from datetime import datetime, date
from decimal import Decimal
from dateutil.relativedelta import relativedelta
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.accounts import Account
from models.categories import Category
from models.transactions import Transaction
from models.vendors import Vendor
from services.finance.payday_service import PaydayService
from services.finance.credit_card_helpers import (
    get_or_create_card_vendor,
    get_or_create_payment_vendor,
)
from extensions import db
from utils import db_helpers
from utils.db_helpers import family_query, family_get, family_get_or_404


class CreditCardService:
    @staticmethod
    def get_summary():
        cards = family_query(CreditCard).filter_by(is_active=True).all()
        return {
            'count': len(cards),
            'total_balance': sum(Decimal(str(card.current_balance or 0)) for card in cards),
            'total_limit': sum(Decimal(str(card.credit_limit or 0)) for card in cards),
            'total_available': sum(Decimal(str(card.available_credit or 0)) for card in cards),
        }

    @staticmethod
    def _card_values(data, existing=None):
        values = {
            'card_name': data.get('card_name'),
            'annual_apr': float(data.get('annual_apr', 0)),
            'monthly_apr': float(data.get('monthly_apr', 0)),
            'min_payment_percent': float(data.get('min_payment_percent', 1.0)),
            'credit_limit': float(data.get('credit_limit', 0)),
            'default_transfer_fee_percent': (
                float(data['default_transfer_fee_percent'])
                if data.get('default_transfer_fee_percent') else None
            ),
            'set_payment': float(data['set_payment']) if data.get('set_payment') else None,
            'statement_date': int(data['statement_date']) if data.get('statement_date') else None,
            'current_balance': float(data.get('current_balance', 0)),
            'is_active': data.get('is_active') == 'on',
            'default_payment_account_id': (
                int(data['default_payment_account_id'])
                if data.get('default_payment_account_id') else None
            ),
            'owner_id': (
                db_helpers.get_current_user_id() if data.get('visibility') == 'private' else None
            ),
        }
        if data.get('start_date'):
            values['start_date'] = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        elif existing is not None:
            values['start_date'] = existing.start_date
        values['purchase_0_percent_until'] = (
            datetime.strptime(data['purchase_0_percent_until'], '%Y-%m-%d').date()
            if data.get('purchase_0_percent_until') else None
        )
        values['balance_transfer_0_percent_until'] = (
            datetime.strptime(data['balance_transfer_0_percent_until'], '%Y-%m-%d').date()
            if data.get('balance_transfer_0_percent_until') else None
        )
        return values

    @staticmethod
    def create_card(data):
        card = CreditCard(family_id=db_helpers.get_family_id(), **CreditCardService._card_values(data))
        card.available_credit = float(card.credit_limit) - float(card.current_balance)
        db.session.add(card)
        db.session.commit()
        return card

    @staticmethod
    def update_card(card_id, data):
        card = family_get_or_404(CreditCard, card_id)
        for field, value in CreditCardService._card_values(data, card).items():
            setattr(card, field, value)
        card.available_credit = float(card.credit_limit) - float(card.current_balance)
        card.updated_at = datetime.now()
        db.session.commit()
        return card

    @staticmethod
    def delete_card(card_id):
        card = family_get_or_404(CreditCard, card_id)
        name = card.card_name
        db.session.delete(card)
        db.session.commit()
        return name

    @staticmethod
    def toggle_transaction_fixed(transaction_id):
        transaction = family_get_or_404(CreditCardTransaction, transaction_id)
        transaction.is_fixed = not transaction.is_fixed
        db.session.commit()
        return transaction

    @staticmethod
    def delete_transaction(transaction_id):
        transaction = family_get_or_404(CreditCardTransaction, transaction_id)
        from models.plans import PlanItem

        for plan_item in family_query(PlanItem).filter_by(
            credit_card_transaction_id=transaction.id,
        ).all():
            plan_item.credit_card_transaction = None
        card_id = transaction.credit_card_id
        account_id = None
        if transaction.bank_transaction_id:
            bank_transaction = family_get(Transaction, transaction.bank_transaction_id)
            if bank_transaction:
                account_id = bank_transaction.account_id
                db.session.delete(bank_transaction)

        linked_card_id = None
        if transaction.linked_cc_transaction_id:
            linked_txn = family_get(CreditCardTransaction, transaction.linked_cc_transaction_id)
            if linked_txn:
                for plan_item in family_query(PlanItem).filter_by(
                    credit_card_transaction_id=linked_txn.id,
                ).all():
                    plan_item.credit_card_transaction = None
                linked_card_id = linked_txn.credit_card_id
                # Clear both sides of the FK pair first to avoid a circular
                # dependency when SQLAlchemy orders the DELETE statements.
                transaction.linked_cc_transaction_id = None
                linked_txn.linked_cc_transaction_id = None
                db.session.flush()
                db.session.delete(linked_txn)

        db.session.delete(transaction)
        db.session.commit()
        CreditCardTransaction.recalculate_card_balance(card_id, commit=True)
        if linked_card_id and linked_card_id != card_id:
            CreditCardTransaction.recalculate_card_balance(linked_card_id, commit=True)
        return card_id, account_id

    @staticmethod
    def create_balance_transfer(data):
        """Move debt from one of the family's cards to another.

        Creates two linked CreditCardTransaction rows:
          - On the FROM card: a 'Balance Transfer' transaction that reduces
            debt (positive amount) equal to the transferred amount.
          - On the TO card: a 'Balance Transfer' transaction that increases
            debt (negative amount) equal to the transferred amount PLUS the
            transfer fee.
        """
        from_card_id = int(data['from_card_id'])
        to_card_id = int(data['to_card_id'])
        if from_card_id == to_card_id:
            raise ValueError('Source and destination cards must be different')

        amount = Decimal(str(data.get('amount') or '0'))
        if amount <= 0:
            raise ValueError('Amount must be greater than 0')

        fee_percent = Decimal(str(data.get('fee_percent') or '0'))
        transfer_date = date.fromisoformat(data['transfer_date'])
        is_paid = data.get('is_paid') == '1'
        description = (data.get('description') or '').strip()

        from_card = family_get_or_404(CreditCard, from_card_id)
        to_card = family_get_or_404(CreditCard, to_card_id)

        fee_amount = (amount * fee_percent / Decimal('100')).quantize(Decimal('0.01'))
        total_debit = amount + fee_amount

        week = f'{transfer_date.isocalendar()[1]:02d}-{transfer_date.year}'
        month = transfer_date.strftime('%Y-%m')
        day_name = transfer_date.strftime('%A')
        bt_apr = to_card.get_current_balance_transfer_apr(transfer_date)

        from_txn = CreditCardTransaction(
            family_id=db_helpers.get_family_id(),
            credit_card_id=from_card_id,
            date=transfer_date,
            day_name=day_name,
            week=week,
            month=month,
            item=description or f'Balance transfer to {to_card.card_name}',
            transaction_type='Balance Transfer',
            amount=amount,
            is_paid=is_paid,
            is_fixed=True,
        )
        db.session.add(from_txn)
        db.session.flush()

        to_txn = CreditCardTransaction(
            family_id=db_helpers.get_family_id(),
            credit_card_id=to_card_id,
            date=transfer_date,
            day_name=day_name,
            week=week,
            month=month,
            item=description or f'Balance transfer from {from_card.card_name}',
            transaction_type='Balance Transfer',
            amount=-total_debit,
            applied_apr=bt_apr,
            is_promotional_rate=(bt_apr == 0),
            is_paid=is_paid,
            is_fixed=True,
            linked_cc_transaction_id=from_txn.id,
        )
        db.session.add(to_txn)
        db.session.flush()

        from_txn.linked_cc_transaction_id = to_txn.id
        db.session.commit()

        CreditCardTransaction.recalculate_card_balance(from_card_id, commit=True)
        CreditCardTransaction.recalculate_card_balance(to_card_id, commit=True)

        return {
            'from_txn': from_txn,
            'to_txn': to_txn,
            'from_card': from_card,
            'to_card': to_card,
            'fee_amount': fee_amount,
            'total_debit': total_debit,
        }

    @staticmethod
    def toggle_transaction_paid(transaction_id):
        transaction = family_get_or_404(CreditCardTransaction, transaction_id)
        transaction.is_paid = not transaction.is_paid
        if transaction.is_paid:
            transaction.is_fixed = True
        if transaction.bank_transaction_id and transaction.bank_transaction:
            transaction.bank_transaction.is_paid = transaction.is_paid
        from models.expenses import Expense
        expense = family_query(Expense).filter_by(
            credit_card_transaction_id=transaction.id
        ).first()
        if expense:
            expense.paid_for = transaction.is_paid
        db.session.commit()
        return transaction

    @staticmethod
    def update_transaction(transaction_id, data):
        transaction = family_get_or_404(CreditCardTransaction, transaction_id)
        if data.get('txn_date'):
            transaction.date = datetime.strptime(
                data['txn_date'], '%Y-%m-%d'
            ).date()
            transaction.day_name = transaction.date.strftime('%A')
            transaction.week = (
                f'{transaction.date.isocalendar()[1]:02d}-{transaction.date.year}'
            )
            transaction.month = transaction.date.strftime('%Y-%m')
        transaction.transaction_type = data.get('txn_type')
        transaction.item = data.get('txn_item')
        transaction.assigned_to = data.get('assigned_to', transaction.assigned_to)
        transaction.amount = float(data.get('txn_amount'))
        vendor_id = int(data['vendor_id']) if data.get('vendor_id') else None
        transaction.vendor_id = family_get(Vendor, vendor_id).id if vendor_id else None
        transaction.is_fixed = data.get('txn_fixed') == '1'
        transaction.is_paid = data.get('txn_paid') == '1'
        db.session.commit()
        return transaction

    @staticmethod
    def update_payment_transaction(transaction_id, data):
        transaction = family_get_or_404(CreditCardTransaction, transaction_id)
        card = family_get_or_404(CreditCard, transaction.credit_card_id)
        payment_amount = abs(float(data.get('payment_amount')))
        if data.get('payment_date'):
            transaction.date = datetime.strptime(
                data['payment_date'], '%Y-%m-%d'
            ).date()
            transaction.day_name = transaction.date.strftime('%A')
            transaction.week = (
                f'{transaction.date.isocalendar()[1]:02d}-{transaction.date.year}'
            )
            transaction.month = transaction.date.strftime('%Y-%m')
        transaction.amount = payment_amount
        transaction.is_fixed = True

        account_id = data.get('account_id')
        if account_id:
            payment_category = family_query(Category).filter_by(
                head_budget='Credit Cards', sub_budget=card.card_name
            ).first() or family_query(Category).filter_by(
                head_budget='Credit Cards'
            ).first()
            vendor = get_or_create_payment_vendor(card, account_id)
            transaction.vendor_id = vendor.id
            bank_transaction = None
            if transaction.bank_transaction_id:
                bank_transaction = family_get(Transaction, transaction.bank_transaction_id)
            if bank_transaction:
                bank_transaction.transaction_date = transaction.date
                bank_transaction.amount = -payment_amount
                bank_transaction.account_id = int(account_id)
                bank_transaction.vendor_id = vendor.id
                bank_transaction.description = f'Payment to {card.card_name}'
                bank_transaction.item = 'Credit Card Payment'
                if payment_category:
                    bank_transaction.category_id = payment_category.id
                bank_transaction.updated_at = datetime.now()
            else:
                bank_transaction = Transaction(
                    family_id=db_helpers.get_family_id(),
                    account_id=int(account_id),
                    category_id=payment_category.id if payment_category else None,
                    vendor_id=vendor.id,
                    amount=-payment_amount,
                    transaction_date=transaction.date,
                    description=f'Payment to {card.card_name}',
                    item='Credit Card Payment',
                    payment_type='Card Payment',
                    is_paid=transaction.is_paid,
                    is_fixed=True,
                    credit_card_id=card.id,
                    year_month=transaction.date.strftime('%Y-%m'),
                    week_year=(
                        f'{transaction.date.isocalendar()[1]:02d}-{transaction.date.year}'
                    ),
                    day_name=transaction.date.strftime('%A'),
                    payday_period=PaydayService.get_period_for_date(transaction.date),
                )
                db.session.add(bank_transaction)
                db.session.flush()
                transaction.bank_transaction_id = bank_transaction.id
        db.session.commit()
        return transaction, int(account_id) if account_id else None

    @staticmethod
    def create_transactions(card_id, data):
        card = family_get_or_404(CreditCard, card_id)
        transaction_date = date.fromisoformat(data['txn_date'])
        transaction_type = data['txn_type']
        item = data['txn_item']
        amount = Decimal(str(data.get('txn_amount') or '0'))
        category_id = int(data['category_id']) if data.get('category_id') else None
        vendor_id = int(data['vendor_id']) if data.get('vendor_id') else None
        account_id = int(data['account_id']) if data.get('account_id') else None
        is_fixed = data.get('txn_fixed') == '1'
        is_paid = data.get('txn_paid') == '1'
        recurring = data.get('is_recurring') == 'on'
        occurrences = int(data.get('occurrences') or 1) if recurring else 1
        if occurrences < 1:
            raise ValueError('Number of occurrences must be at least 1')

        category = family_get(Category, category_id) if category_id else None
        vendor = family_get(Vendor, vendor_id) if vendor_id else None
        card_vendor = get_or_create_payment_vendor(card, account_id) if transaction_type == 'Payment' else None
        frequency = data.get('frequency', 'monthly')
        transactions = []
        for occurrence in range(occurrences):
            offsets = {
                'weekly': {'weeks': occurrence},
                'monthly': {'months': occurrence},
                'yearly': {'years': occurrence},
            }
            current_date = transaction_date + relativedelta(**offsets.get(frequency, {}))
            transaction = CreditCardTransaction(
                family_id=db_helpers.get_family_id(),
                credit_card_id=card_id,
                category_id=category_id,
                vendor_id=(card_vendor or vendor).id if (card_vendor or vendor) else None,
                date=current_date,
                day_name=current_date.strftime('%A'),
                week=f'{current_date.isocalendar()[1]:02d}-{current_date.year}',
                month=current_date.strftime('%Y-%m'),
                head_budget=category.head_budget if category else None,
                sub_budget=category.sub_budget if category else None,
                item=item,
                assigned_to=data.get('assigned_to', ''),
                transaction_type=transaction_type,
                amount=amount,
                is_paid=is_paid,
                is_fixed=is_fixed,
            )
            db.session.add(transaction)
            db.session.flush()

            if transaction_type == 'Payment' and account_id:
                payment_category = family_query(Category).filter_by(
                    head_budget='Credit Cards', sub_budget=card.card_name
                ).first() or family_query(Category).filter_by(
                    head_budget='Credit Cards'
                ).first()
                bank_transaction = Transaction(
                    family_id=db_helpers.get_family_id(),
                    account_id=account_id,
                    category_id=payment_category.id if payment_category else None,
                    vendor_id=card_vendor.id,
                    amount=-abs(amount),
                    transaction_date=current_date,
                    description=f'Payment to {card.card_name}',
                    item='Credit Card Payment',
                    payment_type='Card Payment',
                    is_paid=is_paid,
                    is_fixed=is_fixed,
                    credit_card_id=card_id,
                    year_month=current_date.strftime('%Y-%m'),
                    week_year=f'{current_date.isocalendar()[1]:02d}-{current_date.year}',
                    day_name=current_date.strftime('%A'),
                    payday_period=PaydayService.get_period_for_date(current_date),
                )
                db.session.add(bank_transaction)
                db.session.flush()
                transaction.bank_transaction_id = bank_transaction.id
            transactions.append(transaction)

        db.session.commit()
        CreditCardTransaction.recalculate_card_balance(card_id, commit=True)
        return transactions

    
    

    
    
    
    

    
    
    @staticmethod
    def sync_bank_transaction_to_payment(bank_txn):
        """
        Sync edits from a bank Transaction to its linked CC Payment transaction.

        Called from the transaction-edit blueprint whenever a bank Transaction that
        has a credit_card_id is saved.  Keeps the two records in step for date, amount,
        and paid status.

        Locking behaviour: when synced, the CC payment is always marked is_fixed=True
        (regardless of the bank transaction's is_fixed value) because a real bank
        transaction is now linked — it should not be overwritten by regeneration.

        Does nothing (returns None) if:
          - bank_txn has no credit_card_id
          - no matching CC payment is found
          - the CC payment is already marked is_paid (historical record — do not touch)

        Args:
            bank_txn: Transaction instance whose credit_card_id links it to a CC payment.

        Returns:
            CreditCardTransaction — the updated payment, or None if no action taken.

        Side effects:
            Flushes the session.  Calls recalculate_card_balance() on the CC.
            Does NOT commit — the caller's transaction boundary handles that.
        """
        if not bank_txn.credit_card_id:
            return None
        
        # Find linked credit card payment
        cc_payment = family_query(CreditCardTransaction).filter_by(
            credit_card_id=bank_txn.credit_card_id,
            bank_transaction_id=bank_txn.id
        ).first()
        
        if not cc_payment:
            return None
        
        # Only sync if not paid (avoid changing historical data)
        if cc_payment.is_paid:
            return None

        card = family_get(CreditCard, cc_payment.credit_card_id)
        if card:
            cc_payment.vendor_id = get_or_create_payment_vendor(
                card, bank_txn.account_id
            ).id
        
        # Sync date
        if bank_txn.transaction_date != cc_payment.date:
            cc_payment.date = bank_txn.transaction_date
            cc_payment.day_name = bank_txn.transaction_date.strftime('%A')
            cc_payment.week = f"{bank_txn.transaction_date.isocalendar()[1]:02d}-{bank_txn.transaction_date.year}"
            cc_payment.month = bank_txn.transaction_date.strftime('%Y-%m')
        
        # Sync amount (bank expense = credit card payment)
        if bank_txn.amount != cc_payment.amount:
            cc_payment.amount = abs(float(bank_txn.amount))
        
        # Sync paid status; always lock the CC payment since it has a real bank transaction
        cc_payment.is_paid = bank_txn.is_paid
        cc_payment.is_fixed = True  # Bank transaction is linked — protect from regen
        
        db.session.flush()
        
        # Recalculate credit card balance
        CreditCardTransaction.recalculate_card_balance(cc_payment.credit_card_id)
        
        return cc_payment

    @staticmethod
    def sync_payment_to_bank_transaction(cc_payment):
        """
        Sync edits from a CC Payment transaction to its linked bank Transaction.

        Called from the credit-card-transaction-edit blueprint whenever a CC Payment
        that has a bank_transaction_id is saved.  Mirrors date, amount, paid status,
        and is_fixed onto the bank record.

        Does nothing (returns None) if:
          - cc_payment has no bank_transaction_id
          - the linked bank transaction no longer exists
          - the bank transaction is already marked is_paid (historical — do not touch)

        Args:
            cc_payment: CreditCardTransaction instance whose bank_transaction_id links
                        it to a bank Transaction.

        Returns:
            Transaction — the updated bank record, or None if no action taken.

        Side effects:
            Flushes the session.  Calls recalculate_account_balance() on the bank account.
            Does NOT commit — the caller's transaction boundary handles that.
        """
        if not cc_payment.bank_transaction_id:
            return None
        
        # Find linked bank transaction
        bank_txn = family_get(Transaction, cc_payment.bank_transaction_id)
        
        if not bank_txn:
            return None
        
        # Only sync if not paid (avoid changing historical data)
        if bank_txn.is_paid:
            return None

        card = family_get(CreditCard, cc_payment.credit_card_id)
        if card:
            bank_txn.vendor_id = get_or_create_payment_vendor(
                card, bank_txn.account_id
            ).id
        
        # Sync date
        if cc_payment.date != bank_txn.transaction_date:
            bank_txn.transaction_date = cc_payment.date
            bank_txn.year_month = cc_payment.date.strftime('%Y-%m')
            bank_txn.week_year = f"{cc_payment.date.isocalendar()[1]:02d}-{cc_payment.date.year}"
            bank_txn.day_name = cc_payment.date.strftime('%a')
        
        # Sync amount (credit card payment = bank expense)
        if abs(float(cc_payment.amount)) != bank_txn.amount:
            bank_txn.amount = abs(float(cc_payment.amount))
        
        # Sync paid status
        bank_txn.is_paid = cc_payment.is_paid
        bank_txn.is_fixed = cc_payment.is_fixed
        bank_txn.updated_at = datetime.now()
        
        db.session.flush()
        
        # Recalculate bank account balance
        if bank_txn.account_id:
            Transaction.recalculate_account_balance(bank_txn.account_id)
        
        return bank_txn
