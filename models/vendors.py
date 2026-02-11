from extensions import db
from datetime import datetime


class VendorType(db.Model):
    """Vendor type lookup table"""
    __tablename__ = 'vendor_types'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    sort_order = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    vendors = db.relationship('Vendor', back_populates='vendor_type_rel')

    def __repr__(self):
        return f'<VendorType {self.name}>'


class Vendor(db.Model):
    """
    Vendor/Merchant tracking table
    Stores information about places where money is spent or received from
    """
    __tablename__ = 'vendors'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False, index=True)
    vendor_type_id = db.Column(db.Integer, db.ForeignKey('vendor_types.id'), nullable=True)
    vendor_type = db.Column(db.String(50))  # Deprecated: kept for backward compatibility
    default_category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))
    website = db.Column(db.String(200))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    default_category = db.relationship('Category', backref='vendors')
    vendor_type_rel = db.relationship('VendorType', back_populates='vendors')
    transactions = db.relationship('Transaction', back_populates='vendor', lazy='dynamic')
    
    def __repr__(self):
        return f'<Vendor {self.name}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'vendor_type': self.vendor_type_rel.name if self.vendor_type_rel else self.vendor_type,
            'default_category_id': self.default_category_id,
            'website': self.website,
            'notes': self.notes,
            'is_active': self.is_active,
            'transaction_count': self.transactions.count()
        }
