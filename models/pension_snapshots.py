from extensions import db
from datetime import datetime


class PensionSnapshot(db.Model):
    __tablename__ = 'pension_snapshots'
    
    id = db.Column(db.Integer, primary_key=True)
    pension_id = db.Column(db.Integer, db.ForeignKey('pensions.id'), nullable=False)
    
    review_date = db.Column(db.Date, nullable=False)
    value = db.Column(db.Numeric(10, 2), nullable=False)
    growth_percent = db.Column(db.Numeric(10, 2))  # % growth since last snapshot
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<PensionSnapshot {self.pension.provider} {self.review_date}: £{self.value}>'
