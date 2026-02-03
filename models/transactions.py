from extensions import db
from datetime import datetime


class Transaction(db.Model):
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
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
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    vendor = db.relationship('Vendor', back_populates='transactions')
    income = db.relationship('Income', foreign_keys=[income_id], backref='linked_transaction', uselist=False)
    
    def __repr__(self):
        return f'<Transaction {self.transaction_date}: {self.description} - £{self.amount}>'
    
    @staticmethod
    def recalculate_account_balance(account_id):
        """Recalculate and update account balance from all transactions"""
        from models.accounts import Account
        from decimal import Decimal
        
        account = Account.query.get(account_id)
        if not account:
            return
        
        transactions = Transaction.query.filter_by(account_id=account_id).all()
        # Balance = sum of amounts (positive=income adds, negative=expense subtracts)
        # Keep as Decimal throughout
        balance = sum([Decimal(str(t.amount)) for t in transactions], Decimal('0'))
        account.balance = balance
        account.updated_at = datetime.now()


# Event listeners to update monthly balance cache when transactions change
# DISABLED: Causes session state errors with after_commit events
# Cache updates are now handled manually in routes after transactions are committed
"""
from sqlalchemy import event

@event.listens_for(Transaction, 'after_insert')
def after_transaction_insert(mapper, connection, target):
    \"\"\"Update monthly balance cache when a transaction is added\"\"\"
    if target.account_id:
        # Use after_commit to ensure transaction is completed
        @event.listens_for(db.session, 'after_commit', once=True)
        def update_cache(session):
            from services.monthly_balance_service import MonthlyBalanceService
            MonthlyBalanceService.handle_transaction_change(
                target.account_id, 
                target.transaction_date
            )


@event.listens_for(Transaction, 'after_update')
def after_transaction_update(mapper, connection, target):
    \"\"\"Update monthly balance cache when a transaction is edited\"\"\"
    # Cache update will be handled by the route after commit
    # This avoids session state issues with after_commit events
    pass


@event.listens_for(Transaction, 'after_delete')
def after_transaction_delete(mapper, connection, target):
    \"\"\"Update monthly balance cache when a transaction is deleted\"\"\"
    if target.account_id:
        @event.listens_for(db.session, 'after_commit', once=True)
        def update_cache(session):
            from services.monthly_balance_service import MonthlyBalanceService
            MonthlyBalanceService.handle_transaction_change(
                target.account_id, 
                target.transaction_date
            )
"""
