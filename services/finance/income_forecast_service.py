"""Generation and maintenance of recurring-income forecasts."""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import and_, or_

from extensions import db
from models.income import Income
from models.income_change import IncomeChange
from models.recurring_income import RecurringIncome
from models.transactions import Transaction
from services.finance import income_schedule, payroll_calculator
from services.finance.balance_service import BalanceService
from services.finance.income_service import IncomeService
from utils import db_helpers
from utils.db_helpers import family_get, family_query

DEFAULT_FORECAST_YEARS = 5
MAX_FORECAST_YEARS = 10
FORECAST_YEARS_SETTING = 'income.forecast_years'
GENERATION_HORIZON_YEARS = 50
MAX_RANGE_YEARS = 50
ORPHAN_SERIES_MIN = 3


class IncomeForecastService:
    """Create, refresh and retire saved future payslip forecasts."""

    @staticmethod
    def forecast_years():
        """Household setting: how many years ahead forecast payslips are saved."""
        from models.settings import Settings
        try:
            years = int(Settings.get_value(FORECAST_YEARS_SETTING, DEFAULT_FORECAST_YEARS))
        except (TypeError, ValueError):
            return DEFAULT_FORECAST_YEARS
        return min(max(years, 1), MAX_FORECAST_YEARS)

    @staticmethod
    def set_forecast_years(value):
        """Save the forecast horizon; call refresh_all_forecasts() afterwards to apply it."""
        from models.settings import Settings
        try:
            years = int(value)
        except (TypeError, ValueError):
            raise ValueError('Choose how many years of forecasts to keep.') from None
        if not 1 <= years <= MAX_FORECAST_YEARS:
            raise ValueError(f'Forecasts can be kept from 1 to {MAX_FORECAST_YEARS} years ahead.')
        Settings.set_value(FORECAST_YEARS_SETTING, years,
                           'Years ahead that income payslips are forecast', 'int')
        db.session.commit()
        return years

    @staticmethod
    def forecast_horizon(today=None):
        """Forecast rows are saved up to this date; the plan projects beyond it."""
        return (today or date.today()) + relativedelta(years=IncomeForecastService.forecast_years())

    @staticmethod
    def _validate_range(start_date, end_date):
        if end_date < start_date:
            raise ValueError('End date cannot be before the start date.')
        if end_date > start_date + relativedelta(years=MAX_RANGE_YEARS):
            raise ValueError(f'Date range cannot be longer than {MAX_RANGE_YEARS} years.')

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
        if IncomeForecastService.uses_fixed_figures(recurring):
            IncomeForecastService._apply_fixed_figures(income, recurring)
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
            member_id=recurring.member_id,
            pay_date=pay_date,
            deposit_account_id=recurring.deposit_account_id,
            source=recurring.source,
            recurring_income_id=recurring.id,
            owner_id=recurring.owner_id,
        )
        IncomeForecastService._price_forecast(income, recurring, changes, previous, settings_cache)
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
        limit = IncomeForecastService.forecast_horizon()
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
        changes = IncomeForecastService._changes_for(recurring)
        settings_cache = {}
        previous = income_schedule.previous_pay_date(recurring, dates[0])
        rows, created = [], 0
        for pay_date in dates:
            existing = IncomeForecastService._existing_income_for(recurring, pay_date)
            if existing:
                rows.append(existing)
            else:
                rows.append(IncomeForecastService._create_forecast(recurring, changes, pay_date, previous, settings_cache))
                created += 1
            previous = pay_date
        return rows, created

    @staticmethod
    def _finish_generation(recurring, created, extra_accounts=(), sync=True):
        db.session.flush()
        accounts = set(extra_accounts)
        if created and recurring.auto_create_transaction:
            accounts.add(recurring.deposit_account_id)
        BalanceService.recalculate(account_ids=accounts, commit=False)
        db.session.commit()
        if sync:
            IncomeService._sync_folded_for(recurring.id)

    @staticmethod
    def generate_missing_income(recurring_income_id, end_date=None):
        """
        Fill in missing Income records for a source from where generation last
        stopped up to *end_date* (for monthly pay, the whole of that month),
        never beyond the household's forecast horizon or the source's end
        date. Idempotent.

        Returns the list of Income records (new or pre-existing) in the window.
        """
        recurring = family_get(RecurringIncome, recurring_income_id)
        if not recurring or not recurring.is_active:
            return []
        start = IncomeForecastService._generation_start(recurring)
        limit = IncomeForecastService._generation_limit(recurring, end_date)
        if limit < start:
            return []
        rows, created = IncomeForecastService._generate_dates(recurring, income_schedule.pay_dates(recurring, start, limit))
        recurring.last_generated_date = IncomeForecastService._generated_marker(recurring, limit)
        IncomeForecastService._finish_generation(recurring, created, sync=bool(rows))
        return rows

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
        limit = IncomeForecastService._generation_limit(recurring)
        wanted = income_schedule.pay_dates(recurring, today + timedelta(days=1), limit) if recurring.is_active else []
        previous_of, previous = {}, (income_schedule.previous_pay_date(recurring, wanted[0]) if wanted else None)
        for pay_date in wanted:
            previous_of[pay_date] = previous
            previous = pay_date

        changes = IncomeForecastService._changes_for(recurring)
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
                IncomeForecastService._remove_forecast(income, txn, affected_accounts)
                removed += 1
                continue
            covered.add(income.pay_date)
            income.person = recurring.person
            income.member_id = recurring.member_id
            income.source = recurring.source
            income.owner_id = recurring.owner_id
            income.deposit_account_id = recurring.deposit_account_id
            IncomeForecastService._price_forecast(income, recurring, changes, previous_of[income.pay_date], settings_cache)
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
        _, created = IncomeForecastService._generate_dates(recurring, [d for d in wanted if d not in covered])
        marker = IncomeForecastService._generated_marker(recurring, limit)
        if recurring.last_generated_date and recurring.last_generated_date > marker:
            recurring.last_generated_date = marker
        IncomeForecastService._finish_generation(recurring, created, affected_accounts)
        return {'updated': updated, 'removed': removed, 'added': created}

    @staticmethod
    def refresh_all_forecasts():
        """refresh_forecasts() for every visible source; one bad source doesn't block the rest."""
        from flask import current_app

        totals = {'updated': 0, 'removed': 0, 'added': 0, 'failed': 0}
        for recurring_id, in family_query(RecurringIncome).with_entities(RecurringIncome.id).all():
            try:
                result = IncomeForecastService.refresh_forecasts(recurring_id)
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
                all_generated.extend(IncomeForecastService.generate_missing_income(recurring_id, end_date))
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
                IncomeForecastService._generated_marker(tpl, latest_kept.pay_date) if latest_kept else None
            )

        BalanceService.recalculate(account_ids=affected_accounts, commit=False)
        db.session.commit()
        return {'deleted': deleted_income, 'transactions': deleted_txn}

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
        IncomeForecastService._validate_range(start_date, end_date)

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
        BalanceService.recalculate(account_ids=affected_accounts, commit=False)
        db.session.commit()
        return {'deleted': deleted, 'skipped': len(skipped), 'skipped_records': skipped}

    @staticmethod
    def regenerate_income_range(recurring_income_id, start_date, end_date, force=False):
        """Delete and regenerate a template's income records for a date range."""
        delete_result = IncomeForecastService.delete_income_range(recurring_income_id, start_date, end_date, force)
        generated = IncomeForecastService.generate_missing_income(
            recurring_income_id, end_date=end_date
        )
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
        BalanceService.recalculate(account_ids=affected_accounts, commit=False)
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
        BalanceService.recalculate(account_ids=affected_accounts, commit=False)
        db.session.commit()
        return groups
