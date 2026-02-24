from extensions import db
from datetime import datetime, timezone


class MortgageSnapshot(db.Model):
    """Monthly mortgage balance snapshot (actual or projected)"""
    __tablename__ = 'mortgage_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    mortgage_product_id= db.Column(db.Integer, db.ForeignKey('mortgage_products.id'), nullable=False)
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'))  # Linked payment transaction
    
    date = db.Column(db.Date, nullable=False)
    year_month = db.Column(db.String(7))  # 2024-01 for easy querying
    
    # Balance and payments
    balance = db.Column(db.Numeric(10, 2), nullable=False)  # Outstanding mortgage balance
    monthly_payment = db.Column(db.Numeric(10, 2), nullable=False)  # Regular payment
    overpayment = db.Column(db.Numeric(10, 2), default=0)  # Extra payment this month
    
    # Interest calculations
    interest_charge = db.Column(db.Numeric(10, 2), nullable=False)  # Interest charged this month
    principal_paid = db.Column(db.Numeric(10, 2), nullable=False)  # Amount that reduced principal
    interest_rate = db.Column(db.Numeric(5, 4))  # Monthly rate used
    
    # Property valuation and equity
    property_valuation = db.Column(db.Numeric(10, 2))  # Property value this month
    equity_amount = db.Column(db.Numeric(10, 2))  # valuation - balance
    equity_percent = db.Column(db.Numeric(5, 2))  # (equity / valuation) * 100
    
    # Projection flags
    is_projection = db.Column(db.Boolean, default=False)  # True if future projection
    scenario_name = db.Column(db.String(50), default='base')  # 'base', 'aggressive', 'conservative'
    
    notes = db.Column(db.Text)  # Any notes about this snapshot
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Relationships
    transaction = db.relationship('Transaction', backref='mortgage_snapshot', lazy=True, foreign_keys=[transaction_id])
    
    @property
    def is_paid(self):
        """Check if this snapshot has a linked transaction that is marked as paid"""
        if self.transaction_id is None:
            return False
        # Check if the linked transaction is actually paid
        if self.transaction and hasattr(self.transaction, 'is_paid'):
            return self.transaction.is_paid
        return True  # Fallback if transaction relationship not loaded
    
    def __repr__(self):
        proj_flag = ' (Projected)' if self.is_projection else ''
        return f'<MortgageSnapshot {self.date}: £{self.balance}{proj_flag}>'


# Keep old model for backward compatibility
class MortgagePayment(db.Model):
    __tablename__ = 'mortgage_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    mortgage_id = db.Column(db.Integer, db.ForeignKey('mortgages.id'), nullable=False)
    
    date = db.Column(db.Date, nullable=False)
    year_month = db.Column(db.String(7))
    
    mortgage_balance = db.Column(db.Numeric(10, 2), nullable=False)
    fixed_payment = db.Column(db.Numeric(10, 2), nullable=False)
    optional_payment = db.Column(db.Numeric(10, 2), default=0.00)
    interest_charge = db.Column(db.Numeric(10, 2), nullable=False)
    interest_rate_percent = db.Column(db.Numeric(5, 2))
    equity_paid = db.Column(db.Numeric(10, 2), nullable=False)
    
    property_valuation = db.Column(db.Numeric(10, 2))
    equity_amount = db.Column(db.Numeric(10, 2))
    equity_percent = db.Column(db.Numeric(5, 2))
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    def __repr__(self):
        return f'<MortgagePayment {self.date}: £{self.fixed_payment}>'
