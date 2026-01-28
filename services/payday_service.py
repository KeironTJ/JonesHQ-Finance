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
            # Income (negative amount) adds to balance, expense (positive) subtracts
            # Note: In this system, income is stored as negative, expenses as positive
            if txn.amount < 0:
                current_balance += abs(Decimal(str(txn.amount)))
            else:  # Expense
                current_balance -= Decimal(str(txn.amount))
            
            balances.append(current_balance)
            min_balance = min(min_balance, current_balance)
        
        # Ending balance
        rolling_balance = current_balance if balances else opening_balance
        
        # Max extra spend is the difference between ending and minimum
        max_extra_spend = rolling_balance - min_balance
        
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
            # Income (negative amount) adds to balance, expense (positive) subtracts
            if txn.amount < 0:
                balance += abs(Decimal(str(txn.amount)))
            else:  # Expense
                balance -= Decimal(str(txn.amount))
        
        return balance
    
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
        # Get current date to determine starting period
        today = date.today()
        current_year = today.year
        current_month = today.month
        
        # Get payday periods
        periods = PaydayService.get_payday_periods(current_year, current_month, num_periods)
        
        results = []
        for start_date, end_date, period_label in periods:
            metrics = PaydayService.calculate_period_balances(account_id, start_date, end_date, include_unpaid)
            
            results.append({
                'period_label': period_label,
                'start_date': start_date,
                'end_date': end_date,
                'rolling_balance': metrics['rolling_balance'],
                'min_balance': metrics['min_balance'],
                'max_extra_spend': metrics['max_extra_spend'],
                'opening_balance': metrics['opening_balance']
            })
        
        return results
