from extensions import db
from datetime import datetime


class LoanPayment(db.Model):
    __tablename__ = 'loan_payments'
    
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)
    
    date = db.Column(db.Date, nullable=False)
    year_month = db.Column(db.String(7))  # 2026-01
    period = db.Column(db.Integer, nullable=False)  # Payment number
    
    opening_balance = db.Column(db.Numeric(10, 2), nullable=False)
    payment_amount = db.Column(db.Numeric(10, 2), nullable=False)
    interest_charge = db.Column(db.Numeric(10, 2), default=0.00)
    amount_paid_off = db.Column(db.Numeric(10, 2), nullable=False)  # Principal reduction
    closing_balance = db.Column(db.Numeric(10, 2), nullable=False)
    
    is_paid = db.Column(db.Boolean, default=False)
    bank_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    bank_transaction = db.relationship('Transaction', foreign_keys=[bank_transaction_id])
    
    def __repr__(self):
        return f'<LoanPayment {self.loan.name} Period {self.period}: £{self.payment_amount}>'
