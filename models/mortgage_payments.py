from extensions import db
from datetime import datetime


class MortgagePayment(db.Model):
    __tablename__ = 'mortgage_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    mortgage_id = db.Column(db.Integer, db.ForeignKey('mortgages.id'), nullable=False)
    
    date = db.Column(db.Date, nullable=False)
    year_month = db.Column(db.String(7))  # 2024-01
    
    mortgage_balance = db.Column(db.Numeric(10, 2), nullable=False)
    fixed_payment = db.Column(db.Numeric(10, 2), nullable=False)
    optional_payment = db.Column(db.Numeric(10, 2), default=0.00)
    interest_charge = db.Column(db.Numeric(10, 2), nullable=False)
    interest_rate_percent = db.Column(db.Numeric(5, 2))
    equity_paid = db.Column(db.Numeric(10, 2), nullable=False)
    
    property_valuation = db.Column(db.Numeric(10, 2))
    equity_amount = db.Column(db.Numeric(10, 2))
    equity_percent = db.Column(db.Numeric(5, 2))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<MortgagePayment {self.date}: £{self.fixed_payment}>'
