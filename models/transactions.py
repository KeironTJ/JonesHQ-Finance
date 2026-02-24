from decimal import Decimal
from datetime import datetime, timezone
from extensions import db


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    account_id= db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'), nullable=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(255))
    item = db.Column(db.String(255))  # Specific item/details (e.g., "Weekly shop" when vendor=Tesco)
    assigned_to = db.Column(db.String(100))  # Keiron, Emma, etc.
    payment_type = db.Column(db.String(50))  # BACS, Direct Debit, Card Payment, Transfer
    running_balance = db.Column(db.Numeric(10, 2))  # Balance after transaction
    is_paid = db.Column(db.Boolean, default=False)
    is_fixed = db.Column(db.Boolean, default=False)  # Is this transaction locked from regeneration?
    
    # Optional reference to credit card or loan
    credit_card_id = db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=True)
    
    # Link to income record if this is an income transaction
    income_id = db.Column(db.Integer, db.ForeignKey('income.id'), nullable=True)
    
    # Link to paired transfer transaction (for account-to-account transfers)
    linked_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    
    # Computed fields for reporting
    year_month = db.Column(db.String(7))  # 2026-01
    week_year = db.Column(db.String(7))   # 03-2026
    day_name = db.Column(db.String(10))   # Thu, Fri, etc.
    payday_period = db.Column(db.String(7))  # 2026-01 (payday period this transaction falls in)
    
    is_forecasted = db.Column(db.Boolean, default=False)  # True for predicted/forecasted transactions
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Relationships
    vendor = db.relationship('Vendor', back_populates='transactions')
    income = db.relationship('Income', foreign_keys=[income_id], backref='linked_transaction', uselist=False)
    
    def __repr__(self):
        return f'<Transaction {self.transaction_date}: {self.description} - £{self.amount}>'
    
    @staticmethod
    def recalculate_account_balance(account_id):
        """Recalculate and update account balance from all transactions.

        Scopes to the current family when called within a request context;
        falls back to unscoped for CLI commands and tests.
        """
        from models.accounts import Account

        account = db.session.get(Account, account_id)
        if not account:
            return

        q = Transaction.query.filter(Transaction.account_id == account_id)
        try:
            from utils.db_helpers import get_family_id
            fid = get_family_id()
            if fid is not None:
                q = q.filter(Transaction.family_id == fid)
        except RuntimeError:
            pass  # Outside request context (CLI, tests) — run unscoped

        balance = sum((Decimal(str(t.amount)) for t in q.all()), Decimal('0'))
        account.balance = balance
        account.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
