from extensions import db
from datetime import datetime


class ChildcareRecord(db.Model):
    __tablename__ = 'childcare_records'
    
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    day_name = db.Column(db.String(10))  # Monday, Tuesday, etc.
    year_month = db.Column(db.String(7))  # 2025-05
    
    # Individual child costs
    child_name = db.Column(db.String(100), nullable=False)  # Michael, Emily, Ivy, Brian
    service_type = db.Column(db.String(100))  # AM, PM1, PM2, Lunch, Breakfast Club, School Dinner
    cost = db.Column(db.Numeric(10, 2), nullable=False)
    year_group = db.Column(db.String(50))  # Year 4, Nursery, etc.
    
    provider = db.Column(db.String(100))
    description = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<ChildcareRecord {self.date}: {self.child_name} - £{self.cost}>'
