from extensions import db
from datetime import datetime


class Pension(db.Model):
    __tablename__ = 'pensions'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    person = db.Column(db.String(50), nullable=False, default='Keiron')  # 'Keiron', 'Emma'
    provider = db.Column(db.String(100), nullable=False)  # Peoples Pension, Aviva, Aegon, etc.
    account_number = db.Column(db.String(50))
    current_value = db.Column(db.Numeric(10, 2), nullable=False)
    contribution_rate = db.Column(db.Numeric(5, 2))  # Employee %
    employer_contribution = db.Column(db.Numeric(5, 2))  # Employer %
    is_active = db.Column(db.Boolean, default=True)
    
    # Retirement planning fields
    retirement_age = db.Column(db.Integer, default=65)  # Target retirement age
    monthly_contribution = db.Column(db.Numeric(10, 2), default=0)  # Expected monthly contribution
    projected_value_at_retirement = db.Column(db.Numeric(10, 2))  # Calculated projection
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    snapshots = db.relationship('PensionSnapshot', backref='pension', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Pension {self.provider}: £{self.current_value}>'
