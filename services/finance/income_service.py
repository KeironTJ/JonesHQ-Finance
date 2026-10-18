"""
Income Service
==============
Income record management: payslip estimation, actual-payslip entry, transaction
creation, and recurring-income generation.

All tax / NI / pension maths lives in ``services.finance.payroll_calculator`` —
this service never calculates deductions itself, so every screen agrees.

Two entry modes
---------------
  Calculated  — provide gross salary + percentages; deductions are estimated
                from the UK tax-band settings (TaxSettings model).
  Manual      — provide actual payslip figures; stored verbatim with
                is_manual_override=True.

Transaction link
----------------
Each Income record can be linked to one bank Transaction (the take-home deposit).
When a RecurringIncome template has a category_id, it is used for that transaction;
otherwise a 'Salary' income category is created automatically.

Tax year convention
-------------------
UK tax year: 6 Apr year N → 5 Apr year N+1.  Stored as "YYYY-YYYY" (e.g. "2025-2026").

Primary entry points
--------------------
  create_income_record()        — estimated deductions from % settings
  create_income_record_manual() — actual deductions from payslip
  create_one_off_income(data)   — form wrapper around create_income_record()
  update_income_record(id, data)— edit (calculated or manual mode)
  record_actual_payslip(id, data)
  preview_payslip(data)         — estimate without saving
  generate_missing_income()     — fill gaps for one RecurringIncome template
  generate_all_missing_income() — same for all active templates
  sync_income_to_transaction()  — propagate income edits to the linked transaction
  delete_income_range()         — remove income records in a date window
  regenerate_income_range()     — delete then recreate records in a date window
"""
import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, func, or_

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.income import Income
from models.income_change import IncomeChange
from models.pensions import Pension
from models.recurring_income import RecurringIncome
from models.tax_settings import TaxSettings
from models.transactions import Transaction
from services.finance import income_schedule, payroll_calculator
from services.finance.payday_service import PaydayService
from utils import db_helpers
from utils.db_helpers import family_get, family_get_or_404, family_query


MAX_MONEY = Decimal('99999999.99')  # Numeric(10, 2) ceiling
MAX_TEMPLATE_YEARS = 60             # Longest a single job template may run
GENERATION_HORIZON_YEARS = 50       # Upper bound for trim / range validation
FORECAST_HORIZON_MONTHS = 24        # Forecast rows are saved this far ahead; the plan projects beyond
MAX_RANGE_YEARS = 50                # Longest delete/regenerate window
ORPHAN_SERIES_MIN = 3               # Detached future rows in a run this long are leftover forecasts
MAX_ANNUAL_RISE = Decimal('50')     # % — sanity cap for pay rises


class IncomeService:
    """
    Income record management. All monetary values use Decimal throughout;
    results are quantized to 2dp before being stored.
    """

    # ------------------------------------------------------------------
    # Input parsing / validation
    # ------------------------------------------------------------------

    @staticmethod
    def _check_decimal(value, label, minimum=Decimal('0'), maximum=MAX_MONEY):
        try:
            value = value if isinstance(value, Decimal) else Decimal(str(value).strip().replace(',', ''))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError(f'{label} must be a number.')
        if not value.is_finite():
            raise ValueError(f'{label} must be a number.')
        if minimum is not None and value < minimum:
            raise ValueError(f'{label} cannot be less than {minimum}.')
        if maximum is not None and value > maximum:
            raise ValueError(f'{label} cannot be more than {maximum}.')
        return value

    @staticmethod
    def _decimal(data, key, label, default=Decimal('0'), required=False, **limits):
        raw = data.get(key)
        if raw is None or str(raw).strip() == '':
            if required:
                raise ValueError(f'{label} is required.')
            return default
        return IncomeService._check_decimal(raw, label, **limits)

    @staticmethod
    def _percent(data, key, label):
        return IncomeService._decimal(data, key, label, maximum=Decimal('100'))

    @staticmethod
    def _date(data, key, label, required=True):
        raw = (data.get(key) or '').strip() if isinstance(data.get(key), str) else data.get(key)
        if not raw:
            if required:
                raise ValueError(f'{label} is required.')
            return None
        if isinstance(raw, date):
            return raw
        try:
            return datetime.strptime(raw, '%Y-%m-%d').date()
        except ValueError:
            raise ValueError(f'{label} must be a valid date (YYYY-MM-DD).')

    @staticmethod
    def _int_id(data, key, label):
        raw = data.get(key)
        if raw in (None, ''):
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ValueError(f'Invalid {label} selected.')

    @staticmethod
    def _pay_day(data):
        try:
            pay_day = int(data.get('pay_day'))
        except (TypeError, ValueError):
            raise ValueError('Pay day must be a whole number between 0 and 31.')
        if not 0 <= pay_day <= 31:
            raise ValueError('Pay day must be between 1 and 31 (or 0 for the last day of the month).')
        return pay_day

    @staticmethod
    def _tax_code(raw):
        if not raw or not str(raw).strip():
            raise ValueError('Tax code is required.')
        return payroll_calculator.parse_tax_code(raw).raw

    @staticmethod
    def _text(data, key, max_len, default=''):
        value = (data.get(key) or default or '').strip()
        return value[:max_len]

    @staticmethod
    def _choice(data, key, options, label, default):
        value = (data.get(key) or default or '').strip()
        if value not in options:
            raise ValueError(f'Unknown {label} selected.')
        return value

    @staticmethod
    def _student_loan_plans(data):
        """Form checkboxes (getlist) or a CSV string -> validated CSV, or None."""
        raw = data.getlist('student_loan_plans') if hasattr(data, 'getlist') else data.get('student_loan_plans')
        if isinstance(raw, list) and len(raw) == 1:
            raw = raw[0]
        plans = payroll_calculator.normalise_student_loan_plans(raw or ())
        return ','.join(plans) or None

    @staticmethod
    def _validate_family_references(deposit_account_id=None, category_id=None):
        if deposit_account_id is not None and not family_get(Account, deposit_account_id):
            raise ValueError('Invalid deposit account selected')
        if category_id is not None and not family_get(Category, category_id):
            raise ValueError('Invalid category selected')

    @staticmethod
    def _validate_template_dates(start_date, end_date):
        if end_date is None:
            return
        if end_date < start_date:
            raise ValueError('End date cannot be before the start date.')
        if end_date > start_date + relativedelta(years=MAX_TEMPLATE_YEARS):
            raise ValueError(f'End date cannot be more than {MAX_TEMPLATE_YEARS} years after the start date.')

    @staticmethod
    def _validate_range(start_date, end_date):
        if end_date < start_date:
            raise ValueError('End date cannot be before the start date.')
        if end_date > start_date + relativedelta(years=MAX_RANGE_YEARS):
            raise ValueError(f'Date range cannot be longer than {MAX_RANGE_YEARS} years.')

    # ------------------------------------------------------------------
    # Privacy
    # ------------------------------------------------------------------

    @staticmethod
    def _may_make_private(person):
        """
        Making income private hides it from the rest of the household, so only the
        person it belongs to may do that. For income not tied to a household
        member's name (e.g. 'Household'), the household owner may.
        """
        from models.users import User

        uid = db_helpers.get_current_user_id()
        user = db.session.get(User, uid) if uid else None
        if user is None:
            return False
        person_key = (person or '').strip().lower()
        own_names = {(user.member_name or '').strip().lower(), (user.name or '').strip().lower()} - {''}
        if person_key in own_names:
            return True
        member_names = set()
        for member in family_query(User).all():
            member_names |= {(member.member_name or '').strip().lower(), (member.name or '').strip().lower()}
        return person_key not in member_names and user.is_household_owner

    @staticmethod
    def _resolve_owner_id(data, person, record=None):
        """Work out owner_id for a create/update request without allowing a member
        to take over somebody else's shared income."""
        wants_private = data.get('visibility') == 'private'
        if record is not None and record.owner_id is not None:
            # A private record is only visible (and so only editable) by its owner.
            return record.owner_id if wants_private else None
        if not wants_private:
            return None
        # On edits, authorise against the record's existing person so a member
        # can't relabel someone else's shared income as theirs and hide it.
        check_person = record.person if record is not None else person
        if not IncomeService._may_make_private(check_person):
            raise ValueError(f"Only {check_person} can make this income private.")
        return db_helpers.get_current_user_id()

    # ------------------------------------------------------------------
    # Recurring income templates
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_recurring_fields(recurring, data):
        deposit_account_id = IncomeService._int_id(data, 'deposit_account_id', 'deposit account')
        category_id = IncomeService._int_id(data, 'category_id', 'category')
        IncomeService._validate_family_references(deposit_account_id, category_id)

        start_date = IncomeService._date(data, 'start_date', 'Start date')
        end_date = IncomeService._date(data, 'end_date', 'End date', required=False)
        IncomeService._validate_template_dates(start_date, end_date)

        person = IncomeService._text(data, 'person', 50, default=recurring.person or 'Household') or 'Household'
        recurring.owner_id = IncomeService._resolve_owner_id(
            data, person, record=recurring if recurring.id else None
        )
        recurring.person = person
        recurring.start_date = start_date
        recurring.end_date = end_date
        recurring.income_type = IncomeService._choice(
            data, 'income_type', payroll_calculator.INCOME_TYPES, 'income type', recurring.income_type or 'employment')
        recurring.pay_frequency = IncomeService._choice(
            data, 'pay_frequency', payroll_calculator.PAY_FREQUENCIES, 'pay frequency', recurring.pay_frequency or 'monthly')
        recurring.pension_scheme = IncomeService._choice(
            data, 'pension_scheme', payroll_calculator.PENSION_SCHEME_LABELS, 'pension scheme',
            recurring.pension_scheme or payroll_calculator.DEFAULT_PENSION_SCHEME)
        first_pay_date = IncomeService._date(data, 'first_pay_date', 'First pay date', required=False)
        if recurring.pay_frequency == 'monthly':
            recurring.pay_day = IncomeService._pay_day(data)
            recurring.first_pay_date = None
        else:
            first_pay_date = first_pay_date or start_date
            if first_pay_date < start_date:
                raise ValueError('First pay date cannot be before the start date.')
            recurring.first_pay_date = first_pay_date
            recurring.pay_day = first_pay_date.day
        recurring.student_loan_plans = IncomeService._student_loan_plans(data)
        recurring.set_aside_percent = IncomeService._decimal(
            data, 'set_aside_percent', 'Tax set-aside %', default=None, maximum=Decimal('100'))
        recurring.annual_increase_percent = IncomeService._decimal(
            data, 'annual_increase_percent', 'Yearly pay rise %', default=None, maximum=MAX_ANNUAL_RISE) or None
        recurring.annual_increase_start = IncomeService._date(
            data, 'annual_increase_start', 'First yearly rise date', required=False)
        if recurring.annual_increase_percent and not recurring.annual_increase_start:
            raise ValueError('Choose the date of the next yearly pay rise.')
        if not recurring.annual_increase_percent:
            recurring.annual_increase_start = None
        pension_id = IncomeService._int_id(data, 'pension_id', 'pension')
        if pension_id is not None and not family_get(Pension, pension_id):
            raise ValueError('Invalid pension selected')
        recurring.pension_id = pension_id
        recurring.gross_annual_income = IncomeService._decimal(
            data, 'gross_annual', 'Gross annual income', required=True
        )
        recurring.employer_pension_percent = IncomeService._percent(data, 'employer_pension_pct', 'Employer pension %')
        recurring.employee_pension_percent = IncomeService._percent(data, 'employee_pension_pct', 'Employee pension %')
        recurring.tax_code = IncomeService._tax_code(data.get('tax_code'))
        recurring.avc = IncomeService._decimal(data, 'avc', 'AVC')
        recurring.other_deductions = IncomeService._decimal(data, 'other', 'Other deductions')
        recurring.deposit_account_id = deposit_account_id
        recurring.category_id = category_id
        recurring.auto_create_transaction = data.get('auto_create_transaction') == 'on'
        recurring.source = IncomeService._text(data, 'source', 100)
        recurring.description = IncomeService._text(data, 'description', 255)
        recurring.use_manual_deductions = data.get('use_manual_deductions') == 'on'
        manual_fields = {
            'manual_tax_monthly': 'Manual tax',
            'manual_ni_monthly': 'Manual NI',
            'manual_employee_pension': 'Manual employee pension',
            'manual_employer_pension': 'Manual employer pension',
            'manual_take_home': 'Manual take home',
        }
        for field, label in manual_fields.items():
            setattr(recurring, field, IncomeService._decimal(data, field, label, default=None))

    @staticmethod
    def create_recurring_income(data):
        recurring = RecurringIncome(family_id=db_helpers.get_family_id(), is_active=True)
        IncomeService._apply_recurring_fields(recurring, data)
        db.session.add(recurring)
        db.session.commit()
        return recurring

    @staticmethod
    def update_recurring_income(recurring_id, data):
        """Save the source's settings, then re-price its unsettled future forecasts."""
        recurring = family_get_or_404(RecurringIncome, recurring_id)
        IncomeService._apply_recurring_fields(recurring, data)
        recurring.is_active = data.get('is_active') == 'on'
        # Generated records inherit the template's visibility.
        for income in family_query(Income).filter(Income.recurring_income_id == recurring.id).all():
            income.owner_id = recurring.owner_id
        db.session.commit()
        IncomeService.refresh_forecasts(recurring.id)
        return recurring

    @staticmethod
    def save_income_source(data, recurring_id=None):
        """Create or update a source and bring its saved forecasts up to date."""
        if recurring_id is None:
            recurring = IncomeService.create_recurring_income(data)
            IncomeService.generate_missing_income(recurring.id)
            return recurring
        return IncomeService.update_recurring_income(recurring_id, data)

    # ------------------------------------------------------------------
    # Timeline (pay rises, bonuses, tax code / pension changes)
    # ------------------------------------------------------------------

    @staticmethod
    def add_income_change(recurring_id, data):
        recurring = family_get_or_404(RecurringIncome, recurring_id)
        change_type = IncomeService._choice(data, 'change_type', IncomeChange.CHANGE_TYPES, 'change type', '')
        effective = IncomeService._date(data, 'effective_date', 'Effective date')
        if effective < recurring.start_date:
            raise ValueError('A change cannot be dated before the income starts.')
        if effective > recurring.start_date + relativedelta(years=MAX_TEMPLATE_YEARS):
            raise ValueError(f'A change cannot be more than {MAX_TEMPLATE_YEARS} years after the start date.')
        change = IncomeChange(
            family_id=recurring.family_id or db_helpers.get_family_id(),
            recurring_income_id=recurring.id,
            effective_date=effective,
            change_type=change_type,
            description=IncomeService._text(data, 'description', 255) or None,
        )
        if change_type in ('salary', 'bonus'):
            change.amount = IncomeService._decimal(
                data, 'amount', 'New salary' if change_type == 'salary' else 'Bonus amount', required=True)
            if change.amount <= 0:
                raise ValueError('Amount must be more than zero.')
            change.bonus_pensionable = change_type == 'bonus' and data.get('bonus_pensionable') == 'on'
        elif change_type == 'percent_rise':
            change.percent = IncomeService._decimal(
                data, 'percent', 'Pay rise %', required=True, minimum=-MAX_ANNUAL_RISE, maximum=MAX_ANNUAL_RISE)
            if change.percent == 0:
                raise ValueError('Pay rise % cannot be zero.')
        elif change_type == 'tax_code':
            change.tax_code = IncomeService._tax_code(data.get('tax_code'))
        elif change_type == 'pension':
            change.employee_pension_percent = IncomeService._decimal(
                data, 'employee_pension_pct', 'Employee pension %', default=None, maximum=Decimal('100'))
            change.employer_pension_percent = IncomeService._decimal(
                data, 'employer_pension_pct', 'Employer pension %', default=None, maximum=Decimal('100'))
            if change.employee_pension_percent is None and change.employer_pension_percent is None:
                raise ValueError('Enter the new employee and/or employer pension %.')
        db.session.add(change)
        db.session.commit()
        IncomeService.refresh_forecasts(recurring.id)
        return change

    @staticmethod
    def delete_income_change(change_id):
        change = family_get_or_404(IncomeChange, change_id)
        recurring_id = change.recurring_income_id
        db.session.delete(change)
        db.session.commit()
        IncomeService.refresh_forecasts(recurring_id)
        return recurring_id

    @staticmethod
    def _is_settled(income, transaction=None):
        """True when an income record represents real history that must be kept."""
        if income.is_paid or income.is_manual_override:
            return True
        return transaction is not None and bool(transaction.is_paid)

    @staticmethod
    def _is_history(income, transaction=None):
        """
        Stricter than _is_settled, used when the whole job goes away (template
        deleted / job ended): keep only money actually received. A manual
        override counts only once its pay date has arrived — future rows are
        always forecasts (legacy generation also flagged template-derived
        forecasts as overrides).
        """
        if income.is_paid or (transaction is not None and transaction.is_paid):
            return True
        return bool(income.is_manual_override) and income.pay_date <= date.today()

    @staticmethod
    def delete_recurring_income(recurring_id):
        """
        Delete a template. Forecast records (and their forecast transactions)
        are removed; history (see _is_history) is kept but detached from the
        template. Folded expense groups for this job revert to 'separate'.
        """
        from models.expense_reimbursement_group import ExpenseReimbursementGroup
        from services.finance.expense_sync_service import ExpenseSyncService

        recurring = family_get_or_404(RecurringIncome, recurring_id)
        affected_accounts = set()

        for income in family_query(Income).filter(Income.recurring_income_id == recurring.id).all():
            txn = family_get(Transaction, income.transaction_id) if income.transaction_id else None
            if IncomeService._is_history(income, txn):
                income.recurring_income_id = None
                continue
            ExpenseSyncService.unlink_expenses_from_income(income.id)
            income.transaction_id = None
            db.session.flush()
            if txn:
                affected_accounts.add(txn.account_id)
                db.session.delete(txn)
            db.session.delete(income)

        for group in family_query(ExpenseReimbursementGroup).filter(
            ExpenseReimbursementGroup.recurring_income_id == recurring.id
        ).all():
            group.recurring_income_id = None
            if group.mode == 'folded':
                group.mode = 'separate'

        for change in family_query(IncomeChange).filter(IncomeChange.recurring_income_id == recurring.id).all():
            db.session.delete(change)
        db.session.flush()
        db.session.delete(recurring)
        db.session.flush()
        IncomeService._recalculate_balances(affected_accounts)
        db.session.commit()

    @staticmethod
    def _sync_folded_expenses(income):
        """Recompute any 'folded' reimbursement groups tied to this income's job
        after it is created/edited, so expenses stay correctly totalled in. Never
        raises — a sync failure here shouldn't block saving the income record."""
        if not income.recurring_income_id:
            return
        IncomeService._sync_folded_for(income.recurring_income_id)

    @staticmethod
    def _sync_folded_for(recurring_income_id):
        try:
            from services.finance.expense_sync_service import ExpenseSyncService
            ExpenseSyncService.sync_folded_expenses_for_recurring_income(recurring_income_id)
        except Exception:
            from flask import current_app
            current_app.logger.exception(
                f'Failed to sync folded expenses for recurring_income_id={recurring_income_id}'
            )

    @staticmethod
    def _recalculate_balances(account_ids):
        for account_id in {a for a in account_ids if a}:
            Transaction.recalculate_account_balance(account_id)

    # ------------------------------------------------------------------
    # Income record deletion
    # ------------------------------------------------------------------

    @staticmethod
    def delete_income_record(income_id, keep_transaction=False):
        income = family_get_or_404(Income, income_id)
        from services.finance.expense_sync_service import ExpenseSyncService
        ExpenseSyncService.unlink_expenses_from_income(income.id)
        account_id = None
        if income.transaction_id:
            transaction = family_get(Transaction, income.transaction_id)
            if transaction:
                income.transaction_id = None
                db.session.flush()
                if not keep_transaction:
                    account_id = transaction.account_id
                    db.session.delete(transaction)
        db.session.delete(income)
        db.session.flush()
        IncomeService._recalculate_balances([account_id])
        db.session.commit()

    @staticmethod
    def delete_income_records(income_ids):
        from services.finance.expense_sync_service import ExpenseSyncService
        deleted = 0
        affected_accounts = set()
        for income_id in income_ids:
            try:
                income_id = int(income_id)
            except (TypeError, ValueError):
                continue
            income = family_get(Income, income_id)
            if not income:
                continue
            ExpenseSyncService.unlink_expenses_from_income(income.id)
            if income.transaction_id:
                transaction = family_get(Transaction, income.transaction_id)
                if transaction:
                    income.transaction_id = None
                    db.session.flush()
                    affected_accounts.add(transaction.account_id)
                    db.session.delete(transaction)
            db.session.delete(income)
            deleted += 1
        db.session.flush()
        IncomeService._recalculate_balances(affected_accounts)
        db.session.commit()
        return deleted

    # ------------------------------------------------------------------
    # Tax / payslip calculation
    # ------------------------------------------------------------------

    @staticmethod
    def get_tax_settings_for_date(target_date):
        """Get tax settings for a specific date, falling back to defaults if not found"""
        settings = TaxSettings.get_for_date(target_date)
        if settings:
            return settings

        class DefaultSettings:
            # 2024-2025 / 2025-2026 rUK rates
            personal_allowance = Decimal('12570')
            basic_rate_limit = Decimal('50270')
            higher_rate_limit = Decimal('125140')
            basic_rate = Decimal('0.20')
            higher_rate = Decimal('0.40')
            additional_rate = Decimal('0.45')
            ni_threshold = Decimal('12570')
            ni_upper_earnings = Decimal('50270')
            ni_basic_rate = Decimal('0.08')
            ni_additional_rate = Decimal('0.02')

        return DefaultSettings()

    @staticmethod
    def estimate_payslip(gross_annual, tax_code='1257L', pay_date=None, employee_pension_pct=0,
                         employer_pension_pct=0, avc=0, other=0):
        """Estimate one month's payslip using the tax settings for *pay_date*."""
        pay_date = pay_date or date.today()
        return payroll_calculator.calculate_monthly_payslip(
            gross_annual=gross_annual,
            tax_code=tax_code,
            settings=IncomeService.get_tax_settings_for_date(pay_date),
            pay_date=pay_date,
            employee_pension_pct=employee_pension_pct,
            employer_pension_pct=employer_pension_pct,
            avc=avc,
            other=other,
        )

    @staticmethod
    def calculate_tax_and_ni(gross_annual, tax_code='1257L', pension_amount=0, pay_date=None):
        """
        Annual income tax and NI. Kept for scripts/back-compat.

        *gross_annual* is total gross pay; *pension_amount* is the annual pre-tax
        (salary-sacrifice) pension, removed from both taxable and NI-able pay.
        """
        gross_annual = Decimal(str(gross_annual))
        pension_amount = Decimal(str(pension_amount))
        settings = IncomeService.get_tax_settings_for_date(pay_date or date.today())
        pay = max(Decimal('0'), gross_annual - pension_amount)
        tax, _ = payroll_calculator.calculate_annual_income_tax(pay, tax_code, settings)
        ni = payroll_calculator.calculate_annual_ni(pay, settings)
        tax = tax.quantize(Decimal('0.01'))
        ni = ni.quantize(Decimal('0.01'))
        return {
            'tax': tax,
            'ni': ni,
            'total_deductions': (tax + ni + pension_amount).quantize(Decimal('0.01')),
            'net_annual': (gross_annual - tax - ni - pension_amount).quantize(Decimal('0.01')),
        }

    @staticmethod
    def preview_payslip(data):
        """Parse a preview request and return the estimate as a JSON-safe dict.
        Accepts the source-form fields, so the live preview matches forecasts."""
        data = data or {}
        pay_date = IncomeService._date(data, 'pay_date', 'Pay date', required=False) or date.today()
        estimate = payroll_calculator.calculate_payslip(
            IncomeService._decimal(data, 'gross_annual', 'Gross annual income', required=True),
            IncomeService._tax_code(data.get('tax_code')),
            IncomeService.get_tax_settings_for_date(pay_date),
            pay_date,
            frequency=IncomeService._choice(data, 'pay_frequency', payroll_calculator.PAY_FREQUENCIES, 'pay frequency', 'monthly'),
            income_type=IncomeService._choice(data, 'income_type', payroll_calculator.INCOME_TYPES, 'income type', 'employment'),
            employee_pension_pct=IncomeService._percent(data, 'employee_pension_pct', 'Employee pension %'),
            employer_pension_pct=IncomeService._percent(data, 'employer_pension_pct', 'Employer pension %'),
            pension_scheme=IncomeService._choice(
                data, 'pension_scheme', payroll_calculator.PENSION_SCHEME_LABELS, 'pension scheme',
                payroll_calculator.DEFAULT_PENSION_SCHEME),
            avc=IncomeService._decimal(data, 'avc', 'AVC'),
            other=IncomeService._decimal(data, 'other', 'Other deductions'),
            student_loan_plans=IncomeService._student_loan_plans(data) or (),
            bonus=IncomeService._decimal(data, 'bonus', 'Bonus'),
            bonus_pensionable=data.get('bonus_pensionable') in ('on', 'true', '1', True),
            set_aside_pct=IncomeService._decimal(data, 'set_aside_percent', 'Tax set-aside %', maximum=Decimal('100')),
        )
        return estimate.as_dict()

    @staticmethod
    def _apply_estimate(income, estimate):
        income.tax_year = estimate.tax_year
        income.pay_frequency = estimate.frequency
        income.gross_annual_income = estimate.gross_annual
        income.gross_monthly_income = estimate.gross_period
        income.bonus = estimate.bonus or None
        income.employer_pension_amount = estimate.employer_pension
        income.employee_pension_amount = estimate.employee_pension
        income.total_pension = estimate.total_pension
        income.adjusted_monthly_income = estimate.adjusted_period
        income.adjusted_annual_income = estimate.adjusted_annual
        income.income_tax = estimate.income_tax
        income.national_insurance = estimate.national_insurance
        income.student_loan = estimate.student_loan or None
        income.avc = estimate.avc
        income.other_deductions = estimate.other_deductions
        income.take_home = estimate.take_home
        income.estimated_annual_take_home = (estimate.take_home * estimate.periods_per_year).quantize(Decimal('0.01'))

    # ------------------------------------------------------------------
    # Income record creation / editing
    # ------------------------------------------------------------------

    @staticmethod
    def create_income_record(person, pay_date, gross_annual, employer_pension_pct=0,
                             employee_pension_pct=0, tax_code='1257L', avc=0, other=0,
                             deposit_account_id=None, source='', create_transaction=True,
                             recurring_income_id=None, owner_id=None, recalculate_balance=True,
                             commit=True):
        """Create an income record with estimated tax/NI/pension deductions."""
        IncomeService._validate_family_references(deposit_account_id=deposit_account_id)
        gross_annual = IncomeService._check_decimal(gross_annual, 'Gross annual income')
        employer_pension_pct = IncomeService._check_decimal(employer_pension_pct, 'Employer pension %', maximum=Decimal('100'))
        employee_pension_pct = IncomeService._check_decimal(employee_pension_pct, 'Employee pension %', maximum=Decimal('100'))
        avc = IncomeService._check_decimal(avc, 'AVC')
        other = IncomeService._check_decimal(other, 'Other deductions')
        tax_code = IncomeService._tax_code(tax_code)

        estimate = IncomeService.estimate_payslip(
            gross_annual, tax_code, pay_date, employee_pension_pct, employer_pension_pct, avc, other
        )
        income = Income(
            family_id=db_helpers.get_family_id(),
            person=person,
            pay_date=pay_date,
            employer_pension_percent=employer_pension_pct,
            employee_pension_percent=employee_pension_pct,
            tax_code=tax_code,
            deposit_account_id=deposit_account_id,
            source=source,
            recurring_income_id=recurring_income_id,
            owner_id=owner_id,
        )
        IncomeService._apply_estimate(income, estimate)
        return IncomeService._save_new_income(income, create_transaction, recalculate_balance, commit)

    @staticmethod
    def create_income_record_manual(person, pay_date, gross_annual, employer_pension,
                                    employee_pension, tax, ni, take_home, tax_code='1257L',
                                    avc=0, other=0, deposit_account_id=None, source='',
                                    create_transaction=True, recurring_income_id=None, owner_id=None,
                                    recalculate_balance=True, commit=True):
        """Create an income record with manual (actual payslip) monthly values."""
        IncomeService._validate_family_references(deposit_account_id=deposit_account_id)
        check = IncomeService._check_decimal
        gross_annual = check(gross_annual, 'Gross annual income')
        employer_pension = check(employer_pension, 'Employer pension')
        employee_pension = check(employee_pension, 'Employee pension')
        tax = check(tax, 'Income tax', minimum=-MAX_MONEY)  # tax refunds can be negative
        ni = check(ni, 'National Insurance')
        take_home = check(take_home, 'Take home', minimum=-MAX_MONEY)
        avc = check(avc, 'AVC')
        other = check(other, 'Other deductions')

        gross_monthly = (gross_annual / 12).quantize(Decimal('0.01'))
        income = Income(
            family_id=db_helpers.get_family_id(),
            person=person,
            pay_date=pay_date,
            tax_year=payroll_calculator.tax_year_for(pay_date),
            gross_annual_income=gross_annual,
            gross_monthly_income=gross_monthly,
            employer_pension_percent=Decimal('0'),
            employee_pension_percent=Decimal('0'),
            employer_pension_amount=employer_pension,
            employee_pension_amount=employee_pension,
            total_pension=(employer_pension + employee_pension).quantize(Decimal('0.01')),
            adjusted_monthly_income=(gross_monthly - employee_pension).quantize(Decimal('0.01')),
            adjusted_annual_income=(gross_annual - employee_pension * 12).quantize(Decimal('0.01')),
            tax_code=tax_code,
            income_tax=tax,
            national_insurance=ni,
            avc=avc,
            other_deductions=other,
            take_home=take_home,
            estimated_annual_take_home=(take_home * 12).quantize(Decimal('0.01')),
            deposit_account_id=deposit_account_id,
            source=source,
            is_manual_override=True,
            recurring_income_id=recurring_income_id,
            owner_id=owner_id,
        )
        return IncomeService._save_new_income(income, create_transaction, recalculate_balance, commit)

    @staticmethod
    def _save_new_income(income, create_transaction, recalculate_balance, commit):
        db.session.add(income)
        db.session.flush()
        if create_transaction and income.deposit_account_id:
            transaction = IncomeService.create_income_transaction(
                income, recalculate_balance=recalculate_balance
            )
            income.transaction_id = transaction.id
        if commit:
            db.session.commit()
            IncomeService._sync_folded_expenses(income)
        else:
            db.session.flush()
        return income

    @staticmethod
    def create_one_off_income(data):
        """Create a single (non-recurring) income record from form data."""
        person = IncomeService._text(data, 'person', 50, default='Household') or 'Household'
        deposit_account_id = IncomeService._int_id(data, 'deposit_account_id', 'deposit account')
        return IncomeService.create_income_record(
            person=person,
            pay_date=IncomeService._date(data, 'pay_date', 'Pay date'),
            gross_annual=IncomeService._decimal(data, 'gross_annual', 'Gross annual income', required=True),
            employer_pension_pct=IncomeService._percent(data, 'employer_pension_pct', 'Employer pension %'),
            employee_pension_pct=IncomeService._percent(data, 'employee_pension_pct', 'Employee pension %'),
            tax_code=data.get('tax_code'),
            avc=IncomeService._decimal(data, 'avc', 'AVC'),
            other=IncomeService._decimal(data, 'other', 'Other deductions'),
            deposit_account_id=deposit_account_id,
            source=IncomeService._text(data, 'source', 100),
            create_transaction=data.get('create_transaction') == 'on',
            owner_id=IncomeService._resolve_owner_id(data, person),
        )

    @staticmethod
    def update_income_record(income_id, data):
        """Edit an income record in calculated or manual (actual payslip) mode."""
        income = family_get_or_404(Income, income_id)
        mode = data.get('edit_mode', 'calculated')
        deposit_account_id = IncomeService._int_id(data, 'deposit_account_id', 'deposit account')
        IncomeService._validate_family_references(deposit_account_id=deposit_account_id)

        person = IncomeService._text(data, 'person', 50, default=income.person) or income.person
        income.owner_id = IncomeService._resolve_owner_id(data, person, record=income)
        income.person = person
        income.pay_date = IncomeService._date(data, 'pay_date', 'Pay date')
        income.source = IncomeService._text(data, 'source', 100)
        income.tax_code = IncomeService._tax_code(data.get('tax_code') or income.tax_code)
        income.deposit_account_id = deposit_account_id
        gross_annual = IncomeService._decimal(data, 'gross_annual', 'Gross annual income', required=True)
        avc = IncomeService._decimal(data, 'avc', 'AVC')
        other = IncomeService._decimal(data, 'other', 'Other deductions')
        bonus = IncomeService._decimal(data, 'bonus', 'Bonus', default=Decimal(str(income.bonus or 0)))
        frequency = income.pay_frequency or 'monthly'
        periods = payroll_calculator.PAY_FREQUENCIES.get(frequency, 12)

        if mode == 'manual':
            employer_pension = IncomeService._decimal(data, 'employer_pension_amount', 'Employer pension')
            employee_pension = IncomeService._decimal(data, 'employee_pension_amount', 'Employee pension')
            income.gross_annual_income = gross_annual
            income.bonus = bonus or None
            income.gross_monthly_income = (gross_annual / periods + bonus).quantize(Decimal('0.01'))
            income.employer_pension_amount = employer_pension
            income.employee_pension_amount = employee_pension
            income.total_pension = employer_pension + employee_pension
            income.income_tax = IncomeService._decimal(data, 'income_tax', 'Income tax', minimum=-MAX_MONEY)
            income.national_insurance = IncomeService._decimal(data, 'national_insurance', 'National Insurance')
            income.student_loan = IncomeService._decimal(data, 'student_loan', 'Student loan') or None
            income.take_home = IncomeService._decimal(data, 'take_home', 'Take home', required=True, minimum=-MAX_MONEY)
            income.avc = avc
            income.other_deductions = other
            income.employer_pension_percent = Decimal('0')
            income.employee_pension_percent = Decimal('0')
            income.adjusted_monthly_income = (income.gross_monthly_income - employee_pension).quantize(Decimal('0.01'))
            income.adjusted_annual_income = (gross_annual - employee_pension * periods).quantize(Decimal('0.01'))
            income.estimated_annual_take_home = (income.take_home * periods).quantize(Decimal('0.01'))
            income.tax_year = payroll_calculator.tax_year_for(income.pay_date)
            income.is_manual_override = True
            income.is_paid = income.pay_date <= date.today()
        else:
            income.employer_pension_percent = IncomeService._percent(data, 'employer_pension_pct', 'Employer pension %')
            income.employee_pension_percent = IncomeService._percent(data, 'employee_pension_pct', 'Employee pension %')
            source = income.recurring_income
            estimate = payroll_calculator.calculate_payslip(
                gross_annual, income.tax_code, IncomeService.get_tax_settings_for_date(income.pay_date),
                income.pay_date,
                frequency=frequency,
                income_type=getattr(source, 'income_type', None) or 'employment',
                employee_pension_pct=income.employee_pension_percent,
                employer_pension_pct=income.employer_pension_percent,
                pension_scheme=getattr(source, 'pension_scheme', None) or payroll_calculator.DEFAULT_PENSION_SCHEME,
                avc=avc,
                other=other,
                student_loan_plans=getattr(source, 'student_loan_plans', None) or (),
                bonus=bonus,
                set_aside_pct=getattr(source, 'set_aside_percent', None) or 0,
            )
            IncomeService._apply_estimate(income, estimate)
            income.is_manual_override = False

        IncomeService.sync_income_to_transaction(income)
        db.session.commit()
        return income

    @staticmethod
    def record_actual_payslip(income_id, data):
        """Quick entry of actual payslip figures for a generated income record."""
        income = family_get_or_404(Income, income_id)
        income.income_tax = IncomeService._decimal(data, 'tax', 'Income tax', required=True, minimum=-MAX_MONEY)
        income.national_insurance = IncomeService._decimal(data, 'ni', 'National Insurance', required=True)
        income.employer_pension_amount = IncomeService._decimal(data, 'employer_pension', 'Employer pension')
        income.employee_pension_amount = IncomeService._decimal(data, 'employee_pension', 'Employee pension')
        income.total_pension = income.employer_pension_amount + income.employee_pension_amount
        income.avc = IncomeService._decimal(data, 'avc', 'AVC')
        income.other_deductions = IncomeService._decimal(data, 'other', 'Other deductions')
        income.student_loan = IncomeService._decimal(
            data, 'student_loan', 'Student loan', default=Decimal(str(income.student_loan or 0))) or None
        income.take_home = IncomeService._decimal(data, 'take_home', 'Take home', required=True, minimum=-MAX_MONEY)
        periods = payroll_calculator.PAY_FREQUENCIES.get(income.pay_frequency or 'monthly', 12)
        income.estimated_annual_take_home = (income.take_home * periods).quantize(Decimal('0.01'))
        income.is_manual_override = True
        # Only mark as paid once the pay date has actually passed
        income.is_paid = income.pay_date <= date.today()
        IncomeService.sync_income_to_transaction(income)
        db.session.commit()
        return income

    @staticmethod
    def toggle_income_paid(income_id):
        income = family_get_or_404(Income, income_id)
        income.is_paid = not income.is_paid
        if income.transaction_id:
            transaction = family_get(Transaction, income.transaction_id)
            if transaction:
                transaction.is_paid = income.is_paid
                transaction.is_forecasted = not income.is_paid and income.pay_date > date.today()
        db.session.commit()
        # Folded expenses are only "reimbursed" once the payslip is actually paid
        IncomeService._sync_folded_expenses(income)
        return income

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    @staticmethod
    def _income_category_id(income):
        if income.recurring_income_id and income.recurring_income and income.recurring_income.category_id:
            return income.recurring_income.category_id
        salary_category = family_query(Category).filter(
            Category.name == 'Salary', func.lower(Category.category_type) == 'income'
        ).first()
        if not salary_category:
            salary_category = Category(
                family_id=db_helpers.get_family_id(), name='Salary',
                head_budget='Income', sub_budget='Salary', category_type='income',
            )
            db.session.add(salary_category)
            db.session.flush()
        return salary_category.id

    @staticmethod
    def _stamp_transaction_dates(transaction, pay_date):
        transaction.transaction_date = pay_date
        transaction.payday_period = PaydayService.get_period_for_date(pay_date)
        transaction.year_month = f"{pay_date.year}-{pay_date.month:02d}"
        transaction.week_year = f"{pay_date.isocalendar()[1]:02d}-{pay_date.year}"
        transaction.day_name = pay_date.strftime('%a')

    @staticmethod
    def create_income_transaction(income, recalculate_balance=True):
        """
        Create a bank Transaction for the take-home amount of an Income record.

        Future income (pay_date > today) is created with is_paid=False,
        is_forecasted=True; past/present income is is_paid=True, is_forecasted=False.
        """
        is_future = income.pay_date > date.today()
        transaction = Transaction(
            family_id=db_helpers.get_family_id(),
            account_id=income.deposit_account_id,
            category_id=IncomeService._income_category_id(income),
            amount=income.take_home + (income.expense_reimbursement_total or Decimal('0')),
            description=f"{income.person} Salary",
            item=f"Take home: £{income.take_home:,.2f}",
            payment_type='BACS',
            is_paid=not is_future,
            is_forecasted=is_future,
        )
        IncomeService._stamp_transaction_dates(transaction, income.pay_date)
        db.session.add(transaction)
        db.session.flush()
        if recalculate_balance:
            Transaction.recalculate_account_balance(income.deposit_account_id)
        return transaction

    @staticmethod
    def sync_income_to_transaction(income):
        """
        Propagate edits from an Income record to its linked bank Transaction.
        Flushes but does NOT commit — the caller owns the transaction boundary.
        """
        if not income.transaction_id:
            return None
        transaction = family_get(Transaction, income.transaction_id)
        if not transaction:
            return None
        IncomeService._validate_family_references(deposit_account_id=income.deposit_account_id)
        old_account_id = transaction.account_id
        IncomeService._fill_transaction(transaction, income)

        db.session.flush()
        IncomeService._sync_folded_expenses(income)
        IncomeService._recalculate_balances([old_account_id, transaction.account_id])
        return transaction

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    @staticmethod
    def get_income_summary(person=None, year=None):
        """Get income summary statistics"""
        query = family_query(Income)
        if person:
            query = query.filter_by(person=person)
        if year:
            query = query.filter(db.func.extract('year', Income.pay_date) == year)
        incomes = query.order_by(Income.pay_date.desc()).all()

        if not incomes:
            return {
                'records': [], 'count': 0, 'total_gross': 0, 'total_take_home': 0,
                'total_tax': 0, 'total_ni': 0, 'total_pension': 0,
                'avg_gross': 0, 'avg_take_home': 0,
            }

        def total(attr):
            return sum(float(getattr(i, attr) or 0) for i in incomes)

        total_gross = total('gross_monthly_income')
        total_take_home = total('take_home')
        return {
            'records': incomes,
            'count': len(incomes),
            'total_gross': total_gross,
            'total_take_home': total_take_home,
            'total_tax': total('income_tax'),
            'total_ni': total('national_insurance'),
            'total_pension': total('total_pension'),
            'avg_gross': total_gross / len(incomes),
            'avg_take_home': total_take_home / len(incomes),
        }

    # ------------------------------------------------------------------
    # Generation from templates
    # ------------------------------------------------------------------

    @staticmethod
    def forecast_horizon(today=None):
        """Forecast rows are saved up to this date; the plan projects beyond it."""
        return (today or date.today()) + relativedelta(months=FORECAST_HORIZON_MONTHS)

    @staticmethod
    def pay_date_for_month(recurring_income, target_date):
        """Monthly pay date for the template in *target_date*'s month, moved back
        to the previous working day if it falls on a weekend or bank holiday."""
        return income_schedule.monthly_pay_date(recurring_income.pay_day, target_date.year, target_date.month)

    @staticmethod
    def _existing_income_for(recurring_income, pay_date):
        # Match on the template, so two jobs paid on the same day don't collide.
        # Legacy rows created before recurring_income_id existed are matched by
        # person + employer instead.
        return family_query(Income).filter(
            Income.pay_date == pay_date,
            or_(
                Income.recurring_income_id == recurring_income.id,
                and_(
                    Income.recurring_income_id.is_(None),
                    Income.person == recurring_income.person,
                    Income.source == recurring_income.source,
                ),
            ),
        ).first()

    @staticmethod
    def _changes_for(recurring):
        return family_query(IncomeChange).filter(
            IncomeChange.recurring_income_id == recurring.id
        ).order_by(IncomeChange.effective_date, IncomeChange.id).all()

    @staticmethod
    def uses_fixed_figures(recurring):
        """Legacy templates with typed-in monthly deductions keep those figures
        for every forecast; pay rises, bonuses and the timeline don't apply."""
        return bool(recurring.use_manual_deductions and recurring.manual_take_home)

    @staticmethod
    def _apply_fixed_figures(income, recurring):
        def d(value):
            return Decimal(str(value or 0))

        gross_annual = d(recurring.gross_annual_income)
        gross = (gross_annual / 12).quantize(Decimal('0.01'))
        employer, employee = d(recurring.manual_employer_pension), d(recurring.manual_employee_pension)
        income.tax_year = payroll_calculator.tax_year_for(income.pay_date)
        income.tax_code = recurring.tax_code
        income.pay_frequency = 'monthly'
        income.gross_annual_income = gross_annual
        income.gross_monthly_income = gross
        income.bonus = None
        income.student_loan = None
        income.employer_pension_percent = Decimal('0')
        income.employee_pension_percent = Decimal('0')
        income.employer_pension_amount = employer
        income.employee_pension_amount = employee
        income.total_pension = employer + employee
        income.adjusted_monthly_income = gross - employee
        income.adjusted_annual_income = gross_annual - employee * 12
        income.income_tax = d(recurring.manual_tax_monthly)
        income.national_insurance = d(recurring.manual_ni_monthly)
        income.avc = d(recurring.avc)
        income.other_deductions = d(recurring.other_deductions)
        income.take_home = d(recurring.manual_take_home)
        income.estimated_annual_take_home = (income.take_home * 12).quantize(Decimal('0.01'))

    @staticmethod
    def _price_forecast(income, recurring, changes, previous, settings_cache):
        """(Re)calculate a forecast row from the source's terms on its pay date."""
        if IncomeService.uses_fixed_figures(recurring):
            IncomeService._apply_fixed_figures(income, recurring)
        else:
            terms = income_schedule.terms_for(recurring, changes, income.pay_date, previous)
            year = payroll_calculator.tax_year_start(income.pay_date)
            if year not in settings_cache:
                settings_cache[year] = IncomeService.get_tax_settings_for_date(income.pay_date)
            estimate = income_schedule.estimate(recurring, terms, income.pay_date, settings_cache[year])
            IncomeService._apply_estimate(income, estimate)
            income.tax_code = terms.tax_code
            income.employee_pension_percent = terms.employee_pension_pct
            income.employer_pension_percent = terms.employer_pension_pct
        # A forecast, not an actual payslip; set when the real payslip is entered.
        income.is_manual_override = False

    @staticmethod
    def _create_forecast(recurring, changes, pay_date, previous, settings_cache):
        income = Income(
            family_id=recurring.family_id or db_helpers.get_family_id(),
            person=recurring.person,
            pay_date=pay_date,
            deposit_account_id=recurring.deposit_account_id,
            source=recurring.source,
            recurring_income_id=recurring.id,
            owner_id=recurring.owner_id,
        )
        IncomeService._price_forecast(income, recurring, changes, previous, settings_cache)
        db.session.add(income)
        db.session.flush()
        if recurring.auto_create_transaction and income.deposit_account_id:
            income.transaction_id = IncomeService.create_income_transaction(income, recalculate_balance=False).id
        return income

    @staticmethod
    def _generation_start(recurring):
        last = recurring.last_generated_date
        if last is None:
            return recurring.start_date
        if income_schedule.frequency_of(recurring) == 'monthly':
            # Monthly templates record the last month processed (1st of month).
            return last.replace(day=1) + relativedelta(months=1)
        return last + timedelta(days=1)

    @staticmethod
    def _generation_limit(recurring, end_date=None):
        limit = IncomeService.forecast_horizon()
        if end_date is not None:
            limit = min(limit, end_date)
        if income_schedule.frequency_of(recurring) == 'monthly':
            limit = limit.replace(day=calendar.monthrange(limit.year, limit.month)[1])
        return limit

    @staticmethod
    def _generated_marker(recurring, limit):
        if income_schedule.frequency_of(recurring) == 'monthly':
            return limit.replace(day=1)
        return limit

    @staticmethod
    def _generate_dates(recurring, dates):
        """Create forecasts for *dates* that have no row yet.
        Returns (rows for every date, number created)."""
        if not dates:
            return [], 0
        changes = IncomeService._changes_for(recurring)
        settings_cache = {}
        previous = income_schedule.previous_pay_date(recurring, dates[0])
        rows, created = [], 0
        for pay_date in dates:
            existing = IncomeService._existing_income_for(recurring, pay_date)
            if existing:
                rows.append(existing)
            else:
                rows.append(IncomeService._create_forecast(recurring, changes, pay_date, previous, settings_cache))
                created += 1
            previous = pay_date
        return rows, created

    @staticmethod
    def _finish_generation(recurring, created, extra_accounts=(), sync=True):
        db.session.flush()
        accounts = set(extra_accounts)
        if created and recurring.auto_create_transaction:
            accounts.add(recurring.deposit_account_id)
        IncomeService._recalculate_balances(accounts)
        db.session.commit()
        if sync:
            IncomeService._sync_folded_for(recurring.id)

    @staticmethod
    def generate_missing_income(recurring_income_id, end_date=None):
        """
        Fill in missing Income records for a source from where generation last
        stopped up to *end_date* (for monthly pay, the whole of that month),
        never beyond FORECAST_HORIZON_MONTHS from today or the source's end
        date. Idempotent.

        Returns the list of Income records (new or pre-existing) in the window.
        """
        recurring = family_get(RecurringIncome, recurring_income_id)
        if not recurring or not recurring.is_active:
            return []
        start = IncomeService._generation_start(recurring)
        limit = IncomeService._generation_limit(recurring, end_date)
        if limit < start:
            return []
        rows, created = IncomeService._generate_dates(recurring, income_schedule.pay_dates(recurring, start, limit))
        recurring.last_generated_date = IncomeService._generated_marker(recurring, limit)
        IncomeService._finish_generation(recurring, created, sync=bool(rows))
        return rows

    @staticmethod
    def _fill_transaction(transaction, income):
        transaction.amount = income.take_home + (income.expense_reimbursement_total or Decimal('0'))
        transaction.description = f"{income.person} Salary"
        transaction.item = f"Take home: £{income.take_home:,.2f}"
        transaction.account_id = income.deposit_account_id
        transaction.category_id = IncomeService._income_category_id(income)
        IncomeService._stamp_transaction_dates(transaction, income.pay_date)
        transaction.is_paid = income.is_paid
        transaction.is_forecasted = not income.is_paid and income.pay_date > date.today()

    @staticmethod
    def _remove_forecast(income, txn, affected_accounts):
        from services.finance.expense_sync_service import ExpenseSyncService

        ExpenseSyncService.unlink_expenses_from_income(income.id)
        if txn:
            income.transaction_id = None
            db.session.flush()
            affected_accounts.add(txn.account_id)
            db.session.delete(txn)
        db.session.delete(income)

    @staticmethod
    def refresh_forecasts(recurring_income_id):
        """
        Bring a source's saved future forecasts in line with its current terms
        and timeline. Unsettled forecasts dated after today are re-priced in
        place (keeping their transactions and expense links), removed when no
        longer on the schedule, and missing pay dates up to the horizon are
        added. Settled rows (paid / actual payslip entered) are never touched.
        """
        recurring = family_get(RecurringIncome, recurring_income_id)
        if not recurring:
            raise ValueError('Income source not found.')
        today = date.today()
        limit = IncomeService._generation_limit(recurring)
        wanted = income_schedule.pay_dates(recurring, today + timedelta(days=1), limit) if recurring.is_active else []
        previous_of, previous = {}, (income_schedule.previous_pay_date(recurring, wanted[0]) if wanted else None)
        for pay_date in wanted:
            previous_of[pay_date] = previous
            previous = pay_date

        changes = IncomeService._changes_for(recurring)
        settings_cache = {}
        affected_accounts = set()
        covered = set()
        updated = removed = 0
        rows = family_query(Income).filter(
            Income.recurring_income_id == recurring.id, Income.pay_date > today,
        ).order_by(Income.pay_date, Income.id).all()
        for income in rows:
            txn = family_get(Transaction, income.transaction_id) if income.transaction_id else None
            if IncomeService._is_settled(income, txn):
                covered.add(income.pay_date)
                continue
            if income.pay_date not in previous_of or income.pay_date in covered:
                IncomeService._remove_forecast(income, txn, affected_accounts)
                removed += 1
                continue
            covered.add(income.pay_date)
            income.person = recurring.person
            income.source = recurring.source
            income.owner_id = recurring.owner_id
            income.deposit_account_id = recurring.deposit_account_id
            IncomeService._price_forecast(income, recurring, changes, previous_of[income.pay_date], settings_cache)
            if recurring.auto_create_transaction and income.deposit_account_id:
                if txn:
                    affected_accounts.add(txn.account_id)
                    IncomeService._fill_transaction(txn, income)
                else:
                    income.transaction_id = IncomeService.create_income_transaction(
                        income, recalculate_balance=False).id
                affected_accounts.add(income.deposit_account_id)
            elif txn:
                income.transaction_id = None
                db.session.flush()
                affected_accounts.add(txn.account_id)
                db.session.delete(txn)
            updated += 1

        db.session.flush()
        _, created = IncomeService._generate_dates(recurring, [d for d in wanted if d not in covered])
        marker = IncomeService._generated_marker(recurring, limit)
        if recurring.last_generated_date and recurring.last_generated_date > marker:
            recurring.last_generated_date = marker
        IncomeService._finish_generation(recurring, created, affected_accounts)
        return {'updated': updated, 'removed': removed, 'added': created}

    @staticmethod
    def refresh_all_forecasts():
        """refresh_forecasts() for every visible source; one bad source doesn't block the rest."""
        from flask import current_app

        totals = {'updated': 0, 'removed': 0, 'added': 0, 'failed': 0}
        for recurring_id, in family_query(RecurringIncome).with_entities(RecurringIncome.id).all():
            try:
                result = IncomeService.refresh_forecasts(recurring_id)
            except ValueError:
                db.session.rollback()
                totals['failed'] += 1
                current_app.logger.warning('Forecast refresh failed for recurring_income_id=%s', recurring_id, exc_info=True)
                continue
            for key in ('updated', 'removed', 'added'):
                totals[key] += result[key]
        return totals

    @staticmethod
    def generate_all_missing_income(end_date=None):
        """Generate missing income for all active recurring income templates"""
        from flask import current_app

        all_generated = []
        for recurring_id, in family_query(RecurringIncome).filter_by(is_active=True).with_entities(RecurringIncome.id).all():
            try:
                all_generated.extend(IncomeService.generate_missing_income(recurring_id, end_date))
            except ValueError:
                # One bad template (e.g. an unparseable legacy tax code) mustn't block the rest.
                db.session.rollback()
                current_app.logger.warning(
                    'Skipped income generation for recurring_income_id=%s', recurring_id, exc_info=True
                )
        return all_generated

    @staticmethod
    def trim_future_forecasts(months_ahead=13):
        """
        Delete unsettled forecast Income records (and their linked transactions)
        generated from templates whose pay_date is more than *months_ahead* months
        from today, then reset each template's last_generated_date to the latest
        record kept.
        """
        from services.finance.expense_sync_service import ExpenseSyncService

        try:
            months_ahead = int(months_ahead)
        except (TypeError, ValueError):
            raise ValueError('Months ahead must be a whole number.')
        if not 1 <= months_ahead <= 12 * GENERATION_HORIZON_YEARS:
            raise ValueError(f'Months ahead must be between 1 and {12 * GENERATION_HORIZON_YEARS}.')

        cutoff = date.today().replace(day=1) + relativedelta(months=months_ahead + 1)
        candidates = family_query(Income).filter(
            Income.pay_date >= cutoff,
            Income.is_paid == False,  # noqa: E712
            Income.recurring_income_id.isnot(None),
        ).all()

        deleted_income = 0
        deleted_txn = 0
        affected_template_ids = set()
        affected_accounts = set()

        for income in candidates:
            txn = family_get(Transaction, income.transaction_id) if income.transaction_id else None
            if txn is not None and txn.is_paid:
                continue
            affected_template_ids.add(income.recurring_income_id)
            ExpenseSyncService.unlink_expenses_from_income(income.id)
            if txn:
                income.transaction_id = None
                db.session.flush()
                affected_accounts.add(txn.account_id)
                db.session.delete(txn)
                deleted_txn += 1
            db.session.delete(income)
            deleted_income += 1

        db.session.flush()
        for tpl_id in affected_template_ids:
            tpl = family_get(RecurringIncome, tpl_id)
            if not tpl:
                continue
            latest_kept = (
                family_query(Income).filter_by(recurring_income_id=tpl_id)
                .order_by(Income.pay_date.desc()).first()
            )
            tpl.last_generated_date = (
                IncomeService._generated_marker(tpl, latest_kept.pay_date) if latest_kept else None
            )

        IncomeService._recalculate_balances(affected_accounts)
        db.session.commit()
        return {'deleted': deleted_income, 'transactions': deleted_txn}

    # ------------------------------------------------------------------
    # Range operations
    # ------------------------------------------------------------------

    @staticmethod
    def delete_income_range(recurring_income_id, start_date, end_date, force=False):
        """
        Delete a template's income records between *start_date* and *end_date*
        (inclusive).

        Unsettled records are removed together with their forecast transaction.
        Settled records (paid / actual payslip entered) are skipped unless *force*,
        in which case the record is removed but its paid bank transaction is kept.
        """
        from services.finance.expense_sync_service import ExpenseSyncService

        recurring = family_get(RecurringIncome, recurring_income_id)
        if not recurring:
            raise ValueError("Recurring income not found")
        IncomeService._validate_range(start_date, end_date)

        income_records = family_query(Income).filter(
            Income.recurring_income_id == recurring_income_id,
            Income.pay_date >= start_date,
            Income.pay_date <= end_date,
        ).all()

        deleted = 0
        skipped = []
        affected_accounts = set()

        for income in income_records:
            txn = family_get(Transaction, income.transaction_id) if income.transaction_id else None
            settled = IncomeService._is_settled(income, txn)
            if settled and not force:
                skipped.append({'date': income.pay_date, 'amount': income.take_home, 'is_paid': True})
                continue
            ExpenseSyncService.unlink_expenses_from_income(income.id)
            if income.transaction_id:
                income.transaction_id = None
                db.session.flush()
            if txn and not settled:
                affected_accounts.add(txn.account_id)
                db.session.delete(txn)
            db.session.delete(income)
            deleted += 1

        if deleted:
            if income_schedule.frequency_of(recurring) == 'monthly':
                resume_marker = start_date.replace(day=1) - relativedelta(months=1)
            else:
                resume_marker = start_date - timedelta(days=1)
            if recurring.last_generated_date is None or recurring.last_generated_date > resume_marker:
                recurring.last_generated_date = resume_marker

        db.session.flush()
        IncomeService._recalculate_balances(affected_accounts)
        db.session.commit()
        return {'deleted': deleted, 'skipped': len(skipped), 'skipped_records': skipped}

    @staticmethod
    def regenerate_income_range(recurring_income_id, start_date, end_date, force=False):
        """Delete and regenerate a template's income records for a date range."""
        delete_result = IncomeService.delete_income_range(recurring_income_id, start_date, end_date, force)
        generated = IncomeService.generate_missing_income(recurring_income_id, end_date=end_date)
        regenerated = [inc for inc in generated if start_date <= inc.pay_date <= end_date]
        return {
            'deleted': delete_result['deleted'],
            'skipped': delete_result['skipped'],
            'regenerated': len(regenerated),
            'skipped_records': delete_result['skipped_records'],
        }

    @staticmethod
    def end_job(recurring_income_id, last_pay_date):
        """
        End a job: set end_date, deactivate the template, and delete unsettled
        Income records after *last_pay_date* together with their transactions.
        """
        from services.finance.expense_sync_service import ExpenseSyncService

        recurring = family_get(RecurringIncome, recurring_income_id)
        if not recurring:
            raise ValueError("Recurring income not found")
        if last_pay_date < recurring.start_date:
            raise ValueError('Last pay date cannot be before the job start date.')

        recurring.end_date = last_pay_date
        recurring.is_active = False

        future_incomes = family_query(Income).filter(
            Income.recurring_income_id == recurring_income_id,
            Income.pay_date > last_pay_date,
        ).all()

        deleted = 0
        kept_paid = 0
        affected_accounts = set()
        for income in future_incomes:
            txn = family_get(Transaction, income.transaction_id) if income.transaction_id else None
            if IncomeService._is_history(income, txn):
                kept_paid += 1
                continue
            ExpenseSyncService.unlink_expenses_from_income(income.id)
            if txn:
                income.transaction_id = None
                db.session.flush()
                affected_accounts.add(txn.account_id)
                db.session.delete(txn)
            db.session.delete(income)
            deleted += 1

        db.session.flush()
        IncomeService._recalculate_balances(affected_accounts)
        db.session.commit()
        return {'deleted': deleted, 'kept_paid': kept_paid}

    @staticmethod
    def purge_orphaned_forecasts(dry_run=True, today=None, family_id=None):
        """
        Server-side maintenance (no logged-in household; every query is scoped
        by the row's own family_id). Removes future forecasts left behind when
        a template was deleted under older code, which deleted only the template
        and detached (recurring_income_id = NULL) its generated rows.

        A candidate is detached, unpaid, has no paid transaction and is dated
        after *today*. It is purged when it carries the legacy "actual" flag
        (old generator) or belongs to a series of ORPHAN_SERIES_MIN or more
        such rows for the same family/person/source (a lone future one-off is
        left alone). Only transactions linked to purged rows are deleted.

        Returns a list of dicts grouped by family/person/source.
        """
        from models.expenses import Expense

        today = today or date.today()
        query = (
            Income.query.outerjoin(Transaction, Transaction.id == Income.transaction_id)
            .filter(
                Income.recurring_income_id.is_(None),
                or_(Income.is_paid.is_(False), Income.is_paid.is_(None)),
                or_(Transaction.id.is_(None), Transaction.is_paid.isnot(True)),
                Income.pay_date > today,
            )
        )
        if family_id is not None:
            query = query.filter(Income.family_id == family_id)
        candidates = query.order_by(
            Income.family_id, Income.person, Income.source, Income.pay_date
        ).all()

        series = {}
        for income in candidates:
            series.setdefault((income.family_id, income.person, income.source), []).append(income)

        groups, doomed = [], []
        for (fam, person, source), rows in series.items():
            flagged = [r for r in rows if r.is_manual_override]
            chosen = rows if len(rows) >= ORPHAN_SERIES_MIN else flagged
            if not chosen:
                continue
            doomed.extend(chosen)
            groups.append({
                'family_id': fam, 'person': person, 'source': source, 'count': len(chosen),
                'first': chosen[0].pay_date, 'last': chosen[-1].pay_date,
                'with_transactions': sum(1 for r in chosen if r.transaction_id),
            })

        if dry_run:
            return groups

        affected_accounts = set()
        for income in doomed:
            Expense.query.filter(
                Expense.family_id == income.family_id, Expense.income_id == income.id,
            ).update({'income_id': None, 'claim_group': None, 'reimbursed': False},
                     synchronize_session=False)
            txn = None
            if income.transaction_id:
                txn = Transaction.query.filter_by(
                    id=income.transaction_id, family_id=income.family_id,
                ).first()
                income.transaction_id = None
                db.session.flush()
            if txn:
                affected_accounts.add(txn.account_id)
                db.session.delete(txn)
            db.session.delete(income)

        db.session.flush()
        IncomeService._recalculate_balances(affected_accounts)
        db.session.commit()
        return groups
