from datetime import datetime
from decimal import Decimal
from extensions import db
from models.expenses import Expense
from models.credit_card_transactions import CreditCardTransaction
from models.transactions import Transaction
from models.accounts import Account
from models.categories import Category
from models.credit_cards import CreditCard
from models.settings import Settings
from flask import current_app


class ExpenseSyncService:
    """Service to sync Expense rows into linked transactions (credit card / bank) and keep them in sync.

    Behavior:
    - If Expense.credit_card_id is present, ensure a CreditCardTransaction exists representing the purchase.
    - If Expense.reimbursed is True, ensure a bank Transaction exists in the configured reimburse account.
    - When flags or amounts change, existing linked rows are updated where possible.

    NOTE: This service intentionally avoids DB schema changes; for a more robust implementation
    add explicit foreign-key fields to `Expense` (e.g. `bank_transaction_id`, `credit_card_transaction_id`).
    """

    @staticmethod
    def reconcile(expense_id):
        exp = Expense.query.get(expense_id)
        if not exp:
            return

        # Respect global toggle to disable automatic syncing of expenses to transactions
        auto_sync = Settings.get_value('expenses.auto_sync', False)
        if not auto_sync:
            current_app.logger.info(f"ExpenseSyncService.reconcile disabled by setting; skipping expense {expense_id}")
            return

        try:
            # Create or update credit card transaction for card-paid expenses
            if exp.credit_card_id:
                ExpenseSyncService._ensure_credit_card_txn(exp)

            # Create or update bank transaction when reimbursed
            if exp.reimbursed:
                ExpenseSyncService._ensure_bank_reimbursement(exp)

            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def bulk_delete_linked_transactions(expense_ids=None):
        """Delete linked bank and credit-card transactions for the given expenses.

        If `expense_ids` is None, operate on all expenses that currently have links.
        Returns a summary dict with counts and lists of affected ids.
        """
        # Collect target expenses
        q = Expense.query
        if expense_ids:
            q = q.filter(Expense.id.in_(expense_ids))

        linked_expenses = q.filter(
            (Expense.bank_transaction_id != None) | (Expense.credit_card_transaction_id != None)
        ).all()

        bank_txn_ids = set()
        cc_txn_ids = set()
        accounts_to_recalc = set()
        cards_to_recalc = set()

        for exp in linked_expenses:
            if exp.bank_transaction_id:
                bank_txn_ids.add(exp.bank_transaction_id)
            if exp.credit_card_transaction_id:
                cc_txn_ids.add(exp.credit_card_transaction_id)

        # Inspect and collect affected accounts/cards
        if bank_txn_ids:
            txns = Transaction.query.filter(Transaction.id.in_(list(bank_txn_ids))).all()
            for t in txns:
                if t.account_id:
                    accounts_to_recalc.add(t.account_id)

        if cc_txn_ids:
            ccs = CreditCardTransaction.query.filter(CreditCardTransaction.id.in_(list(cc_txn_ids))).all()
            for c in ccs:
                if c.credit_card_id:
                    cards_to_recalc.add(c.credit_card_id)

        summary = {
            'expenses_found': [e.id for e in linked_expenses],
            'bank_txn_ids': list(bank_txn_ids),
            'cc_txn_ids': list(cc_txn_ids),
            'deleted_bank_txns': 0,
            'deleted_cc_txns': 0,
            'accounts_recalced': list(accounts_to_recalc),
            'cards_recalced': list(cards_to_recalc)
        }

        # Delete credit card transactions
        if cc_txn_ids:
            CreditCardTransaction.query.filter(CreditCardTransaction.id.in_(list(cc_txn_ids))).delete(synchronize_session=False)
            db.session.commit()
            summary['deleted_cc_txns'] = len(cc_txn_ids)

        # Delete bank transactions
        if bank_txn_ids:
            Transaction.query.filter(Transaction.id.in_(list(bank_txn_ids))).delete(synchronize_session=False)
            db.session.commit()
            summary['deleted_bank_txns'] = len(bank_txn_ids)

        # Clear expense links
        for exp in linked_expenses:
            changed = False
            if exp.bank_transaction_id:
                exp.bank_transaction_id = None
                changed = True
            if exp.credit_card_transaction_id:
                exp.credit_card_transaction_id = None
                changed = True
            if changed:
                db.session.add(exp)
        db.session.commit()

        # Recalculate balances
        for account_id in accounts_to_recalc:
            if account_id:
                Transaction.recalculate_account_balance(account_id)

        for card_id in cards_to_recalc:
            if card_id:
                CreditCardTransaction.recalculate_card_balance(card_id)

        return summary

    @staticmethod
    def _ensure_credit_card_txn(exp: Expense):
        # Look for an existing credit card txn matching date, card and amount (purchase = negative)
        cc = CreditCard.query.get(exp.credit_card_id)
        if not cc:
            return

        target_amount = -abs(float(exp.total_cost))

        existing = CreditCardTransaction.query.filter_by(
            credit_card_id=cc.id,
            date=exp.date,
            amount=target_amount
        ).first()

        if existing:
            # Update details if changed
            updated = False
            if existing.item != exp.description:
                existing.item = exp.description
                updated = True
            if existing.transaction_type != 'Purchase':
                existing.transaction_type = 'Purchase'
                updated = True
            if updated:
                existing.updated_at = datetime.utcnow()
                db.session.add(existing)
            # record link back to expense
            if getattr(exp, 'credit_card_transaction_id', None) != existing.id:
                exp.credit_card_transaction_id = existing.id
                db.session.add(exp)
        else:
            # Create new credit card purchase transaction
            cc_txn = CreditCardTransaction(
                credit_card_id=cc.id,
                category_id=None,
                date=exp.date,
                day_name=exp.day_name,
                week=exp.week,
                month=exp.month,
                head_budget=None,
                sub_budget=None,
                item=exp.description,
                transaction_type='Purchase',
                amount=Decimal(str(target_amount)),
                is_paid=False,
            )
            db.session.add(cc_txn)
            # flush to obtain id and record link on expense
            db.session.flush()
            if getattr(exp, 'credit_card_transaction_id', None) != cc_txn.id:
                exp.credit_card_transaction_id = cc_txn.id
                db.session.add(exp)

    @staticmethod
    def _ensure_bank_reimbursement(exp: Expense):
        # Determine reimburse account from settings or fallback to first account
        acct_id = Settings.get_value('expenses.reimburse_account_id')
        account = None
        if acct_id:
            account = Account.query.get(int(acct_id))
        if not account:
            account = Account.query.order_by(Account.name).first()
        if not account:
            return

        # Find category for reimbursement (Income > Expense Reimbursement) if exists
        reimburse_cat = Category.query.filter_by(head_budget='Income', sub_budget='Expense Reimbursement').first()
        # Fallbacks: Income > Expenses, or any Income category, or first category available
        if not reimburse_cat:
            reimburse_cat = Category.query.filter_by(head_budget='Income', sub_budget='Expenses').first()
        if not reimburse_cat:
            reimburse_cat = Category.query.filter_by(head_budget='Income').first()
        if not reimburse_cat:
            reimburse_cat = Category.query.first()

        # Look for existing matching bank transaction
        existing = Transaction.query.filter_by(
            account_id=account.id,
            transaction_date=exp.date,
            amount=float(exp.total_cost),
            description=exp.description
        ).first()

        if existing:
            # Update category/flags if needed
            updated = False
            if reimburse_cat and existing.category_id != reimburse_cat.id:
                existing.category_id = reimburse_cat.id
                updated = True
            if updated:
                existing.updated_at = datetime.utcnow()
                db.session.add(existing)
            # record link back to expense
            if getattr(exp, 'bank_transaction_id', None) != existing.id:
                exp.bank_transaction_id = existing.id
                db.session.add(exp)
        else:
            # Create bank transaction representing the reimbursement payment
            txn = Transaction(
                account_id=account.id,
                category_id=reimburse_cat.id if reimburse_cat else None,
                vendor_id=None,
                amount=Decimal(str(exp.total_cost)),
                transaction_date=exp.date,
                description=exp.description,
                item=exp.description,
                assigned_to=None,
                payment_type='Reimbursement',
                is_paid=True,
                year_month=exp.month,
                week_year=exp.week,
                day_name=exp.day_name,
                payday_period=exp.month
            )
            db.session.add(txn)
            db.session.flush()
            # record link back to expense
            if getattr(exp, 'bank_transaction_id', None) != txn.id:
                exp.bank_transaction_id = txn.id
                db.session.add(exp)
            Transaction.recalculate_account_balance(account.id)
