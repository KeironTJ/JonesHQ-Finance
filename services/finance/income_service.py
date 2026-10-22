"""
Income Service
==============
Income record management: payslip estimation, actual-payslip entry, transaction
creation and recurring-income source management. Saved forecast generation is
handled by ``IncomeForecastService``.

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
  sync_income_to_transaction()  — propagate income edits to the linked transaction
"""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dateutil.relativedelta import relativedelta
from sqlalchemy import func

from extensions import db
from models.accounts import Account
from models.categories import Category
from models.income import Income
from models.income_change import IncomeChange
from models.pensions import Pension
from models.recurring_income import RecurringIncome
from models.tax_settings import TaxSettings
from models.transactions import Transaction
from services.finance import payroll_calculator
from services.finance.payday_service import PaydayService
from utils import db_helpers
from utils.db_helpers import family_get, family_get_or_404, family_query
from services.household.member_identity_service import MemberIdentityService

_MEMBER_UNSET = object()

MAX_MONEY = Decimal('99999999.99')  # Numeric(10, 2) ceiling
MAX_TEMPLATE_YEARS = 60             # Longest a single job template may run
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

    # ------------------------------------------------------------------
    # Privacy
    # ------------------------------------------------------------------

    @staticmethod
    def _member_id_for(person):
        """User id of the household member whose name is *person* (member name or
        account name, case-insensitive), or None if it isn't exactly one member."""
        return MemberIdentityService.member_id_for(person)

    @staticmethod
    def sync_member_link(member, family_id, previous_names=()):
        """Link *member* to income recorded under their name(s) and keep `person`
        on their linked income in step with their current display name.

        Called when someone joins the household or a member is renamed. Names
        shared with another member are never auto-linked."""
        from models.users import User

        display = (member.member_name or member.name or '').strip()[:50]
        if not family_id or not display:
            return
        keys = {(name or '').strip().lower() for name in (member.member_name, member.name, *previous_names)} - {''}
        for other in User.query.filter(User.family_id == family_id, User.id != member.id).all():
            keys -= {(other.member_name or '').strip().lower(), (other.name or '').strip().lower()}
        from services.planning.retirement_service import RetirementService
        RetirementService.link_legacy(member, family_id, keys)
        for model in (RecurringIncome, Income, Pension):
            if keys:
                model.query.filter(
                    model.family_id == family_id,
                    model.member_id.is_(None),
                    func.lower(func.trim(model.person)).in_(keys),
                ).update({'member_id': member.id}, synchronize_session=False)
            model.query.filter(model.family_id == family_id, model.member_id == member.id).update(
                {'person': display}, synchronize_session=False)

    @staticmethod
    def unlink_member(member_id, family_id):
        """Detach a departing member from the household's income; names are kept."""
        for model in (RecurringIncome, Income, Pension):
            model.query.filter(model.family_id == family_id, model.member_id == member_id).update(
                {'member_id': None}, synchronize_session=False)

    @staticmethod
    def _may_make_private(person, member_id=None):
        """
        Making income private hides it from the rest of the household, so only the
        person it belongs to may do that. For income not tied to a household
        member (e.g. 'Household'), the household owner may.
        """
        from models.users import User

        uid = db_helpers.get_current_user_id()
        user = db.session.get(User, uid) if uid else None
        if user is None:
            return False
        if member_id is not None:
            return member_id == user.id
        person_key = (person or '').strip().lower()
        member_names = set()
        for member in family_query(User).all():
            member_names |= {(member.member_name or '').strip().lower(), (member.name or '').strip().lower()}
        matched_member = IncomeService._member_id_for(person)
        return matched_member == uid or (person_key not in member_names and user.is_household_owner)

    @staticmethod
    def _resolve_owner_id(data, person, record=None, member_id=None):
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
        if record is not None:
            check_person, check_member = record.person, record.member_id
        else:
            check_person, check_member = person, member_id
        if not IncomeService._may_make_private(check_person, check_member):
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

        person, member_id = MemberIdentityService.resolve(data, recurring if recurring.id else None)
        recurring.owner_id = IncomeService._resolve_owner_id(
            data, person, record=recurring if recurring.id else None, member_id=member_id,
        )
        recurring.person = person
        recurring.member_id = member_id
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
        if pension_id is not None:
            pension = family_get(Pension, pension_id)
            if pension is None:
                raise ValueError('Invalid pension selected')
            if member_id is not None and pension.member_id is not None and pension.member_id != member_id:
                raise ValueError('Choose a pension belonging to the same household member.')
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
        from services.finance.income_forecast_service import IncomeForecastService
        IncomeForecastService.refresh_forecasts(recurring.id)
        return recurring

    @staticmethod
    def save_income_source(data, recurring_id=None):
        """Create or update a source and bring its saved forecasts up to date."""
        if recurring_id is None:
            recurring = IncomeService.create_recurring_income(data)
            from services.finance.income_forecast_service import IncomeForecastService
            IncomeForecastService.generate_missing_income(recurring.id)
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
        from services.finance.income_forecast_service import IncomeForecastService
        IncomeForecastService.refresh_forecasts(recurring.id)
        return change

    @staticmethod
    def delete_income_change(change_id):
        change = family_get_or_404(IncomeChange, change_id)
        recurring_id = change.recurring_income_id
        db.session.delete(change)
        db.session.commit()
        from services.finance.income_forecast_service import IncomeForecastService
        IncomeForecastService.refresh_forecasts(recurring_id)
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
                             commit=True, member_id=_MEMBER_UNSET):
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
            member_id=IncomeService._member_id_for(person) if member_id is _MEMBER_UNSET else member_id,
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
                                    recalculate_balance=True, commit=True, member_id=_MEMBER_UNSET):
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
            member_id=IncomeService._member_id_for(person) if member_id is _MEMBER_UNSET else member_id,
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
        person, member_id = MemberIdentityService.resolve(data)
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
            owner_id=IncomeService._resolve_owner_id(data, person, member_id=member_id),
            member_id=member_id,
        )

    @staticmethod
    def update_income_record(income_id, data):
        """Edit an income record in calculated or manual (actual payslip) mode."""
        income = family_get_or_404(Income, income_id)
        mode = data.get('edit_mode', 'calculated')
        deposit_account_id = IncomeService._int_id(data, 'deposit_account_id', 'deposit account')
        IncomeService._validate_family_references(deposit_account_id=deposit_account_id)

        person, member_id = MemberIdentityService.resolve(data, income)
        income.owner_id = IncomeService._resolve_owner_id(data, person, record=income)
        income.member_id = member_id
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
    # Range operations
    # ------------------------------------------------------------------
