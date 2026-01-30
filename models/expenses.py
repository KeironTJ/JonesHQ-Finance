from extensions import db
from datetime import datetime


class Expense(db.Model):
    __tablename__ = 'expenses'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    month = db.Column(db.String(7))  # 2025-04
    week = db.Column(db.String(7))  # 14-2025
    day_name = db.Column(db.String(10))
    finance_year = db.Column(db.String(9))  # 2025-2026
    
    description = db.Column(db.String(255), nullable=False)  # Tetrad, Garner Hotel, etc.
    expense_type = db.Column(db.String(50), nullable=False)  # Fuel, Hotel, Food
    credit_card_id = db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=True)
    # Linked transaction ids created by sync service
    credit_card_transaction_id = db.Column(db.Integer, db.ForeignKey('credit_card_transactions.id'), nullable=True)
    bank_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    
    # Mileage specific
    covered_miles = db.Column(db.Integer)
    rate_per_mile = db.Column(db.Numeric(5, 2))  # £0.45
    days = db.Column(db.Integer, default=1)
    cumulative_miles_ytd = db.Column(db.Integer)
    vehicle_registration = db.Column(db.String(20))
    
    # Cost
    cost = db.Column(db.Numeric(10, 2), nullable=False)
    total_cost = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Status
    paid_for = db.Column(db.Boolean, default=False)
    submitted = db.Column(db.Boolean, default=False)
    reimbursed = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Expense {self.date}: {self.description} - £{self.total_cost}>'
