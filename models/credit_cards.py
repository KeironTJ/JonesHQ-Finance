from extensions import db
from datetime import datetime


class CreditCard(db.Model):
    __tablename__ = 'credit_cards'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    card_name= db.Column(db.String(100), nullable=False)  # Barclaycard, M&S, Natwest, etc.
    
    # APR and Interest
    annual_apr = db.Column(db.Numeric(5, 2), nullable=False)
    monthly_apr = db.Column(db.Numeric(5, 2), nullable=False)
    
    # Promotional 0% Offers
    purchase_0_percent_until = db.Column(db.Date)  # 0% on purchases until this date
    balance_transfer_0_percent_until = db.Column(db.Date)  # 0% on balance transfers until this date
    
    # Payment Settings
    min_payment_percent = db.Column(db.Numeric(5, 2))  # Minimum payment %
    set_payment = db.Column(db.Numeric(10, 2))  # Regular payment amount
    statement_date = db.Column(db.Integer)  # Day of month (1-31)
    
    # Limits and Balances
    credit_limit = db.Column(db.Numeric(10, 2), nullable=False)
    current_balance = db.Column(db.Numeric(10, 2), default=0.00)
    available_credit = db.Column(db.Numeric(10, 2))
    
    # Default Payment Account
    default_payment_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    
    # Account Management
    start_date = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    transactions = db.relationship('CreditCardTransaction', backref='credit_card', lazy=True, cascade='all, delete-orphan')
    promotional_offers = db.relationship('CreditCardPromotion', backref='credit_card', lazy=True, cascade='all, delete-orphan')
    default_payment_account = db.relationship('Account', foreign_keys=[default_payment_account_id])
    
    def get_current_purchase_apr(self, date=None):
        """Get APR for purchases on a specific date (considers 0% offers)"""
        check_date = date or datetime.now().date()
        if self.purchase_0_percent_until and check_date <= self.purchase_0_percent_until:
            return 0.0
        return float(self.monthly_apr)
    
    def get_current_balance_transfer_apr(self, date=None):
        """Get APR for balance transfers on a specific date (considers 0% offers)"""
        check_date = date or datetime.now().date()
        if self.balance_transfer_0_percent_until and check_date <= self.balance_transfer_0_percent_until:
            return 0.0
        return float(self.monthly_apr)
    
    def calculate_minimum_payment(self):
        """Calculate minimum payment based on balance and min_payment_percent (negative = owe)"""
        if not self.current_balance or self.current_balance >= 0:
            return 0.0
        # Use absolute value since negative balance means we owe money
        min_payment = abs(float(self.current_balance)) * (float(self.min_payment_percent) / 100)
        return round(min_payment, 2)
    
    def calculate_actual_payment(self):
        """Calculate actual payment: MIN(set_payment, abs(current_balance)) - negative balance = owe money"""
        if not self.current_balance or self.current_balance >= 0:
            return 0.0
        if not self.set_payment:
            return self.calculate_minimum_payment()
        # Use absolute value since negative balance means we owe money
        return round(min(float(self.set_payment), abs(float(self.current_balance))), 2)
    
    def __repr__(self):
        return f'<CreditCard {self.card_name}: £{self.current_balance}>'


class CreditCardPromotion(db.Model):
    """Track promotional offers on credit cards (historical record)"""
    __tablename__ = 'credit_card_promotions'
    
    id = db.Column(db.Integer, primary_key=True)
    credit_card_id = db.Column(db.Integer, db.ForeignKey('credit_cards.id'), nullable=False)
    
    promotion_type = db.Column(db.String(50), nullable=False)  # 'purchase', 'balance_transfer'
    apr_rate = db.Column(db.Numeric(5, 2), nullable=False)  # Usually 0.00
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<CreditCardPromotion {self.promotion_type}: {self.apr_rate}% until {self.end_date}>'
