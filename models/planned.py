from extensions import db
from datetime import datetime


class PlannedTransaction(db.Model):
    __tablename__ = 'planned_transactions'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    category_id= db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    planned_date = db.Column(db.Date, nullable=False)
    description = db.Column(db.String(255))
    is_recurring = db.Column(db.Boolean, default=False)
    frequency = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<PlannedTransaction {self.id}: {self.amount}>'
