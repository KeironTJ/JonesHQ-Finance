from extensions import db
from datetime import datetime


class CreditCard(db.Model):
    __tablename__ = 'credit_cards'
    
    id = db.Column(db.Integer, primary_key=True)
    card_name = db.Column(db.String(100), nullable=False)  # Barclaycard, M&S, Natwest, etc.
    annual_apr = db.Column(db.Numeric(5, 2), nullable=False)
    monthly_apr = db.Column(db.Numeric(5, 2), nullable=False)
    min_payment_percent = db.Column(db.Numeric(5, 2))  # Minimum payment %
    credit_limit = db.Column(db.Numeric(10, 2), nullable=False)
    set_payment = db.Column(db.Numeric(10, 2))  # Regular payment amount
    statement_date = db.Column(db.Integer)  # Day of month
    current_balance = db.Column(db.Numeric(10, 2), default=0.00)
    available_credit = db.Column(db.Numeric(10, 2))
    start_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    transactions = db.relationship('CreditCardTransaction', backref='credit_card', lazy=True)
    
    def __repr__(self):
        return f'<CreditCard {self.card_name}: £{self.current_balance}>'
