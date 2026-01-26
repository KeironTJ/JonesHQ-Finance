from extensions import db
from datetime import datetime


class Income(db.Model):
    __tablename__ = 'income'
    
    id = db.Column(db.Integer, primary_key=True)
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
    
    source = db.Column(db.String(100))  # Employer name
    description = db.Column(db.String(255))
    is_recurring = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<Income {self.pay_date}: £{self.take_home}>'
