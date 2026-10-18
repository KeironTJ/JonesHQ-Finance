from extensions import db
from datetime import datetime, timezone


class RecurringIncome(db.Model):
    """Template for recurring income - generates Income records automatically"""
    __tablename__ = 'recurring_income'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    person = db.Column(db.String(50), nullable=False, default='Household')
    # Household member this income belongs to (NULL = household / non-member label).
    # `person` stays as the display name and follows the member's name on rename.
    member_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    
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

    # NULL = shared/joint, visible to the whole family. Set = private, visible only to that user.
    # Inherited by Income records generated from this template.
    owner_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    # Metadata
    source = db.Column(db.String(100))  # Employer name
    description = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=True)

    # Income source settings (see services/finance/payroll_calculator.py for options)
    income_type = db.Column(db.String(30), nullable=False, default='employment', server_default='employment')
    pay_frequency = db.Column(db.String(20), nullable=False, default='monthly', server_default='monthly')
    # Anchor for weekly / fortnightly / four-weekly / annual schedules (monthly uses pay_day).
    first_pay_date = db.Column(db.Date, nullable=True)
    pension_scheme = db.Column(db.String(20), nullable=False, default='salary_sacrifice', server_default='salary_sacrifice')
    student_loan_plans = db.Column(db.String(60), nullable=True)  # CSV of plan keys
    set_aside_percent = db.Column(db.Numeric(5, 2), nullable=True)  # rental / self-employed
    # Automatic yearly rise: annual_increase_percent applied every year from
    # annual_increase_start (inclusive) on the same day and month.
    annual_increase_percent = db.Column(db.Numeric(6, 3), nullable=True)
    annual_increase_start = db.Column(db.Date, nullable=True)
    # Pension pot that receives this job's contributions (retirement planning).
    pension_id = db.Column(db.Integer, db.ForeignKey('pensions.id', ondelete='SET NULL'), nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    owner = db.relationship('User', foreign_keys=[owner_id])
    member = db.relationship('User', foreign_keys=[member_id])
    pension = db.relationship('Pension', foreign_keys=[pension_id])

    @property
    def student_loan_plan_list(self):
        return [p for p in (self.student_loan_plans or '').split(',') if p]

    @property
    def is_private(self):
        """True if this recurring income template is restricted to a single family member."""
        return self.owner_id is not None
    
    # Relationships
    deposit_account = db.relationship('Account', foreign_keys=[deposit_account_id])
    category = db.relationship('Category', foreign_keys=[category_id])
    
    def __repr__(self):
        return f'<RecurringIncome {self.person} {self.source}: £{self.gross_annual_income}/year>'
