from extensions import db
from datetime import datetime, timezone


class Account(db.Model):
    __tablename__ = 'accounts'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    account_type = db.Column(db.String(50), nullable=False)  # Joint, Personal, Savings, etc.
    balance = db.Column(db.Numeric(10, 2), default=0.00)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Relationships
    transactions = db.relationship('Transaction', backref='account', lazy=True)
    balances = db.relationship('Balance', backref='account', lazy=True)
    
    @property
    def paid_balance(self):
        """Calculate balance from PAID transactions only"""
        from decimal import Decimal
        from models.transactions import Transaction
        
        paid_transactions = Transaction.query.filter_by(
            account_id=self.id,
            is_paid=True
        ).all()
        
        balance = sum([Decimal(str(t.amount)) for t in paid_transactions], Decimal('0'))
        return float(balance)
    
    def __repr__(self):
        return f'<Account {self.name}>'
