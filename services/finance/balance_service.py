from datetime import datetime, timezone
from decimal import Decimal

from extensions import db
from models.accounts import Account
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.transactions import Transaction
from utils import db_helpers


class BalanceService:
    @staticmethod
    def recalculate_account_balance(account_id):
        """Recalculate one household account from its bank transactions."""
        try:
            family_id = db_helpers.get_family_id()
        except RuntimeError:
            family_id = None

        account_query = Account.query.filter_by(id=account_id)
        if family_id is not None:
            account_query = account_query.filter_by(family_id=family_id)
        account = account_query.first()
        if not account:
            return False

        transactions = Transaction.query.filter(
            Transaction.account_id == account_id,
            Transaction.family_id == account.family_id,
        ).all()
        account.balance = sum(
            (Decimal(str(transaction.amount)) for transaction in transactions),
            Decimal('0'),
        )
        account.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return True

    @staticmethod
    def recalculate_credit_card_balance(credit_card_id):
        """Recalculate running and paid balances for one household credit card."""
        try:
            family_id = db_helpers.get_family_id()
        except RuntimeError:
            family_id = None

        card_query = CreditCard.query.filter_by(id=credit_card_id)
        if family_id is not None:
            card_query = card_query.filter_by(family_id=family_id)
        card = card_query.first()
        if not card:
            return False

        transactions = CreditCardTransaction.query.filter_by(
            credit_card_id=credit_card_id,
            family_id=card.family_id,
        ).order_by(
            CreditCardTransaction.date.asc(), CreditCardTransaction.id.asc()
        ).all()

        running_balance = 0.0
        for transaction in transactions:
            running_balance += float(transaction.amount)
            transaction.balance = round(running_balance, 2)
            transaction.credit_available = round(
                float(card.credit_limit) - abs(running_balance), 2
            )

        paid_transactions = CreditCardTransaction.query.filter_by(
            credit_card_id=credit_card_id,
            family_id=card.family_id,
            is_paid=True,
        ).order_by(
            CreditCardTransaction.date.asc(), CreditCardTransaction.id.asc()
        ).all()
        paid_balance = sum(float(transaction.amount) for transaction in paid_transactions)

        card.current_balance = round(paid_balance, 2)
        card.available_credit = round(
            float(card.credit_limit) - abs(paid_balance), 2
        )
        return True

    @staticmethod
    def recalculate(account_ids=(), credit_card_ids=(), commit=True):
        """Recalculate related account/card balances and optionally commit once."""
        accounts = {value for value in account_ids if value is not None}
        cards = {value for value in credit_card_ids if value is not None}
        if not accounts and not cards:
            return
        found = False
        for account_id in accounts:
            found = BalanceService.recalculate_account_balance(account_id) or found
        for card_id in cards:
            found = BalanceService.recalculate_credit_card_balance(card_id) or found
        if commit and found:
            db.session.commit()
