from extensions import db
from datetime import datetime


class MonthlyAccountBalance(db.Model):
    """Cache table for monthly account balances (actual and projected)"""
    __tablename__ = 'monthly_account_balances'
    
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    year_month = db.Column(db.String(7), nullable=False)  # Format: YYYY-MM
    
    # Actual balance (only paid transactions)
    actual_balance = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    
    # Projected balance (paid + unpaid + forecasted transactions)
    projected_balance = db.Column(db.Numeric(10, 2), nullable=False, default=0.00)
    
    # Metadata
    last_calculated = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    account = db.relationship('Account', backref='monthly_balances')
    
    # Composite index for fast lookups
    __table_args__ = (
        db.Index('idx_account_yearmonth', 'account_id', 'year_month'),
        db.UniqueConstraint('account_id', 'year_month', name='unique_account_month'),
    )
    
    def __repr__(self):
        return f'<MonthlyAccountBalance {self.account_id} {self.year_month}: Actual={self.actual_balance}, Projected={self.projected_balance}>'
