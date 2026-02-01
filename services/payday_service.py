"""
Payday Period Service
Handles calculations for payday-to-payday tracking periods
"""
from datetime import date, timedelta
from decimal import Decimal
from models.transactions import Transaction
from models.settings import Settings
from extensions import db


class PaydayService:
    """Service for managing payday period calculations"""
    
    @staticmethod
    def get_payday_setting():
        """Get the payday from settings (day of month)"""
        return Settings.get_value('payday_day', 15)  # Default to 15th
    
    @staticmethod
    def is_weekend(date_obj):
        """Check if a date falls on a weekend (Saturday=5, Sunday=6)"""
        return date_obj.weekday() >= 5
    
    @staticmethod
    def get_previous_working_day(date_obj):
        """Get the previous working day if date is a weekend"""
        while PaydayService.is_weekend(date_obj):
            date_obj = date_obj - timedelta(days=1)
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
    def calculate_period_balances(account_id, start_date, end_date, include_unpaid=True):
        """
        Calculate rolling balance, minimum balance, and max extra spend for a payday period.
        
        Args:
            account_id: Bank account ID to track
            start_date: Period start date
            end_date: Period end date
            include_unpaid: Whether to include unpaid transactions (default True for forecasting)
            
        Returns:
            dict with rolling_balance, min_balance, max_extra_spend
        """
        # Get opening balance (cumulative balance at start_date - 1)
        opening_balance = PaydayService.get_balance_at_date(account_id, start_date - timedelta(days=1), include_unpaid=True)
        
        # Get all transactions in the period (regardless of paid status - we want to see forecast)
        query = Transaction.query.filter(
            Transaction.account_id == account_id,
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date
        )
        
        # Always include unpaid for payday forecasting
        # (The include_unpaid parameter is kept for consistency but we ignore it for now)
        
        transactions = query.order_by(Transaction.transaction_date).all()
        
        # Calculate daily balances
        current_balance = opening_balance
        min_balance = opening_balance
        balances = []
        
        for txn in transactions:
            # Income (positive amount) adds to balance, expense (negative) subtracts
            # Note: In this system, income is stored as positive, expenses as negative
            if txn.amount > 0:
                current_balance += Decimal(str(txn.amount))
            else:  # Expense
                current_balance -= abs(Decimal(str(txn.amount)))
            
            balances.append(current_balance)
            min_balance = min(min_balance, current_balance)
        
        # Ending balance
        rolling_balance = current_balance if balances else opening_balance
        
        # Max extra spend is the difference between ending balance and opening balance
        max_extra_spend = rolling_balance - opening_balance
        
        return {
            'rolling_balance': float(rolling_balance),
            'min_balance': float(min_balance),
            'max_extra_spend': float(max_extra_spend),
            'opening_balance': float(opening_balance)
        }
    
    @staticmethod
    def get_balance_at_date(account_id, target_date, include_unpaid=True):
        """
        Calculate cumulative account balance at a specific date.
        Always includes all transactions (paid and unpaid) for forecasting.
        
        Args:
            account_id: Bank account ID
            target_date: Date to calculate balance for
            include_unpaid: Whether to include unpaid transactions (kept for compatibility, always True for payday)
            
        Returns:
            Decimal balance
        """
        # Get account
        from models.accounts import Account
        account = Account.query.get(account_id)
        if not account:
            return Decimal('0.00')
        
        # Start from zero and calculate cumulative balance
        balance = Decimal('0.00')
        
        # Get all transactions up to target_date (including unpaid for forecasting)
        query = Transaction.query.filter(
            Transaction.account_id == account_id,
            Transaction.transaction_date <= target_date
        )
        
        # Always include all transactions for payday forecasting
        
        transactions = query.order_by(Transaction.transaction_date).all()
        
        # Apply transactions
        for txn in transactions:
            # Income (positive amount) adds to balance, expense (negative) subtracts
            if txn.amount > 0:
                balance += Decimal(str(txn.amount))
            else:  # Expense
                balance -= abs(Decimal(str(txn.amount)))
        
        return balance
    
    @staticmethod
    def get_category_breakdown(account_id, start_date, end_date, include_unpaid=True):
        """
        Get spending breakdown by category and subcategory for a payday period.
        Includes both income and expenses.
        
        Args:
            account_id: Bank account ID to track (None for all accounts)
            start_date: Period start date
            end_date: Period end date
            include_unpaid: Whether to include unpaid transactions
            
        Returns:
            Dict with 'income' and 'expenses' lists, each containing category breakdowns
        """
        from models.categories import Category
        from sqlalchemy import func
        
        # Get all transactions in the period
        query = Transaction.query.filter(
            Transaction.transaction_date >= start_date,
            Transaction.transaction_date <= end_date
        )
        
        # Optionally filter by account
        if account_id:
            query = query.filter(Transaction.account_id == account_id)
        
        transactions = query.all()
        
        # Separate income and expenses
        income_totals = {}
        expense_totals = {}
        uncategorized_income = 0
        uncategorized_expense = 0
        
        for txn in transactions:
            amount = abs(float(txn.amount))
            is_income = txn.amount > 0
            
            if txn.category_id:
                category = Category.query.get(txn.category_id)
                if category:
                    head = category.head_budget or 'Uncategorized'
                    sub = category.sub_budget or 'General'
                    
                    # Choose the right totals dict
                    totals = income_totals if is_income else expense_totals
                    
                    if head not in totals:
                        totals[head] = {
                            'total': 0,
                            'subcategories': {}
                        }
                    
                    if sub not in totals[head]['subcategories']:
                        totals[head]['subcategories'][sub] = 0
                    
                    totals[head]['total'] += amount
                    totals[head]['subcategories'][sub] += amount
                else:
                    if is_income:
                        uncategorized_income += amount
                    else:
                        uncategorized_expense += amount
            else:
                if is_income:
                    uncategorized_income += amount
                else:
                    uncategorized_expense += amount
        
        # Add uncategorized if there are any
        if uncategorized_income > 0:
            income_totals['Uncategorized'] = {
                'total': uncategorized_income,
                'subcategories': {'No Category': uncategorized_income}
            }
        
        if uncategorized_expense > 0:
            expense_totals['Uncategorized'] = {
                'total': uncategorized_expense,
                'subcategories': {'No Category': uncategorized_expense}
            }
        
        # Convert to sorted lists
        income_result = []
        for head, data in sorted(income_totals.items(), key=lambda x: x[1]['total'], reverse=True):
            subcats = [{'name': sub, 'amount': amt} for sub, amt in sorted(data['subcategories'].items(), key=lambda x: x[1], reverse=True)]
            income_result.append({
                'category': head,
                'total': data['total'],
                'subcategories': subcats
            })
        
        expense_result = []
        for head, data in sorted(expense_totals.items(), key=lambda x: x[1]['total'], reverse=True):
            subcats = [{'name': sub, 'amount': amt} for sub, amt in sorted(data['subcategories'].items(), key=lambda x: x[1], reverse=True)]
            expense_result.append({
                'category': head,
                'total': data['total'],
                'subcategories': subcats
            })
        
        return {
            'income': income_result,
            'expenses': expense_result
        }
    
    @staticmethod
    def get_payday_summary(account_id, num_periods=12, include_unpaid=True):
        """
        Get summary of all payday periods for dashboard display.
        
        Args:
            account_id: Bank account ID to track
            num_periods: Number of periods to show
            include_unpaid: Whether to include unpaid transactions
            
        Returns:
            List of dicts with period info and metrics
        """
        # Get current date and determine which payday period we're in
        today = date.today()
        current_period_label = PaydayService.get_period_for_date(today)
        
        # Extract year and month from period label (format: "2026-01")
        current_year = int(current_period_label.split('-')[0])
        current_month = int(current_period_label.split('-')[1])
        
        # Get payday periods starting from current period
        periods = PaydayService.get_payday_periods(current_year, current_month, num_periods)
        
        results = []
        for start_date, end_date, period_label in periods:
            metrics = PaydayService.calculate_period_balances(account_id, start_date, end_date, include_unpaid)
            category_breakdown = PaydayService.get_category_breakdown(account_id, start_date, end_date, include_unpaid)
            
            results.append({
                'period_label': period_label,
                'start_date': start_date,
                'end_date': end_date,
                'rolling_balance': metrics['rolling_balance'],
                'min_balance': metrics['min_balance'],
                'max_extra_spend': metrics['max_extra_spend'],
                'opening_balance': metrics['opening_balance'],
                'category_breakdown': category_breakdown
            })
        
        return results
