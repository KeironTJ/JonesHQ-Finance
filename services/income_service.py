"""
Income Service
Handles income record management, tax/NI calculations, and transaction creation
"""
from models.income import Income
from models.recurring_income import RecurringIncome
from models.accounts import Account
from models.transactions import Transaction
from models.categories import Category
from models.tax_settings import TaxSettings
from extensions import db
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from decimal import Decimal
import calendar


class IncomeService:
    
    @staticmethod
    def get_tax_settings_for_date(target_date):
        """Get tax settings for a specific date, falling back to defaults if not found"""
        settings = TaxSettings.get_for_date(target_date)
        
        if not settings:
            # Fallback to hardcoded defaults (2024-2025 rates)
            class DefaultSettings:
                personal_allowance = 12570
                basic_rate_limit = 50270
                higher_rate_limit = 125140
                basic_rate = Decimal('0.20')
                higher_rate = Decimal('0.40')
                additional_rate = Decimal('0.45')
                ni_threshold = 12570
                ni_upper_earnings = 50270
                ni_basic_rate = Decimal('0.12')
                ni_additional_rate = Decimal('0.02')
            
            return DefaultSettings()
        
        return settings
    
    @staticmethod
    def calculate_tax_and_ni(gross_annual, tax_code='1257L', pension_amount=0, pay_date=None):
        """
        Calculate income tax and National Insurance
        
        Args:
            gross_annual: Gross annual salary
            tax_code: UK tax code (e.g., '1257L')
            pension_amount: Annual pension contributions (pre-tax)
            pay_date: Date of payment (to determine which tax year rates to use)
        
        Returns:
            dict with tax, ni, and net amounts
        """
        # Convert to Decimal for accurate calculations
        gross_annual = Decimal(str(gross_annual))
        pension_amount = Decimal(str(pension_amount))
        
        # Get tax settings for this date
        if pay_date is None:
            pay_date = date.today()
        
        tax_settings = IncomeService.get_tax_settings_for_date(pay_date)
        
        # Parse tax code to get personal allowance
        try:
            code_number = int(tax_code.rstrip('L'))
            personal_allowance = code_number * 10
        except:
            personal_allowance = tax_settings.personal_allowance
        
        # Taxable income (after pension deductions)
        taxable_income = max(Decimal('0'), gross_annual - pension_amount)
        
        # Calculate tax using settings
        tax = Decimal('0')
        if taxable_income > personal_allowance:
            taxable = taxable_income - personal_allowance
            
            if taxable <= (tax_settings.basic_rate_limit - personal_allowance):
                # All in basic rate
                tax = taxable * Decimal(str(tax_settings.basic_rate))
            elif taxable <= (tax_settings.higher_rate_limit - personal_allowance):
                # Basic + Higher rate
                basic = (tax_settings.basic_rate_limit - personal_allowance)
                higher = taxable - basic
                tax = (basic * Decimal(str(tax_settings.basic_rate))) + (higher * Decimal(str(tax_settings.higher_rate)))
            else:
                # Basic + Higher + Additional
                basic = (tax_settings.basic_rate_limit - personal_allowance)
                higher = (tax_settings.higher_rate_limit - tax_settings.basic_rate_limit)
                additional = taxable - basic - higher
                tax = (basic * Decimal(str(tax_settings.basic_rate))) + (higher * Decimal(str(tax_settings.higher_rate))) + (additional * Decimal(str(tax_settings.additional_rate)))
        
        # Calculate National Insurance (on gross, before pension) using settings
        ni = Decimal('0')
        if gross_annual > tax_settings.ni_threshold:
            if gross_annual <= tax_settings.ni_upper_earnings:
                # All in basic NI rate
                ni_able = gross_annual - tax_settings.ni_threshold
                ni = ni_able * Decimal(str(tax_settings.ni_basic_rate))
            else:
                # Basic + Additional NI rate
                basic_ni = (tax_settings.ni_upper_earnings - tax_settings.ni_threshold) * Decimal(str(tax_settings.ni_basic_rate))
                additional_ni = (gross_annual - tax_settings.ni_upper_earnings) * Decimal(str(tax_settings.ni_additional_rate))
                ni = basic_ni + additional_ni
        
        return {
            'tax': tax.quantize(Decimal('0.01')),
            'ni': ni.quantize(Decimal('0.01')),
            'total_deductions': (tax + ni + pension_amount).quantize(Decimal('0.01')),
            'net_annual': (gross_annual - tax - ni - pension_amount).quantize(Decimal('0.01'))
        }
    
    @staticmethod
    def create_income_record(person, pay_date, gross_annual, employer_pension_pct=0,
                            employee_pension_pct=0, tax_code='1257L', avc=0, other=0,
                            deposit_account_id=None, source='', create_transaction=True,
                            recurring_income_id=None):
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
            recurring_income_id: ID of recurring income template that generated this
        """
        # Convert to Decimal
        gross_annual = Decimal(str(gross_annual))
        employer_pension_pct = Decimal(str(employer_pension_pct))
        employee_pension_pct = Decimal(str(employee_pension_pct))
        avc = Decimal(str(avc))
        other = Decimal(str(other))
        
        gross_monthly = (gross_annual / 12).quantize(Decimal('0.01'))
        
        # Calculate pension amounts
        employer_pension = (gross_monthly * (employer_pension_pct / 100)).quantize(Decimal('0.01'))
        employee_pension = (gross_monthly * (employee_pension_pct / 100)).quantize(Decimal('0.01'))
        total_pension = (employer_pension + employee_pension).quantize(Decimal('0.01'))
        
        # Adjusted income (after employee pension)
        adjusted_monthly = (gross_monthly - employee_pension).quantize(Decimal('0.01'))
        adjusted_annual = (gross_annual - (employee_pension * 12)).quantize(Decimal('0.01'))
        
        # Calculate tax and NI on adjusted annual (pass pay_date for correct tax year rates)
        calcs = IncomeService.calculate_tax_and_ni(
            adjusted_annual, 
            tax_code, 
            employee_pension * 12,
            pay_date
        )
        
        monthly_tax = (calcs['tax'] / 12).quantize(Decimal('0.01'))
        monthly_ni = (calcs['ni'] / 12).quantize(Decimal('0.01'))
        
        # Take home = gross monthly - employee pension - tax - NI - other deductions
        take_home = (gross_monthly - employee_pension - monthly_tax - monthly_ni - avc - other).quantize(Decimal('0.01'))
        
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
            estimated_annual_take_home=(take_home * 12).quantize(Decimal('0.01')),
            deposit_account_id=deposit_account_id,
            source=source,
            recurring_income_id=recurring_income_id
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
    def create_income_record_manual(person, pay_date, gross_annual, employer_pension,
                                   employee_pension, tax, ni, take_home, tax_code='1257L',
                                   avc=0, other=0, deposit_account_id=None, source='',
                                   create_transaction=True, recurring_income_id=None):
        """
        Create an income record with manual (actual payslip) values
        
        Args:
            person: Person name
            pay_date: Date of payment
            gross_annual: Gross annual salary
            employer_pension: Actual employer pension amount (monthly)
            employee_pension: Actual employee pension amount (monthly)
            tax: Actual tax amount (monthly)
            ni: Actual NI amount (monthly)
            take_home: Actual take home amount (monthly)
            tax_code: UK tax code
            avc: Additional voluntary contributions
            other: Other deductions
            deposit_account_id: Account to deposit income
            source: Employer name
            create_transaction: Whether to create linked transaction
            recurring_income_id: ID of recurring income template that generated this
        """
        # Convert to Decimal
        gross_annual = Decimal(str(gross_annual))
        employer_pension = Decimal(str(employer_pension))
        employee_pension = Decimal(str(employee_pension))
        tax = Decimal(str(tax))
        ni = Decimal(str(ni))
        take_home = Decimal(str(take_home))
        avc = Decimal(str(avc))
        other = Decimal(str(other))
        
        gross_monthly = (gross_annual / 12).quantize(Decimal('0.01'))
        total_pension = (employer_pension + employee_pension).quantize(Decimal('0.01'))
        adjusted_monthly = (gross_monthly - employee_pension).quantize(Decimal('0.01'))
        adjusted_annual = (gross_annual - (employee_pension * 12)).quantize(Decimal('0.01'))
        
        # Determine tax year
        if pay_date.month >= 4:
            tax_year = f"{pay_date.year}-{pay_date.year + 1}"
        else:
            tax_year = f"{pay_date.year - 1}-{pay_date.year}"
        
        # Create income record with manual values
        income = Income(
            person=person,
            pay_date=pay_date,
            tax_year=tax_year,
            gross_annual_income=gross_annual,
            gross_monthly_income=gross_monthly,
            employer_pension_percent=Decimal('0'),  # Not calculated from %
            employee_pension_percent=Decimal('0'),  # Not calculated from %
            employer_pension_amount=employer_pension,
            employee_pension_amount=employee_pension,
            total_pension=total_pension,
            adjusted_monthly_income=adjusted_monthly,
            adjusted_annual_income=adjusted_annual,
            tax_code=tax_code,
            income_tax=tax,
            national_insurance=ni,
            avc=avc,
            other_deductions=other,
            take_home=take_home,
            estimated_annual_take_home=(take_home * 12).quantize(Decimal('0.01')),
            deposit_account_id=deposit_account_id,
            source=source,
            is_manual_override=True,  # Flag as manually entered
            recurring_income_id=recurring_income_id
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
        salary_category = Category.query.filter_by(name='Salary', category_type='Income').first()
        if not salary_category:
            salary_category = Category(name='Salary', category_type='Income')
            db.session.add(salary_category)
            db.session.flush()
        
        # Create transaction
        transaction = Transaction(
            account_id=income.deposit_account_id,
            category_id=salary_category.id,
            amount=income.take_home,
            transaction_date=income.pay_date,
            description=f"{income.person} Salary",
            item=f"Take home: £{income.take_home:,.2f}",
            payment_type='BACS',
            is_paid=True,
            is_forecasted=False,
            year_month=f"{income.pay_date.year}-{income.pay_date.month:02d}",
            income_id=income.id
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
        
        # Check if using manual deductions
        if recurring_income.use_manual_deductions and recurring_income.manual_take_home:
            # Use manual override values from payslip
            income = IncomeService.create_income_record_manual(
                person=recurring_income.person,
                pay_date=pay_date,
                gross_annual=recurring_income.gross_annual_income,
                employer_pension=recurring_income.manual_employer_pension or Decimal('0'),
                employee_pension=recurring_income.manual_employee_pension or Decimal('0'),
                tax=recurring_income.manual_tax_monthly or Decimal('0'),
                ni=recurring_income.manual_ni_monthly or Decimal('0'),
                take_home=recurring_income.manual_take_home,
                tax_code=recurring_income.tax_code,
                avc=recurring_income.avc,
                other=recurring_income.other_deductions,
                deposit_account_id=recurring_income.deposit_account_id,
                source=recurring_income.source,
                create_transaction=recurring_income.auto_create_transaction,
                recurring_income_id=recurring_income.id
            )
        else:
            # Use automatic calculation
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
                create_transaction=recurring_income.auto_create_transaction,
                recurring_income_id=recurring_income.id
            )
        
        return income
    
    @staticmethod
    def generate_missing_income(recurring_income_id, end_date=None):
        """Generate all missing income records for a recurring income template"""
        recurring = RecurringIncome.query.get(recurring_income_id)
        if not recurring or not recurring.is_active:
            return []
        
        # Determine date range - use first of month for comparisons
        if recurring.last_generated_date:
            # Start from month AFTER last generated
            start = (recurring.last_generated_date.replace(day=1) + relativedelta(months=1))
        else:
            # Start from beginning
            start = recurring.start_date.replace(day=1)
        
        # Determine end date for generation
        if end_date is None:
            if recurring.end_date:
                # Use the recurring income's end date
                end_date = recurring.end_date
            else:
                # No end date set - generate 20 years ahead
                end_date = date.today() + relativedelta(years=20)
        
        # Normalize to first of month for comparison
        end_date = end_date.replace(day=1)
        
        # Generate income for each month
        generated = []
        current = start
        
        while current <= end_date:
            income = IncomeService.generate_income_for_month(recurring, current)
            if income:
                generated.append(income)
            
            # Update last_generated_date to this month
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

    @staticmethod
    def sync_income_to_transaction(income):
        """Update linked transaction to match income changes"""
        if not income.transaction_id:
            return None
        
        transaction = Transaction.query.get(income.transaction_id)
        if not transaction:
            return None
        
        # Sync fields from income to transaction
        transaction.amount = income.take_home
        transaction.transaction_date = income.pay_date
        transaction.description = f"{income.person} Salary"
        transaction.item = f"Take home: £{income.take_home:,.2f}"
        transaction.account_id = income.deposit_account_id
        transaction.year_month = f"{income.pay_date.year}-{income.pay_date.month:02d}"
        
        db.session.flush()
        
        # Recalculate account balance
        if transaction.account_id:
            Transaction.recalculate_account_balance(transaction.account_id)
        
        return transaction

    @staticmethod
    def delete_income_range(recurring_income_id, start_date, end_date, force=False):
        """
        Delete income records within a date range for a specific recurring income
        
        Args:
            recurring_income_id: ID of recurring income template
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)
            force: If True, delete even if linked to transactions (will break transaction links first)
        
        Returns:
            dict with deleted count and any warnings
        """
        recurring = RecurringIncome.query.get(recurring_income_id)
        if not recurring:
            raise ValueError("Recurring income not found")
        
        # Find all income records in this range from this specific recurring income template
        income_records = Income.query.filter(
            Income.recurring_income_id == recurring_income_id,
            Income.pay_date >= start_date,
            Income.pay_date <= end_date
        ).all()
        
        deleted = 0
        skipped_with_transactions = []
        
        for income in income_records:
            # Check if linked to a PAID transaction
            should_protect = False
            if income.transaction_id:
                transaction = Transaction.query.get(income.transaction_id)
                if transaction and transaction.is_paid:
                    should_protect = True
            
            if should_protect:
                if not force:
                    # Skip deletion - this income is already paid
                    skipped_with_transactions.append({
                        'date': income.pay_date,
                        'amount': income.take_home,
                        'is_paid': True
                    })
                    continue
                else:
                    # Force mode: break the link before deletion (even for paid)
                    transaction = Transaction.query.get(income.transaction_id)
                    if transaction:
                        transaction.income_id = None
                    income.transaction_id = None
                    db.session.flush()
            else:
                # Unpaid or no transaction - safe to delete, break link if exists
                if income.transaction_id:
                    transaction = Transaction.query.get(income.transaction_id)
                    if transaction:
                        transaction.income_id = None
                    income.transaction_id = None
                    db.session.flush()
            
            db.session.delete(income)
            deleted += 1
        
        if deleted > 0:
            # Update last_generated_date to before the deleted range
            # This allows regeneration from the start of the deleted range
            if start_date <= recurring.last_generated_date if recurring.last_generated_date else date.max:
                # Reset to month before the deleted range
                recurring.last_generated_date = (start_date.replace(day=1) - relativedelta(months=1))
        
        db.session.commit()
        
        return {
            'deleted': deleted,
            'skipped': len(skipped_with_transactions),
            'skipped_records': skipped_with_transactions
        }

    @staticmethod
    def regenerate_income_range(recurring_income_id, start_date, end_date, force=False):
        """
        Delete and regenerate income records for a date range
        
        Args:
            recurring_income_id: ID of recurring income template
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)
            force: If True, delete and regenerate even if transactions exist
        
        Returns:
            dict with results
        """
        # Step 1: Delete existing records in range
        delete_result = IncomeService.delete_income_range(
            recurring_income_id, start_date, end_date, force
        )
        
        # Step 2: Regenerate the records
        generated = IncomeService.generate_missing_income(
            recurring_income_id, 
            end_date=end_date
        )
        
        # Filter to only count records in the target range
        regenerated = [
            inc for inc in generated 
            if start_date <= inc.pay_date <= end_date
        ]
        
        return {
            'deleted': delete_result['deleted'],
            'skipped': delete_result['skipped'],
            'regenerated': len(regenerated),
            'skipped_records': delete_result['skipped_records']
        }

