from extensions import db
from datetime import datetime


class CreditCardTransaction(db.Model):
    __tablename__ = 'credit_card_transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    credit_card_id = db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    
    date = db.Column(db.Date, nullable=False)
    day_name = db.Column(db.String(10))
    week = db.Column(db.String(7))  # 51-2025
    month = db.Column(db.String(7))  # 2025-12
    
    head_budget = db.Column(db.String(100))  # Main category
    sub_budget = db.Column(db.String(100))   # Sub category
    item = db.Column(db.String(255))  # Merchant/description
    
    transaction_type = db.Column(db.String(50))  # Purchase, Payment, Interest, Rewards
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    is_paid = db.Column(db.Boolean, default=False)
    
    balance = db.Column(db.Numeric(10, 2))  # Balance after transaction
    credit_available = db.Column(db.Numeric(10, 2))
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<CreditCardTransaction {self.date}: {self.item} - £{self.amount}>'
