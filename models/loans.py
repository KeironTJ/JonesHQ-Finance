from extensions import db
from datetime import datetime


class Loan(db.Model):
    __tablename__ = 'loans'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # EE, JN Bank, Loft Loan, etc.
    loan_value = db.Column(db.Numeric(10, 2), nullable=False)  # Original loan amount
    principal = db.Column(db.Numeric(10, 2), nullable=False)   # Original principal (same as loan_value)
    current_balance = db.Column(db.Numeric(10, 2), nullable=False)
    annual_apr = db.Column(db.Numeric(5, 2), nullable=False)
    monthly_apr = db.Column(db.Numeric(5, 2), nullable=False)
    monthly_payment = db.Column(db.Numeric(10, 2), nullable=False)
    calculated_payment = db.Column(db.Numeric(10, 2))  # Calculated vs actual
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date)
    term_months = db.Column(db.Integer, nullable=False)
    
    # Default Payment Account
    default_payment_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    payments = db.relationship('LoanPayment', backref='loan', lazy=True)
    transactions = db.relationship('Transaction', backref='loan', lazy=True)
    default_payment_account = db.relationship('Account', foreign_keys=[default_payment_account_id])
    
    def __repr__(self):
        return f'<Loan {self.name}: £{self.current_balance}>'
