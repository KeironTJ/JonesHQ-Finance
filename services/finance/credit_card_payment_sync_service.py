"""Synchronize linked credit-card payments and bank transactions."""
from datetime import datetime

from extensions import db
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.transactions import Transaction
from services.finance.balance_service import BalanceService
from services.finance.credit_card_helpers import get_or_create_payment_vendor
from services.finance.credit_card_statement_service import CreditCardStatementService
from utils.db_helpers import family_get, family_query


class CreditCardPaymentSyncService:
    @staticmethod
    def sync_bank_transaction_to_payment(bank_txn):
        """Propagate bank-side edits to the linked unpaid card payment."""
        if not bank_txn.credit_card_id:
            return None

        cc_payment = family_query(CreditCardTransaction).filter_by(
            credit_card_id=bank_txn.credit_card_id,
            bank_transaction_id=bank_txn.id,
        ).first()
        if not cc_payment or cc_payment.is_paid:
            return None

        card = family_get(CreditCard, cc_payment.credit_card_id)
        if card:
            cc_payment.vendor_id = get_or_create_payment_vendor(
                card, bank_txn.account_id
            ).id

        if bank_txn.transaction_date != cc_payment.date:
            cc_payment.date = bank_txn.transaction_date
            cc_payment.day_name = bank_txn.transaction_date.strftime('%A')
            cc_payment.week = (
                f'{bank_txn.transaction_date.isocalendar()[1]:02d}-'
                f'{bank_txn.transaction_date.year}'
            )
            cc_payment.month = bank_txn.transaction_date.strftime('%Y-%m')

        if bank_txn.amount != cc_payment.amount:
            cc_payment.amount = abs(float(bank_txn.amount))

        cc_payment.is_paid = bank_txn.is_paid
        cc_payment.is_fixed = True
        db.session.flush()
        CreditCardStatementService.refresh_after_changes(
            [cc_payment.credit_card_id], preserve_ids=[cc_payment.id],
        )
        return cc_payment

    @staticmethod
    def sync_payment_to_bank_transaction(cc_payment):
        """Propagate card-payment edits to its linked unpaid bank transaction."""
        if not cc_payment.bank_transaction_id:
            return None

        bank_txn = family_get(Transaction, cc_payment.bank_transaction_id)
        if not bank_txn or bank_txn.is_paid:
            return None

        card = family_get(CreditCard, cc_payment.credit_card_id)
        if card:
            bank_txn.vendor_id = get_or_create_payment_vendor(
                card, bank_txn.account_id
            ).id

        if cc_payment.date != bank_txn.transaction_date:
            bank_txn.transaction_date = cc_payment.date
            bank_txn.year_month = cc_payment.date.strftime('%Y-%m')
            bank_txn.week_year = (
                f'{cc_payment.date.isocalendar()[1]:02d}-{cc_payment.date.year}'
            )
            bank_txn.day_name = cc_payment.date.strftime('%a')

        if -abs(float(cc_payment.amount)) != bank_txn.amount:
            bank_txn.amount = -abs(float(cc_payment.amount))

        bank_txn.is_paid = cc_payment.is_paid
        bank_txn.is_fixed = cc_payment.is_fixed
        bank_txn.updated_at = datetime.now()
        db.session.flush()

        if bank_txn.account_id:
            BalanceService.recalculate(
                account_ids=[bank_txn.account_id], commit=False,
            )
        return bank_txn
