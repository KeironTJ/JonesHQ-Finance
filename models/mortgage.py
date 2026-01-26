from extensions import db
from datetime import datetime


class Mortgage(db.Model):
    __tablename__ = 'mortgages'
    
    id = db.Column(db.Integer, primary_key=True)
    property_address = db.Column(db.String(255), nullable=False)
    principal = db.Column(db.Numeric(10, 2), nullable=False)  # Original amount
    current_balance = db.Column(db.Numeric(10, 2), nullable=False)
    interest_rate = db.Column(db.Numeric(5, 2), nullable=False)  # Annual %
    fixed_payment = db.Column(db.Numeric(10, 2), nullable=False)
    optional_payment = db.Column(db.Numeric(10, 2))  # Extra payments
    start_date = db.Column(db.Date, nullable=False)
    term_years = db.Column(db.Integer, nullable=False)
    property_valuation = db.Column(db.Numeric(10, 2))  # Current property value
    equity_amount = db.Column(db.Numeric(10, 2))  # Calculated equity
    equity_percent = db.Column(db.Numeric(5, 2))  # Equity %
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    payments = db.relationship('MortgagePayment', backref='mortgage', lazy=True)
    
    def __repr__(self):
        return f'<Mortgage {self.property_address}: £{self.current_balance}>'
