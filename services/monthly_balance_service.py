"""
Monthly Balance Service
=======================
Write-through cache of end-of-month account balances stored in the
MonthlyAccountBalance table.  Avoids full transaction-history scans
when rendering dashboards, net-worth timelines, and payday summaries.

Cache model
-----------
Each row stores (account_id, year_month) → (actual_balance, projected_balance).

  actual_balance    — sum of is_paid=True transactions up to month-end.
  projected_balance — sum of all transactions (paid + unpaid); for future months
                      also includes is_forecasted=True transactions.

The cache is updated incrementally: whenever a transaction is added, edited, or
deleted, call handle_transaction_change() to refresh from that month forward.
A full rebuild is available via rebuild_all_cache() (for migrations or corruption).

Primary entry points
--------------------
  handle_transaction_change()         — invalidate and refresh from a month forward
  get_balance_for_month()             — read cached balance (returns None on miss)
  update_month_cache()                — recalculate and save one month
  update_account_from_month()         — recalculate all months forward for one account
  update_all_accounts_from_month()    — same for all active accounts
  rebuild_all_cache()                 — full rebuild from earliest transaction
"""
from datetime import date, datetime, timezone
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from models.monthly_account_balance import MonthlyAccountBalance
from models.accounts import Account
from models.transactions import Transaction
from extensions import db
import calendar
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


class MonthlyBalanceService:
    """
    Write-through cache for end-of-month account balances.

    Call handle_transaction_change() whenever a transaction is created, edited, or
    deleted to keep the cache current.  Read via get_balance_for_month().
    """
    
    @staticmethod
    def get_year_month_string(year, month):
        """Convert year/month to YYYY-MM string"""
        return f"{year:04d}-{month:02d}"
    
    @staticmethod
    def parse_year_month(year_month_str):
        """Parse YYYY-MM string to (year, month) tuple"""
        parts = year_month_str.split('-')
        return int(parts[0]), int(parts[1])
    
    @staticmethod
    def get_month_end_date(year, month):
        """Get the last day of the given month"""
        _, last_day = calendar.monthrange(year, month)
        return date(year, month, last_day)
    
    @staticmethod
    def calculate_month_balance(account_id, year, month, include_forecasted=False):
        """
        Calculate balance for a specific account and month
        
        Returns: (actual_balance, projected_balance)
        - actual_balance: Only paid transactions
        - projected_balance: Paid + unpaid + (optionally) forecasted
        """
        month_end = MonthlyBalanceService.get_month_end_date(year, month)
        
        # Get all transactions up to and including this month
        query = family_query(Transaction).filter(
            Transaction.account_id == account_id,
            Transaction.transaction_date <= month_end
        ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc())
        
        all_txns = query.all()
        
        # Calculate actual balance (paid only)
        actual_balance = Decimal('0')
        for txn in all_txns:
            if txn.is_paid:
                actual_balance += Decimal(str(txn.amount))
        
        # Calculate projected balance (paid + unpaid + forecasted)
        projected_balance = Decimal('0')
        for txn in all_txns:
            if include_forecasted or not txn.is_forecasted:
                projected_balance += Decimal(str(txn.amount))
        
        return float(actual_balance), float(projected_balance)
    
    @staticmethod
    def update_month_cache(account_id, year, month):
        """Update or create cache entry for a specific account/month"""
        year_month = MonthlyBalanceService.get_year_month_string(year, month)
        
        # Calculate balances
        today = date.today()
        month_end = MonthlyBalanceService.get_month_end_date(year, month)
        is_future = month_end > today
        
        # Include forecasted transactions for future months
        actual, projected = MonthlyBalanceService.calculate_month_balance(
            account_id, year, month, include_forecasted=is_future
        )
        
        # Find or create cache entry
        cache_entry = family_query(MonthlyAccountBalance).filter_by(
            account_id=account_id,
            year_month=year_month
        ).first()
        
        if cache_entry:
            cache_entry.actual_balance = actual
            cache_entry.projected_balance = projected
            cache_entry.last_calculated = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            cache_entry = MonthlyAccountBalance(
                account_id=account_id,
                year_month=year_month,
                actual_balance=actual,
                projected_balance=projected,
                last_calculated=datetime.now(timezone.utc).replace(tzinfo=None)
            )
            db.session.add(cache_entry)
        
        return cache_entry
    
    @staticmethod
    def update_account_from_month(account_id, start_year, start_month, num_months=None, future_months=24):
        """
        Update cache for an account starting from a specific month forward
        
        Args:
            account_id: Account to update
            start_year: Starting year
            start_month: Starting month
            num_months: How many months to update (None = all future months up to future_months from now)
            future_months: How many months into the future to project (default 24)
        """
        if num_months is None:
            # Update from start month to future_months in the future (for longer projections)
            today = date.today()
            future_date = today + relativedelta(months=future_months)
            
            # Calculate number of months between start and future
            start_date = date(start_year, start_month, 1)
            months_diff = (future_date.year - start_date.year) * 12 + (future_date.month - start_date.month) + 1
            num_months = max(months_diff, 1)
        
        current_year = start_year
        current_month = start_month
        
        for i in range(num_months):
            MonthlyBalanceService.update_month_cache(account_id, current_year, current_month)
            
            # Move to next month
            current_month += 1
            if current_month > 12:
                current_month = 1
                current_year += 1
        
        db.session.commit()
    
    @staticmethod
    def update_all_accounts_from_month(start_year, start_month, num_months=None, future_months=24):
        """Update all active accounts from a specific month forward"""
        accounts = family_query(Account).filter_by(is_active=True).all()
        
        for account in accounts:
            MonthlyBalanceService.update_account_from_month(
                account.id, start_year, start_month, num_months, future_months
            )
        
        db.session.commit()
    
    @staticmethod
    def get_balance_for_month(account_id, year, month, use_projected=False):
        """
        Get cached balance for a specific account/month
        
        Args:
            account_id: Account ID
            year: Year
            month: Month
            use_projected: If True, return projected_balance; else actual_balance
        
        Returns: Balance as float, or None if not cached
        """
        year_month = MonthlyBalanceService.get_year_month_string(year, month)
        
        cache_entry = family_query(MonthlyAccountBalance).filter_by(
            account_id=account_id,
            year_month=year_month
        ).first()
        
        if cache_entry:
            return float(cache_entry.projected_balance if use_projected else cache_entry.actual_balance)
        
        return None
    
    @staticmethod
    def rebuild_all_cache(future_months=24):
        """
        Rebuild entire cache from scratch (use for initial population or full refresh)
        
        Args:
            future_months: How many months into the future to project (default 24, max 240 for retirement planning)
        """
        # Clear existing cache
        MonthlyAccountBalance.query.delete()
        db.session.commit()
        
        # Find earliest transaction date across all accounts
        earliest = family_query(Transaction).with_entities(db.func.min(Transaction.transaction_date)).scalar()
        
        if not earliest:
            print("No transactions found")
            return
        
        # Start from earliest transaction month
        start_year = earliest.year
        start_month = earliest.month
        
        # Update all accounts from earliest month to future_months in future
        print(f"Rebuilding cache from {start_year}-{start_month:02d} to {future_months} months in future...")
        MonthlyBalanceService.update_all_accounts_from_month(start_year, start_month, future_months=future_months)
        
        print("Cache rebuild complete!")
    
    @staticmethod
    def handle_transaction_change(account_id, transaction_date):
        """
        Invalidate and refresh the cache from transaction_date's month forward.

        Call this whenever a Transaction for the given account is created, edited,
        or deleted.  Recalculates from that month through 24 future months so
        downstream balance forecasts stay accurate.

        Args:
            account_id:       ID of the bank account whose cache needs updating.
            transaction_date: Date of the changed transaction (determines start month).
        """
        year = transaction_date.year
        month = transaction_date.month
        
        # Update from this month forward
        MonthlyBalanceService.update_account_from_month(account_id, year, month)
