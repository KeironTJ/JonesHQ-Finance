from extensions import db
from datetime import datetime


class TaxSettings(db.Model):
    """UK Tax and National Insurance rate settings - can be updated annually"""
    __tablename__ = 'tax_settings'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    tax_year = db.Column(db.String(9), nullable=False)# e.g., "2024-2025"
    effective_from = db.Column(db.Date, nullable=False)  # Start date (typically April 6)
    effective_to = db.Column(db.Date, nullable=True)  # End date (typically April 5 next year)
    
    # Income Tax Thresholds and Rates
    personal_allowance = db.Column(db.Numeric(10, 2), nullable=False, default=12570)
    basic_rate_limit = db.Column(db.Numeric(10, 2), nullable=False, default=50270)
    higher_rate_limit = db.Column(db.Numeric(10, 2), nullable=False, default=125140)
    
    basic_rate = db.Column(db.Numeric(5, 4), nullable=False, default=0.20)  # 20%
    higher_rate = db.Column(db.Numeric(5, 4), nullable=False, default=0.40)  # 40%
    additional_rate = db.Column(db.Numeric(5, 4), nullable=False, default=0.45)  # 45%
    
    # National Insurance Thresholds and Rates (Employee Class 1)
    ni_threshold = db.Column(db.Numeric(10, 2), nullable=False, default=12570)
    ni_upper_earnings = db.Column(db.Numeric(10, 2), nullable=False, default=50270)
    ni_basic_rate = db.Column(db.Numeric(5, 4), nullable=False, default=0.12)  # 12%
    ni_additional_rate = db.Column(db.Numeric(5, 4), nullable=False, default=0.02)  # 2%
    
    is_active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text)  # For any special notes about this tax year
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<TaxSettings {self.tax_year}>'
    
    @staticmethod
    def get_for_date(target_date):
        """Get the tax settings applicable for a specific date"""
        return TaxSettings.query.filter(
            TaxSettings.effective_from <= target_date,
            db.or_(
                TaxSettings.effective_to.is_(None),
                TaxSettings.effective_to >= target_date
            ),
            TaxSettings.is_active == True
        ).first()
    
    @staticmethod
    def get_current():
        """Get the currently active tax settings"""
        from datetime import date
        return TaxSettings.get_for_date(date.today())
