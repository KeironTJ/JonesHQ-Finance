from extensions import db
from datetime import datetime


class Balance(db.Model):
    __tablename__ = 'balances'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    account_id= db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False)
    balance = db.Column(db.Numeric(10, 2), nullable=False)
    balance_date = db.Column(db.Date, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Balance {self.account_id}: {self.balance}>'
