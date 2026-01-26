from extensions import db
from datetime import datetime


class NetWorth(db.Model):
    __tablename__ = 'net_worth'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    year_month = db.Column(db.String(7))  # 2023-01
    is_active_month = db.Column(db.Boolean, default=True)
    
    # Assets breakdown
    cash = db.Column(db.Numeric(10, 2), default=0.00)
    savings = db.Column(db.Numeric(10, 2), default=0.00)
    house_value = db.Column(db.Numeric(10, 2), default=0.00)
    pensions_value = db.Column(db.Numeric(10, 2), default=0.00)
    total_assets = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Liabilities breakdown
    credit_cards = db.Column(db.Numeric(10, 2), default=0.00)
    loans = db.Column(db.Numeric(10, 2), default=0.00)
    mortgage = db.Column(db.Numeric(10, 2), default=0.00)
    total_liabilities = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Net worth and tracking
    net_worth = db.Column(db.Numeric(10, 2), nullable=False)
    one_month_track = db.Column(db.Numeric(10, 2))  # % change from previous month
    three_month_track = db.Column(db.Numeric(10, 2))  # % change from 3 months ago
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<NetWorth {self.date}: £{self.net_worth}>'
