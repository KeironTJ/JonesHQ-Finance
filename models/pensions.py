from extensions import db
from datetime import datetime


class Pension(db.Model):
    __tablename__ = 'pensions'
    
    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(100), nullable=False)  # Peoples Pension, Aviva, Aegon, etc.
    account_number = db.Column(db.String(50))
    current_value = db.Column(db.Numeric(10, 2), nullable=False)
    contribution_rate = db.Column(db.Numeric(5, 2))  # Employee %
    employer_contribution = db.Column(db.Numeric(5, 2))  # Employer %
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    snapshots = db.relationship('PensionSnapshot', backref='pension', lazy=True)
    
    def __repr__(self):
        return f'<Pension {self.provider}: £{self.current_value}>'
