from extensions import db
from datetime import datetime


class MortgageProduct(db.Model):
    """Represents a mortgage product (e.g., 2YR Fixed, 3YR Fixed, Variable)"""
    __tablename__ = 'mortgage_products'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    property_id= db.Column(db.Integer, db.ForeignKey('properties.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'))  # Bank account for payments
    vendor_id = db.Column(db.Integer, db.ForeignKey('vendors.id'))  # Lender as vendor
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'))  # Transaction category
    
    # Product details
    lender = db.Column(db.String(100), nullable=False)  # e.g., "The Mortgage Lender", "Nationwide"
    product_name = db.Column(db.String(100), nullable=False)  # e.g., "2YR FIXED 70%", "Variable"
    
    # Dates
    start_date = db.Column(db.Date, nullable=False)  # When this product starts
    end_date = db.Column(db.Date, nullable=False)  # When this product ends
    term_months = db.Column(db.Integer, nullable=False)  # Term of THIS product in months
    
    # Financial details
    initial_balance = db.Column(db.Numeric(10, 2), nullable=False)  # Balance at start of this product
    current_balance = db.Column(db.Numeric(10, 2), nullable=False)  # Current balance
    annual_rate = db.Column(db.Numeric(5, 2), nullable=False)  # Annual interest rate %
    monthly_payment = db.Column(db.Numeric(10, 2), nullable=False)  # Fixed monthly payment
    payment_day = db.Column(db.Integer, default=1)  # Day of month payment is due (1-31)
    
    # Status
    is_active = db.Column(db.Boolean, default=True)  # Currently the active product for this property
    is_current = db.Column(db.Boolean, default=False)  # Is this the current time period (vs future plan)
    
    # LTV information
    ltv_ratio = db.Column(db.Numeric(5, 2))  # Loan to value ratio at start
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    snapshots = db.relationship('MortgageSnapshot', backref='mortgage_product', lazy=True, cascade='all, delete-orphan')
    account = db.relationship('Account', backref='mortgage_products', lazy=True)
    vendor = db.relationship('Vendor', backref='mortgage_products', lazy=True)
    category = db.relationship('Category', backref='mortgage_products', lazy=True)
    
    def __repr__(self):
        return f'<MortgageProduct {self.lender} {self.product_name}: £{self.current_balance}>'
    
    @property
    def monthly_rate(self):
        """Calculate monthly interest rate"""
        return self.annual_rate / 12 / 100


# Keep old Mortgage model for backward compatibility temporarily
class Mortgage(db.Model):
    __tablename__ = 'mortgages'
    
    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    property_address = db.Column(db.String(255), nullable=False)
    principal = db.Column(db.Numeric(10, 2), nullable=False)
    current_balance = db.Column(db.Numeric(10, 2), nullable=False)
    interest_rate = db.Column(db.Numeric(5, 2), nullable=False)
    fixed_payment = db.Column(db.Numeric(10, 2), nullable=False)
    optional_payment = db.Column(db.Numeric(10, 2))
    start_date = db.Column(db.Date, nullable=False)
    term_years = db.Column(db.Integer, nullable=False)
    property_valuation = db.Column(db.Numeric(10, 2))
    equity_amount = db.Column(db.Numeric(10, 2))
    equity_percent = db.Column(db.Numeric(5, 2))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    payments = db.relationship('MortgagePayment', backref='mortgage', lazy=True)
    
    def __repr__(self):
        return f'<Mortgage {self.property_address}: £{self.current_balance}>'
