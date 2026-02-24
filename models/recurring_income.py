from extensions import db
from datetime import datetime, timezone


class RecurringIncome(db.Model):
    """Template for recurring income - generates Income records automatically"""
    __tablename__ = 'recurring_income'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    person = db.Column(db.String(50), nullable=False, default='Keiron')
    
    # Schedule
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)  # None = ongoing
    pay_day = db.Column(db.Integer, nullable=False)  # Day of month (1-31, or 0 for last day)
    last_generated_date = db.Column(db.Date, nullable=True)  # Track what's been generated
    
    # Income details
    gross_annual_income = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Pension contributions
    employer_pension_percent = db.Column(db.Numeric(5, 2), default=0)
    employee_pension_percent = db.Column(db.Numeric(5, 2), default=0)
    
    # Deductions
    tax_code = db.Column(db.String(10), nullable=False)
    avc = db.Column(db.Numeric(10, 2), default=0)
    other_deductions = db.Column(db.Numeric(10, 2), default=0)
    
    # Manual override for actual payslip values
    use_manual_deductions = db.Column(db.Boolean, default=False)
    manual_tax_monthly = db.Column(db.Numeric(10, 2), nullable=True)
    manual_ni_monthly = db.Column(db.Numeric(10, 2), nullable=True)
    manual_employer_pension = db.Column(db.Numeric(10, 2), nullable=True)
    manual_employee_pension = db.Column(db.Numeric(10, 2), nullable=True)
    manual_take_home = db.Column(db.Numeric(10, 2), nullable=True)
    
    # Account & transaction settings
    deposit_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('categories.id'), nullable=True)
    auto_create_transaction = db.Column(db.Boolean, default=True)
    
    # Metadata
    source = db.Column(db.String(100))  # Employer name
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    
    # Relationships
    deposit_account = db.relationship('Account', foreign_keys=[deposit_account_id])
    category = db.relationship('Category', foreign_keys=[category_id])
    
    def __repr__(self):
        return f'<RecurringIncome {self.person} {self.source}: £{self.gross_annual_income}/year>'
