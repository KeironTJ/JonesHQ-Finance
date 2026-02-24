from extensions import db
from datetime import datetime, timezone


class Property(db.Model):
    """Represents a property (can have multiple mortgage products over time)"""
    __tablename__ = 'properties'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    address= db.Column(db.String(255), nullable=False)
    purchase_date = db.Column(db.Date)
    purchase_price = db.Column(db.Numeric(10, 2))
    current_valuation = db.Column(db.Numeric(10, 2))
    
    # Valuation growth assumptions
    annual_appreciation_rate = db.Column(db.Numeric(5, 2), default=3.0)  # 3% default
    
    is_primary_residence = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Relationships
    mortgage_products = db.relationship('MortgageProduct', backref='property', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Property {self.address}>'
    
    @property
    def current_equity(self):
        """Calculate current equity (valuation - total mortgage balance)"""
        if not self.current_valuation:
            return 0
        
        total_mortgage = sum([mp.current_balance or 0 for mp in self.mortgage_products if mp.is_active])
        return self.current_valuation - total_mortgage
    
    @property
    def equity_percent(self):
        """Calculate equity percentage"""
        if not self.current_valuation or self.current_valuation == 0:
            return 0
        return (self.current_equity / self.current_valuation) * 100
