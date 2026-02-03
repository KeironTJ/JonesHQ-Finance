from extensions import db
from datetime import datetime


class PensionSnapshot(db.Model):
    __tablename__ = 'pension_snapshots'
    
    id = db.Column(db.Integer, primary_key=True)
    pension_id = db.Column(db.Integer, db.ForeignKey('pensions.id'), nullable=False)
    
    review_date = db.Column(db.Date, nullable=False)
    value = db.Column(db.Numeric(10, 2), nullable=False)
    growth_percent = db.Column(db.Numeric(10, 4))  # % growth since last snapshot
    
    # Projection flags and scenario data
    is_projection = db.Column(db.Boolean, default=False)  # True if this is a future projection
    scenario_name = db.Column(db.String(50), default='default')  # 'default', 'optimistic', 'pessimistic', etc.
    growth_rate_used = db.Column(db.Numeric(10, 4))  # The monthly growth rate used for this projection
    
    # Additional tracking
    notes = db.Column(db.Text)  # Any notes about this snapshot/projection
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        proj_flag = ' (Projected)' if self.is_projection else ''
        return f'<PensionSnapshot {self.review_date}: £{self.value}{proj_flag}>'
