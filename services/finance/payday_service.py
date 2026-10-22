"""
Payday Service
==============
Period and balance calculations for the payday-period budgeting model.

Payday period
-------------
A "payday period" runs from one payday to the day before the next.  The period
label is YYYY-MM (the year and month of the *start* payday, not the end date).
For example, if payday is the 15th, the January 2026 period runs 15 Jan → 14 Feb
and is labelled "2026-01".

Weekend / bank holiday adjustment
-----------------------------------
All working-day helpers (is_non_working_day, get_previous_working_day,
get_next_working_day) treat both weekends *and* England & Wales bank holidays
as non-working days.  Bank holiday data comes from the ``holidays`` package
and is cached per year to avoid repeated object creation.

  get_payday_for_month()        — shifts to the *previous* working day
  get_payment_date_for_month()  — shifts to the *next* working day

Primary entry points
--------------------
  get_period_for_date()         — map any date → YYYY-MM period label
  get_payday_period()           — start/end/label for a given year+month
  get_recent_periods()          — list of periods for a filter dropdown
  get_payday_summary_for_year() — forecast balances and categories for one year
  change_payday_and_reperiod()  — validate payday and update stored period labels
"""
from datetime import date, timedelta
from decimal import Decimal
import holidays as holidays_lib
from models.transactions import Transaction
from models.settings import Settings
from extensions import db
from utils import db_helpers
from utils.db_helpers import family_query

# Module-level cache: year -> set of bank holiday dates (England & Wales)
_bank_holiday_cache: dict[int, set] = {}


class PaydayService:
    """
    Calculations for payday-period budgeting.

    The payday day is read from Settings ('payday_day', default 15).  All date
    arithmetic handles month-length edge cases (e.g. payday=31 in a 28-day month
    clamps to the last day of that month).
    """
    
    @staticmethod
    def get_payday_setting():
        """Get the payday from settings (day of month, 1-31)."""
        day = Settings.get_value('payday_day', 15)
        # Older versions could save 0 to mean "last day"; 31 is clamped to each month's end.
        if day == 0:
            return 31
        if not 1 <= day <= 31:
            raise ValueError('Payday must be a day between 1 and 31.')
        return day

    # ------------------------------------------------------------------
    # Bank holiday helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_bank_holidays(year: int) -> set:
        """Return the set of England & Wales bank holiday dates for *year*.

        Results are cached in _bank_holiday_cache so that repeated calls
        within the same process do not re-create the holidays object.
        """
        if year not in _bank_holiday_cache:
            _bank_holiday_cache[year] = set(
                holidays_lib.country_holidays('GB', subdiv='ENG', years=year).keys()
            )
        return _bank_holiday_cache[year]

    @staticmethod
    def is_bank_holiday(date_obj: date) -> bool:
        """Return True if *date_obj* is an England & Wales bank holiday."""
        return date_obj in PaydayService._get_bank_holidays(date_obj.year)

    @staticmethod
    def is_weekend(date_obj: date) -> bool:
        """Return True if *date_obj* falls on a Saturday or Sunday."""
        return date_obj.weekday() >= 5

    @staticmethod
    def is_non_working_day(date_obj: date) -> bool:
        """Return True if *date_obj* is a weekend OR a bank holiday."""
        return PaydayService.is_weekend(date_obj) or PaydayService.is_bank_holiday(date_obj)

    @staticmethod
    def get_previous_working_day(date_obj: date) -> date:
        """Shift *date_obj* backwards until it lands on a working day.

        A working day is any day that is neither a weekend nor an England &
        Wales bank holiday.
        """
        while PaydayService.is_non_working_day(date_obj):
            date_obj = date_obj - timedelta(days=1)
        return date_obj

    @staticmethod
    def get_next_working_day(date_obj: date) -> date:
        """Shift *date_obj* forwards until it lands on a working day.

        A working day is any day that is neither a weekend nor an England &
        Wales bank holiday.
        """
        while PaydayService.is_non_working_day(date_obj):
            date_obj = date_obj + timedelta(days=1)
        return date_obj
    
    @staticmethod
    def get_payday_for_month(year, month):
        """
        Get the actual payday for a given month, accounting for weekends.
        If the payday falls on a weekend, return the previous working day.
        """
        payday_day = PaydayService.get_payday_setting()
        
        # Handle months with fewer days
        import calendar
        max_day = calendar.monthrange(year, month)[1]
        actual_day = min(payday_day, max_day)
        
        payday = date(year, month, actual_day)
        
        # Adjust if weekend
        return PaydayService.get_previous_working_day(payday)
    
    @staticmethod
    def get_payment_date_for_month(year, month, payment_day):
        """
        Get the actual payment date for a given month and day, accounting for weekends.
        If the payment day falls on a weekend, return the next working day.
        
        Args:
            year: Year
            month: Month (1-12)
            payment_day: Day of month (1-31)
            
        Returns:
            date object adjusted to working day
        """
        # Handle months with fewer days
        import calendar
        max_day = calendar.monthrange(year, month)[1]
        actual_day = min(payment_day, max_day)
        
        payment_date = date(year, month, actual_day)
        
        # Adjust if weekend - move to next working day
        return PaydayService.get_next_working_day(payment_date)
    
    @staticmethod
    def get_payday_period(year, month):
        """
        Get the start and end dates for a payday period.
        E.g., if payday is 15th, January period = 15 Jan to 14 Feb
        
        Returns: (start_date, end_date, period_label)
        """
        # Start date is payday of this month
        start_date = PaydayService.get_payday_for_month(year, month)
        
        # End date is day before next month's payday
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1
        
        next_payday = PaydayService.get_payday_for_month(next_year, next_month)
        end_date = next_payday - timedelta(days=1)
        
        # Period label (e.g., "2026-01" for January payday period)
        period_label = f"{year:04d}-{month:02d}"
        
        return start_date, end_date, period_label
    
    @staticmethod
    def get_payday_periods(start_year, start_month, num_periods=12):
        """
        Get a list of payday periods.
        
        Args:
            start_year: Starting year
            start_month: Starting month
            num_periods: Number of periods to generate
            
        Returns:
            List of tuples: (start_date, end_date, period_label)
        """
        periods = []
        current_year = start_year
        current_month = start_month
        
        for _ in range(num_periods):
            period = PaydayService.get_payday_period(current_year, current_month)
            periods.append(period)
            
            # Move to next month
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1
        
        return periods
    
    @staticmethod
    def get_period_for_date(target_date):
        """
        Get the payday period label for a given transaction date.
        
        Args:
            target_date: The date to find the payday period for
            
        Returns:
            period_label (e.g., "2026-01") or None if cannot determine
        """
        if not target_date:
            return None
        
        # Search backwards from target_date to find which period it belongs to
        # Start with the year/month of the target date
        search_year = target_date.year
        search_month = target_date.month
        
        # Check current month and previous 2 months (handles edge cases)
        for _ in range(3):
            start_date, end_date, period_label = PaydayService.get_payday_period(search_year, search_month)
            
            if start_date <= target_date <= end_date:
                return period_label
            
            # Move backwards one month
            search_month -= 1
            if search_month < 1:
                search_month = 12
                search_year -= 1
        
        # If we still haven't found it, just use the year-month of the transaction
        return f"{target_date.year:04d}-{target_date.month:02d}"
    
    @staticmethod
    def get_recent_periods(num_periods=24, include_future=True, start_year=None, start_month=None):
        """
        Get recent payday periods for filter dropdowns.
        
        Args:
            num_periods: Number of periods to return
            include_future: Whether to include future periods (ignored if start_year/month provided)
            start_year: Optional starting year (overrides include_future logic)
            start_month: Optional starting month (overrides include_future logic)
            
        Returns:
            List of dicts with period info for display
        """
        today = date.today()
        
        # If start year/month provided, use those
        if start_year and start_month:
            current_year = start_year
            current_month = start_month
        elif include_future:
            # Show current month + future months
            current_year = today.year
            current_month = today.month
        else:
            # Show past periods - go back num_periods months
            current_year = today.year
            current_month = today.month - num_periods + 1
            
            while current_month < 1:
                current_month += 12
                current_year -= 1
        
        periods = PaydayService.get_payday_periods(current_year, current_month, num_periods)
        
        # Format for display
        result = []
        for start_date, end_date, period_label in periods:
            # Create display name like "Jan 15 - Feb 14, 2026"
            display_name = f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d, %Y')}"
            
            result.append({
                'label': period_label,
                'start_date': start_date,
                'end_date': end_date,
                'display_name': display_name,
                'year': start_date.year  # For grouping
            })
        
        return result
    
    @staticmethod
    def get_payday_summary_for_year(account_id, year):
        """
        Get summary of all payday periods for a specific year.
        Optimised: loads all transactions once and computes all 12 periods in a single pass
        instead of issuing 12+ separate full-table scans.
        """
        from models.categories import Category

        # Build the 12 payday-period date ranges for the year
        periods = PaydayService.get_payday_periods(year, 1, num_periods=12)

        if not periods:
            return []

        # The earliest date we need a balance for is the day before the first period start
        first_period_start = periods[0][0]
        last_period_end   = periods[-1][1]
        history_cutoff    = first_period_start - timedelta(days=1)

        # ── Single query: all transactions for this account up to end of last period ──
        all_txns = (
            family_query(Transaction)
            .filter(
                Transaction.account_id == account_id,
                Transaction.transaction_date <= last_period_end,
            )
            .order_by(Transaction.transaction_date)
            .all()
        )

        # ── Single query: full category map (no per-transaction DB hits) ──
        category_map = {c.id: c for c in family_query(Category).all()}

        # Compute opening balance for the first period (cumulative up to history_cutoff)
        opening_balance = Decimal('0')
        for txn in all_txns:
            if txn.transaction_date <= history_cutoff:
                opening_balance += Decimal(str(txn.amount))

        # Bucket transactions into periods by date range
        period_txns = [[] for _ in periods]
        for txn in all_txns:
            if txn.transaction_date < first_period_start:
                continue
            for idx, (start, end, _) in enumerate(periods):
                if start <= txn.transaction_date <= end:
                    period_txns[idx].append(txn)
                    break

        # Build results, carrying the running balance forward across periods
        results = []
        running_balance = opening_balance

        for idx, (start_date, end_date, period_label) in enumerate(periods):
            txns = period_txns[idx]
            period_opening = running_balance

            # Rolling balance & minimum within the period
            current = period_opening
            min_balance = period_opening
            for txn in sorted(txns, key=lambda t: t.transaction_date):
                current += Decimal(str(txn.amount))
                if current < min_balance:
                    min_balance = current

            rolling_balance   = current
            max_extra_spend   = rolling_balance - period_opening
            running_balance   = rolling_balance  # carry forward

            # Category breakdown (uses pre-loaded category_map — no extra DB queries)
            income_totals  = {}
            expense_totals = {}
            uncategorized_income  = 0
            uncategorized_expense = 0

            for txn in txns:
                amount    = abs(float(txn.amount))
                is_income = txn.amount > 0
                category  = category_map.get(txn.category_id) if txn.category_id else None

                if category:
                    head   = category.head_budget or 'Uncategorized'
                    sub    = category.sub_budget  or 'General'
                    totals = income_totals if is_income else expense_totals
                    if head not in totals:
                        totals[head] = {'total': 0, 'subcategories': {}}
                    totals[head]['subcategories'].setdefault(sub, 0)
                    totals[head]['total']              += amount
                    totals[head]['subcategories'][sub] += amount
                else:
                    if is_income:
                        uncategorized_income  += amount
                    else:
                        uncategorized_expense += amount

            if uncategorized_income > 0:
                income_totals['Uncategorized'] = {'total': uncategorized_income,  'subcategories': {'No Category': uncategorized_income}}
            if uncategorized_expense > 0:
                expense_totals['Uncategorized'] = {'total': uncategorized_expense, 'subcategories': {'No Category': uncategorized_expense}}

            def _to_list(totals_dict):
                result = []
                for head, data in sorted(totals_dict.items(), key=lambda x: x[1]['total'], reverse=True):
                    subcats = [{'name': s, 'amount': a} for s, a in sorted(data['subcategories'].items(), key=lambda x: x[1], reverse=True)]
                    result.append({'category': head, 'total': data['total'], 'subcategories': subcats})
                return result

            results.append({
                'period_label':       period_label,
                'start_date':         start_date,
                'end_date':           end_date,
                'rolling_balance':    float(rolling_balance),
                'min_balance':        float(min_balance),
                'max_extra_spend':    float(max_extra_spend),
                'opening_balance':    float(period_opening),
                'category_breakdown': {'income': _to_list(income_totals), 'expenses': _to_list(expense_totals)},
            })

        return results

    @staticmethod
    def reperiod_all_transactions():
        """
        Re-calculate and update payday_period for every transaction in the family.

        Call this after the household payday_day setting has changed. The caller
        commits the setting and transaction updates together.

        Payday is household-wide, so this deliberately includes transactions on
        other members' private accounts (scoped by ``family_id`` only, not
        ``family_query`` visibility). No record data is returned to the caller.

        Returns:
            int — number of transaction rows whose payday_period was changed.
        """
        family_id = db_helpers.get_family_id()
        if family_id is None:
            raise ValueError('No household selected.')
        transactions = Transaction.query.filter(
            Transaction.family_id == family_id,
            Transaction.transaction_date.isnot(None),
        ).all()

        updated = 0
        for txn in transactions:
            new_period = PaydayService.get_period_for_date(txn.transaction_date)
            if txn.payday_period != new_period:
                txn.payday_period = new_period
                updated += 1

        return updated

    @staticmethod
    def change_payday_and_reperiod(data):
        """Optionally save a new ``payday_day`` (1-31), then re-period every transaction.

        Day 31 already means "last day of the month": shorter months use their
        final day. Returns ``(updated_count, new_day_or_None)``.
        """
        raw_day = data.get('new_payday_day')
        raw_day = '' if raw_day is None else str(raw_day).strip()
        new_day = None
        if raw_day:
            try:
                new_day = int(raw_day)
            except ValueError:
                raise ValueError('Payday must be a day between 1 and 31.') from None
            if not 1 <= new_day <= 31:
                raise ValueError('Payday must be a day between 1 and 31.')
            Settings.set_value('payday_day', new_day, description='Day of month salary is paid',
                               setting_type='int')
        updated = PaydayService.reperiod_all_transactions()
        db.session.commit()
        return updated, new_day
