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
    
    # Link to paired transfer transaction (for account-to-account transfers)
    linked_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    
    # Computed fields for reporting
    year_month = db.Column(db.String(7))  # 2026-01
    week_year = db.Column(db.String(7))   # 03-2026
    day_name = db.Column(db.String(10))   # Thu, Fri, etc.
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    vendor = db.relationship('Vendor', back_populates='transactions')
    
    def __repr__(self):
        return f'<Transaction {self.transaction_date}: {self.description} - £{self.amount}>'
    
    @staticmethod
    def recalculate_account_balance(account_id):
        """Recalculate and update account balance from all transactions"""
        from models.accounts import Account
        
        account = Account.query.get(account_id)
        if not account:
            return
        
        transactions = Transaction.query.filter_by(account_id=account_id).all()
        # Balance = sum of -amount (negative amounts are income, positive are expenses)
        balance = float(sum([-t.amount for t in transactions]))
        account.balance = balance
        account.updated_at = datetime.now()
