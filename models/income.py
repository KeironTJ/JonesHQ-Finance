from extensions import db
from datetime import datetime


class Income(db.Model):
    __tablename__ = 'income'
    
    id = db.Column(db.Integer, primary_key=True)
    person = db.Column(db.String(50), nullable=False, default='Keiron')  # 'Keiron', 'Emma'
    pay_date = db.Column(db.Date, nullable=False)
    tax_year = db.Column(db.String(9))  # 2022-2023
    
    # Income details
    gross_annual_income = db.Column(db.Numeric(10, 2), nullable=False)
    gross_monthly_income = db.Column(db.Numeric(10, 2), nullable=False)
    
    # Pension contributions
    employer_pension_percent = db.Column(db.Numeric(5, 2))
    employee_pension_percent = db.Column(db.Numeric(5, 2))
    employer_pension_amount = db.Column(db.Numeric(10, 2))
    employee_pension_amount = db.Column(db.Numeric(10, 2))
    total_pension = db.Column(db.Numeric(10, 2))
    
    # Adjusted income
    adjusted_monthly_income = db.Column(db.Numeric(10, 2))
    adjusted_annual_income = db.Column(db.Numeric(10, 2))
    
    # Deductions
    tax_code = db.Column(db.String(10))
    income_tax = db.Column(db.Numeric(10, 2))
    national_insurance = db.Column(db.Numeric(10, 2))
    avc = db.Column(db.Numeric(10, 2))  # Additional Voluntary Contributions
    other_deductions = db.Column(db.Numeric(10, 2))
    
    # Final amounts
    take_home = db.Column(db.Numeric(10, 2), nullable=False)
    estimated_annual_take_home = db.Column(db.Numeric(10, 2))
    
    # Link to account where income is deposited
    deposit_account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=True)
    
    # Link to auto-created transaction
    transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True)
    
    # Link to recurring income template that generated this record
    recurring_income_id = db.Column(db.Integer, db.ForeignKey('recurring_income.id'), nullable=True)
    
    source = db.Column(db.String(100))  # Employer name
    description = db.Column(db.String(255))
    is_recurring = db.Column(db.Boolean, default=True)
    
    # Manual override flag (if true, values were entered manually not calculated)
    is_manual_override = db.Column(db.Boolean, default=False)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    deposit_account = db.relationship('Account', foreign_keys=[deposit_account_id])
    transaction = db.relationship('Transaction', foreign_keys=[transaction_id], uselist=False)
    recurring_income = db.relationship('RecurringIncome', foreign_keys=[recurring_income_id], backref='generated_income')
    
    def __repr__(self):
        return f'<Income {self.person} {self.pay_date}: £{self.take_home}>'
    
    @property
    def year_month(self):
        """Return YYYY-MM format for grouping"""
        return f"{self.pay_date.year}-{self.pay_date.month:02d}"