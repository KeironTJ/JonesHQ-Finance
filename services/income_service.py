"""
Income Service
Handles income record management, tax/NI calculations, and transaction creation
"""
from models.income import Income
from models.recurring_income import RecurringIncome
from models.accounts import Account
from models.transactions import Transaction
from models.categories import Category
from extensions import db
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from decimal import Decimal
import calendar


class IncomeService:
    
    # UK Tax Rates (2023-2024 onwards)
    PERSONAL_ALLOWANCE = 12570  # Tax-free allowance
    BASIC_RATE_LIMIT = 50270    # Up to this is 20%
    HIGHER_RATE_LIMIT = 125140  # Up to this is 40%
    # Above 125140 is 45%
    
    # National Insurance Rates (Employee Class 1)
    NI_THRESHOLD = 12570  # Annual threshold
    NI_UPPER_EARNINGS = 50270
    NI_BASIC_RATE = 0.12  # 12% between threshold and upper
    NI_ADDITIONAL_RATE = 0.02  # 2% above upper
    
    @staticmethod
    def calculate_tax_and_ni(gross_annual, tax_code='1257L', pension_amount=0):
        """
        Calculate income tax and National Insurance
        
        Args:
            gross_annual: Gross annual salary
            tax_code: UK tax code (e.g., '1257L')
            pension_amount: Annual pension contributions (pre-tax)
        
        Returns:
            dict with tax, ni, and net amounts
        """
        # Parse tax code to get personal allowance
        try:
            code_number = int(tax_code.rstrip('L'))
            personal_allowance = code_number * 10
        except:
            personal_allowance = IncomeService.PERSONAL_ALLOWANCE
        
        # Taxable income (after pension deductions)
        taxable_income = max(0, gross_annual - pension_amount)
        
        # Calculate tax
        tax = 0
        if taxable_income > personal_allowance:
            taxable = taxable_income - personal_allowance
            
            if taxable <= (IncomeService.BASIC_RATE_LIMIT - personal_allowance):
                # All in basic rate (20%)
                tax = taxable * 0.20
            elif taxable <= (IncomeService.HIGHER_RATE_LIMIT - personal_allowance):
                # Basic + Higher rate
                basic = (IncomeService.BASIC_RATE_LIMIT - personal_allowance)
                higher = taxable - basic
                tax = (basic * 0.20) + (higher * 0.40)
            else:
                # Basic + Higher + Additional
                basic = (IncomeService.BASIC_RATE_LIMIT - personal_allowance)
                higher = (IncomeService.HIGHER_RATE_LIMIT - IncomeService.BASIC_RATE_LIMIT)
                additional = taxable - basic - higher
                tax = (basic * 0.20) + (higher * 0.40) + (additional * 0.45)
        
        # Calculate National Insurance (on gross, before pension)
        ni = 0
        if gross_annual > IncomeService.NI_THRESHOLD:
            if gross_annual <= IncomeService.NI_UPPER_EARNINGS:
                # All in basic NI rate
                ni_able = gross_annual - IncomeService.NI_THRESHOLD
                ni = ni_able * IncomeService.NI_BASIC_RATE
            else:
                # Basic + Additional NI rate
                basic_ni = (IncomeService.NI_UPPER_EARNINGS - IncomeService.NI_THRESHOLD) * IncomeService.NI_BASIC_RATE
                additional_ni = (gross_annual - IncomeService.NI_UPPER_EARNINGS) * IncomeService.NI_ADDITIONAL_RATE
                ni = basic_ni + additional_ni
        
        return {
            'tax': round(tax, 2),
            'ni': round(ni, 2),
            'total_deductions': round(tax + ni + pension_amount, 2),
            'net_annual': round(gross_annual - tax - ni - pension_amount, 2)
        }
    
    @staticmethod
    def create_income_record(person, pay_date, gross_annual, employer_pension_pct=0,
                            employee_pension_pct=0, tax_code='1257L', avc=0, other=0,
                            deposit_account_id=None, source='', create_transaction=True):
        """
        Create an income record with calculated tax/NI
        
        Args:
            person: Person name ('Keiron', 'Emma')
            pay_date: Date of payment
            gross_annual: Gross annual salary
            employer_pension_pct: Employer pension %
            employee_pension_pct: Employee pension %
            tax_code: UK tax code
            avc: Additional voluntary contributions
            other: Other deductions
            deposit_account_id: Account to deposit income
            source: Employer name
            create_transaction: Whether to create linked transaction
        """
        gross_monthly = gross_annual / 12
        
        # Calculate pension amounts
        employer_pension = gross_monthly * (employer_pension_pct / 100)
        employee_pension = gross_monthly * (employee_pension_pct / 100)
        total_pension = employer_pension + employee_pension
        
        # Adjusted income (after employee pension)
        adjusted_monthly = gross_monthly - employee_pension
        adjusted_annual = gross_annual - (employee_pension * 12)
        
        # Calculate tax and NI on adjusted annual
        calcs = IncomeService.calculate_tax_and_ni(
            adjusted_annual, 
            tax_code, 
            employee_pension * 12
        )
        
        monthly_tax = calcs['tax'] / 12
        monthly_ni = calcs['ni'] / 12
        
        # Take home = gross monthly - employee pension - tax - NI - other deductions
        take_home = gross_monthly - employee_pension - monthly_tax - monthly_ni - avc - other
        
        # Determine tax year (Apr-Apr)
        if pay_date.month >= 4:
            tax_year = f"{pay_date.year}-{pay_date.year + 1}"
        else:
            tax_year = f"{pay_date.year - 1}-{pay_date.year}"
        
        # Create income record
        income = Income(
            person=person,
            pay_date=pay_date,
            tax_year=tax_year,
            gross_annual_income=gross_annual,
            gross_monthly_income=gross_monthly,
            employer_pension_percent=employer_pension_pct,
            employee_pension_percent=employee_pension_pct,
            employer_pension_amount=employer_pension,
            employee_pension_amount=employee_pension,
            total_pension=total_pension,
            adjusted_monthly_income=adjusted_monthly,
            adjusted_annual_income=adjusted_annual,
            tax_code=tax_code,
            income_tax=monthly_tax,
            national_insurance=monthly_ni,
            avc=avc,
            other_deductions=other,
            take_home=take_home,
            estimated_annual_take_home=take_home * 12,
            deposit_account_id=deposit_account_id,
            source=source
        )
        
        db.session.add(income)
        db.session.flush()  # Get income ID
        
        # Create linked transaction if requested
        if create_transaction and deposit_account_id:
            transaction = IncomeService.create_income_transaction(income)
            income.transaction_id = transaction.id
        
        db.session.commit()
        return income
    
    @staticmethod
    def create_income_transaction(income):
        """Create a linked transaction for income record"""
        # Find or create "Salary" category
        salary_category = Category.query.filter_by(name='Salary', type='Income').first()
        if not salary_category:
            salary_category = Category(name='Salary', type='Income')
            db.session.add(salary_category)
            db.session.flush()
        
        # Create transaction
        transaction = Transaction(
            account_id=income.deposit_account_id,
            category_id=salary_category.id,
            amount=float(income.take_home),
            transaction_date=income.pay_date,
            description=f"{income.person} Salary",
            item=f"Take home: £{income.take_home:,.2f}",
            payment_type='BACS',
            is_paid=True,
            is_forecasted=False,
            year_month=f"{income.pay_date.year}-{income.pay_date.month:02d}"
        )
        
        db.session.add(transaction)
        db.session.flush()
        
        # Recalculate account balance
        Transaction.recalculate_account_balance(income.deposit_account_id)
        
        return transaction
    
    @staticmethod
    def get_income_summary(person=None, year=None):
        """Get income summary statistics"""
        query = Income.query
        
        if person:
            query = query.filter_by(person=person)
        
        if year:
            query = query.filter(
                db.func.extract('year', Income.pay_date) == year
            )
        
        incomes = query.order_by(Income.pay_date.desc()).all()
        
        if not incomes:
            return {
                'records': [],
                'count': 0,
                'total_gross': 0,
                'total_take_home': 0,
                'total_tax': 0,
                'total_ni': 0,
                'total_pension': 0,
                'avg_gross': 0,
                'avg_take_home': 0
            }
        
        total_gross = sum(float(i.gross_monthly_income) for i in incomes)
        total_take_home = sum(float(i.take_home) for i in incomes)
        total_tax = sum(float(i.income_tax) for i in incomes)
        total_ni = sum(float(i.national_insurance) for i in incomes)
        total_pension = sum(float(i.total_pension) for i in incomes)
        
        return {
            'records': incomes,
            'count': len(incomes),
            'total_gross': total_gross,
            'total_take_home': total_take_home,
            'total_tax': total_tax,
            'total_ni': total_ni,
            'total_pension': total_pension,
            'avg_gross': total_gross / len(incomes) if incomes else 0,
            'avg_take_home': total_take_home / len(incomes) if incomes else 0
        }
    
    @staticmethod
    def generate_income_for_month(recurring_income, target_date):
        """Generate an income record for a specific month from a recurring template"""
        # Calculate pay date for this month
        year = target_date.year
        month = target_date.month
        
        if recurring_income.pay_day == 0:
            # Last day of month
            pay_day = calendar.monthrange(year, month)[1]
        else:
            # Specific day, capped at last day of month
            pay_day = min(recurring_income.pay_day, calendar.monthrange(year, month)[1])
        
        pay_date = date(year, month, pay_day)
        
        # Check if this income already exists
        existing = Income.query.filter(
            Income.person == recurring_income.person,
            Income.pay_date == pay_date
        ).first()
        
        if existing:
            return existing
        
        # Create new income record
        income = IncomeService.create_income_record(
            person=recurring_income.person,
            pay_date=pay_date,
            gross_annual=recurring_income.gross_annual_income,
            employer_pension_pct=recurring_income.employer_pension_percent,
            employee_pension_pct=recurring_income.employee_pension_percent,
            tax_code=recurring_income.tax_code,
            avc=recurring_income.avc,
            other=recurring_income.other_deductions,
            deposit_account_id=recurring_income.deposit_account_id,
            source=recurring_income.source,
            create_transaction=recurring_income.auto_create_transaction
        )
        
        return income
    
    @staticmethod
    def generate_missing_income(recurring_income_id, end_date=None):
        """Generate all missing income records for a recurring income template"""
        recurring = RecurringIncome.query.get(recurring_income_id)
        if not recurring or not recurring.is_active:
            return []
        
        # Determine date range
        start = recurring.last_generated_date or recurring.start_date
        if start < recurring.start_date:
            start = recurring.start_date
        
        # Move to next month if we've already generated for this month
        if recurring.last_generated_date:
            start = start + relativedelta(months=1)
        
        # Default end_date to current month if not specified
        if end_date is None:
            end_date = date.today()
        
        # Cap at recurring end_date if set
        if recurring.end_date and end_date > recurring.end_date:
            end_date = recurring.end_date
        
        # Generate income for each month
        generated = []
        current = start
        
        while current <= end_date:
            income = IncomeService.generate_income_for_month(recurring, current)
            if income:
                generated.append(income)
            
            # Update last_generated_date
            recurring.last_generated_date = current
            
            # Move to next month
            current = current + relativedelta(months=1)
        
        if generated:
            db.session.commit()
        
        return generated
    
    @staticmethod
    def generate_all_missing_income(end_date=None):
        """Generate missing income for all active recurring income templates"""
        recurring_incomes = RecurringIncome.query.filter_by(is_active=True).all()
        
        all_generated = []
        for recurring in recurring_incomes:
            generated = IncomeService.generate_missing_income(recurring.id, end_date)
            all_generated.extend(generated)
        
        return all_generated

