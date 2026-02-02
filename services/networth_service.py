from models.networth import NetWorth
from models.accounts import Account
from models.loans import Loan
from models.mortgage import Mortgage
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.loan_payments import LoanPayment
from models.pensions import Pension
from extensions import db
from datetime import date, datetime, timedelta
from decimal import Decimal


class NetWorthService:
    @staticmethod
    def calculate_current_networth():
        """Calculate current net worth from all accounts and liabilities"""
        from services.monthly_balance_service import MonthlyBalanceService
        
        today = date.today()
        
        # ASSETS
        # Get all active account balances using cache
        active_accounts = Account.query.filter_by(is_active=True).all()
        cash = 0.00
        savings = 0.00
        
        account_details = []
        for acc in active_accounts:
            # Try to get cached balance for current month
            balance = MonthlyBalanceService.get_balance_for_month(
                acc.id, 
                today.year, 
                today.month,
                use_projected=True  # Use projected for most up-to-date view
            )
            
            # Fallback to account balance if cache miss
            if balance is None:
                balance = float(acc.balance)
            
            account_details.append({'name': acc.name, 'type': acc.account_type, 'balance': balance})
            
            if acc.account_type in ['Joint', 'Personal']:
                cash += balance
            elif acc.account_type == 'Savings':
                savings += balance
        
        # Get pension values (sum of current values from active pensions)
        active_pensions = Pension.query.filter_by(is_active=True).all()
        pensions_value = sum(float(pension.current_value) for pension in active_pensions)
        
        pension_details = [
            {'name': p.provider, 'value': float(p.current_value)}
            for p in active_pensions
        ]
        
        # House value - TODO: implement when property tracking is added
        house_value = 0.00
        
        total_assets = cash + savings + house_value + pensions_value
        
        # LIABILITIES
        # Credit cards - sum of balances (negative balances = owe money)
        active_credit_cards = CreditCard.query.filter_by(is_active=True).all()
        credit_cards_total = 0.00
        cc_details = []
        for card in active_credit_cards:
            # Get latest transaction balance (paid only for current, all for projection)
            latest_txn = CreditCardTransaction.query.filter_by(
                credit_card_id=card.id,
                is_paid=True
            ).order_by(CreditCardTransaction.date.desc(), CreditCardTransaction.id.desc()).first()
            
            if latest_txn:
                balance = float(latest_txn.balance)
                # If balance is negative, we owe money (add as positive liability)
                if balance < 0:
                    credit_cards_total += abs(balance)
                    cc_details.append({'name': card.card_name, 'balance': balance, 'owed': abs(balance)})
                else:
                    cc_details.append({'name': card.card_name, 'balance': balance, 'owed': 0})
            else:
                cc_details.append({'name': card.card_name, 'balance': 0, 'owed': 0})
        
        # Loans - sum of remaining balances
        active_loans = Loan.query.filter_by(is_active=True).all()
        loans_total = 0.00
        loan_details = []
        for loan in active_loans:
            # Get latest paid loan payment
            latest_payment = LoanPayment.query.filter_by(
                loan_id=loan.id,
                is_paid=True
            ).order_by(LoanPayment.date.desc(), LoanPayment.id.desc()).first()
            
            if latest_payment:
                remaining = float(latest_payment.closing_balance)
                loans_total += remaining
                loan_details.append({'name': loan.name, 'balance': remaining})
            else:
                # No payments yet, use original loan value
                original = float(loan.loan_value)
                loans_total += original
                loan_details.append({'name': loan.name, 'balance': original})
        
        # Mortgage - get remaining balance
        mortgage_total = 0.00
        active_mortgage = Mortgage.query.filter_by(is_active=True).first()
        if active_mortgage:
            mortgage_total = float(active_mortgage.current_balance)
        
        total_liabilities = credit_cards_total + loans_total + mortgage_total
        
        # NET WORTH
        net_worth = total_assets - total_liabilities
        
        # Calculate liquid net worth (excluding pensions and house)
        liquid_assets = cash + savings
        liquid_net_worth = liquid_assets - total_liabilities
        
        return {
            'cash': cash,
            'savings': savings,
            'house_value': house_value,
            'pensions_value': pensions_value,
            'total_assets': total_assets,
            'liquid_assets': liquid_assets,
            'credit_cards': credit_cards_total,
            'loans': loans_total,
            'mortgage': mortgage_total,
            'total_liabilities': total_liabilities,
            'net_worth': net_worth,
            'liquid_net_worth': liquid_net_worth,
            # Detailed breakdowns for debugging
            'account_details': account_details,
            'pension_details': pension_details,
            'cc_details': cc_details,
            'loan_details': loan_details,
            'mortgage_balance': mortgage_total
        }
    
    @staticmethod
    def calculate_networth_at_date(target_date):
        """Calculate net worth as of a specific date (based on all data up to that date)"""
        # ASSETS - Accounts
        # Use monthly balance cache for efficient lookups
        from services.monthly_balance_service import MonthlyBalanceService
        
        active_accounts = Account.query.filter_by(is_active=True).all()
        cash = 0.00
        savings = 0.00
        
        today = date.today()
        
        for acc in active_accounts:
            # Determine if we should use actual or projected balance
            use_projected = target_date > today
            
            # Try to get balance from cache
            balance = MonthlyBalanceService.get_balance_for_month(
                acc.id, 
                target_date.year, 
                target_date.month,
                use_projected=use_projected
            )
            
            if balance is None:
                # Cache miss - fallback to current account balance
                # This should rarely happen if cache is populated properly
                balance = float(acc.balance)
            
            if balance != 0:
                if acc.account_type in ['Joint', 'Personal']:
                    cash += balance
                elif acc.account_type == 'Savings':
                    savings += balance
        
        # ASSETS - Pensions
        # Get pension snapshots on or before target_date
        from models.pension_snapshots import PensionSnapshot
        
        active_pensions = Pension.query.filter_by(is_active=True).all()
        pensions_value = 0.00
        
        for pension in active_pensions:
            latest_snapshot = PensionSnapshot.query.filter(
                PensionSnapshot.pension_id == pension.id,
                PensionSnapshot.snapshot_date <= target_date
            ).order_by(PensionSnapshot.snapshot_date.desc()).first()
            
            if latest_snapshot:
                pensions_value += float(latest_snapshot.value)
        
        house_value = 0.00
        total_assets = cash + savings + house_value + pensions_value
        liquid_assets = cash + savings
        
        # LIABILITIES - Credit Cards
        active_credit_cards = CreditCard.query.filter_by(is_active=True).all()
        credit_cards_total = 0.00
        
        for card in active_credit_cards:
            # For future dates, include unpaid transactions; for past, only paid
            query = CreditCardTransaction.query.filter(
                CreditCardTransaction.credit_card_id == card.id,
                CreditCardTransaction.date <= target_date
            )
            
            if target_date <= today:
                query = query.filter(CreditCardTransaction.is_paid == True)
            
            latest_txn = query.order_by(
                CreditCardTransaction.date.desc(), 
                CreditCardTransaction.id.desc()
            ).first()
            
            if latest_txn:
                balance = float(latest_txn.balance)
                if balance < 0:
                    credit_cards_total += abs(balance)
        
        # LIABILITIES - Loans
        active_loans = Loan.query.filter_by(is_active=True).all()
        loans_total = 0.00
        
        for loan in active_loans:
            # For future dates, include unpaid payments; for past, only paid
            query = LoanPayment.query.filter(
                LoanPayment.loan_id == loan.id,
                LoanPayment.date <= target_date
            )
            
            if target_date <= today:
                query = query.filter(LoanPayment.is_paid == True)
            
            latest_payment = query.order_by(
                LoanPayment.date.desc(), 
                LoanPayment.id.desc()
            ).first()
            
            if latest_payment:
                loans_total += float(latest_payment.closing_balance)
            elif loan.start_date <= target_date:
                # Loan started but no payments yet
                loans_total += float(loan.loan_value)
        
        # LIABILITIES - Mortgage
        from models.mortgage_payments import MortgagePayment
        
        mortgage_total = 0.00
        active_mortgage = Mortgage.query.filter_by(is_active=True).first()
        
        if active_mortgage:
            # For future dates, include unpaid payments; for past, only paid
            query = MortgagePayment.query.filter(
                MortgagePayment.mortgage_id == active_mortgage.id,
                MortgagePayment.date <= target_date
            )
            
            if target_date <= today:
                query = query.filter(MortgagePayment.is_paid == True)
            
            latest_payment = query.order_by(
                MortgagePayment.date.desc(), 
                MortgagePayment.id.desc()
            ).first()
            
            if latest_payment:
                mortgage_total = float(latest_payment.closing_balance)
            elif active_mortgage.start_date <= target_date:
                # Mortgage started but no payments yet
                mortgage_total = float(active_mortgage.loan_amount)
        
        total_liabilities = credit_cards_total + loans_total + mortgage_total
        net_worth = total_assets - total_liabilities
        liquid_net_worth = liquid_assets - total_liabilities
        
        return {
            'date': target_date,
            'cash': cash,
            'savings': savings,
            'house_value': house_value,
            'pensions_value': pensions_value,
            'total_assets': total_assets,
            'liquid_assets': liquid_assets,
            'credit_cards': credit_cards_total,
            'loans': loans_total,
            'mortgage': mortgage_total,
            'total_liabilities': total_liabilities,
            'net_worth': net_worth,
            'liquid_net_worth': liquid_net_worth
        }
    
    @staticmethod
    def get_monthly_timeline(start_year=None, start_month=None, num_months=24):
        """Generate monthly net worth timeline data"""
        from datetime import datetime
        from dateutil.relativedelta import relativedelta
        import calendar
        
        today = date.today()
        
        if start_year is None or start_month is None:
            # Default to 12 months ago from today
            start_date = today - relativedelta(months=12)
            start_year = start_date.year
            start_month = start_date.month
        
        timeline = []
        current_date = date(start_year, start_month, 1)
        
        for i in range(num_months):
            # Calculate net worth at end of each month
            _, last_day = calendar.monthrange(current_date.year, current_date.month)
            month_end = date(current_date.year, current_date.month, last_day)
            
            # For future months beyond today, mark as projection
            is_future = month_end > today
            
            # Always use month_end for calculations (past or future)
            calc_date = month_end
            
            values = NetWorthService.calculate_networth_at_date(calc_date)
            values['month'] = current_date.month
            values['year'] = current_date.year
            values['month_label'] = current_date.strftime('%b %Y')
            values['is_future'] = is_future
            values['calc_date'] = calc_date  # For debugging
            
            timeline.append(values)
            
            # Move to next month
            current_date = current_date + relativedelta(months=1)
        
        return timeline
    
    @staticmethod
    def get_networth_for_year(year):
        """Get monthly net worth data for a specific year"""
        return NetWorthService.get_monthly_timeline(year, 1, 12)
    
    @staticmethod
    def save_networth_snapshot(snapshot_date=None):
        """Save a snapshot of current net worth"""
        if snapshot_date is None:
            snapshot_date = date.today()
        
        # Check if snapshot already exists for this date
        existing = NetWorth.query.filter_by(date=snapshot_date).first()
        if existing:
            # Update existing snapshot
            snapshot = existing
        else:
            # Create new snapshot
            snapshot = NetWorth()
            snapshot.date = snapshot_date
        
        # Calculate current values
        values = NetWorthService.calculate_current_networth()
        
        # Update snapshot with current values
        snapshot.year_month = f"{snapshot_date.year}-{snapshot_date.month:02d}"
        snapshot.cash = Decimal(str(values['cash']))
        snapshot.savings = Decimal(str(values['savings']))
        snapshot.house_value = Decimal(str(values['house_value']))
        snapshot.pensions_value = Decimal(str(values['pensions_value']))
        snapshot.total_assets = Decimal(str(values['total_assets']))
        snapshot.credit_cards = Decimal(str(values['credit_cards']))
        snapshot.loans = Decimal(str(values['loans']))
        snapshot.mortgage = Decimal(str(values['mortgage']))
        snapshot.total_liabilities = Decimal(str(values['total_liabilities']))
        snapshot.net_worth = Decimal(str(values['net_worth']))
        
        # Calculate tracking percentages
        NetWorthService._calculate_tracking(snapshot)
        
        if not existing:
            db.session.add(snapshot)
        
        db.session.commit()
        return snapshot
    
    @staticmethod
    def _calculate_tracking(snapshot):
        """Calculate 1-month and 3-month tracking percentages"""
        # Get previous snapshots
        one_month_ago = snapshot.date - timedelta(days=30)
        three_months_ago = snapshot.date - timedelta(days=90)
        
        # Find closest snapshot to 1 month ago
        prev_1m = NetWorth.query.filter(NetWorth.date < snapshot.date)\
            .order_by(NetWorth.date.desc()).first()
        
        if prev_1m and float(prev_1m.net_worth) != 0:
            change = float(snapshot.net_worth) - float(prev_1m.net_worth)
            snapshot.one_month_track = Decimal(str((change / float(prev_1m.net_worth)) * 100))
        
        # Find snapshot closest to 3 months ago
        prev_3m = NetWorth.query.filter(NetWorth.date <= three_months_ago)\
            .order_by(NetWorth.date.desc()).first()
        
        if prev_3m and float(prev_3m.net_worth) != 0:
            change = float(snapshot.net_worth) - float(prev_3m.net_worth)
            snapshot.three_month_track = Decimal(str((change / float(prev_3m.net_worth)) * 100))
    
    @staticmethod
    def get_networth_trend():
        """Analyze net worth trend over time"""
        recent_snapshots = NetWorth.query.order_by(NetWorth.date.desc()).limit(12).all()
        
        if len(recent_snapshots) < 2:
            return {
                'trend': 'insufficient_data',
                'average_monthly_change': 0,
                'total_change': 0
            }
        
        # Calculate average monthly change
        total_change = 0
        changes = []
        for i in range(len(recent_snapshots) - 1):
            change = float(recent_snapshots[i].net_worth) - float(recent_snapshots[i + 1].net_worth)
            changes.append(change)
            total_change += change
        
        average_monthly_change = total_change / len(changes) if changes else 0
        
        # Determine trend
        if average_monthly_change > 100:
            trend = 'strong_growth'
        elif average_monthly_change > 0:
            trend = 'growth'
        elif average_monthly_change > -100:
            trend = 'decline'
        else:
            trend = 'strong_decline'
        
        return {
            'trend': trend,
            'average_monthly_change': average_monthly_change,
            'total_change': total_change,
            'recent_snapshots': recent_snapshots
        }
    
    @staticmethod
    @staticmethod
    def get_comparison_data():
        """Get month-over-month and year-over-year comparisons using timeline calculation"""
        from dateutil.relativedelta import relativedelta
        
        today = date.today()
        
        # Calculate current
        current = NetWorthService.calculate_networth_at_date(today)
        
        # Calculate 1 month ago
        one_month_ago = today - relativedelta(months=1)
        prev_month_data = NetWorthService.calculate_networth_at_date(one_month_ago)
        
        # Calculate 1 year ago
        one_year_ago = today - relativedelta(years=1)
        prev_year_data = NetWorthService.calculate_networth_at_date(one_year_ago)
        
        result = {
            'latest': None,
            'latest_date': today,
            'latest_value': current['net_worth']
        }
        
        # Month comparison
        change = current['net_worth'] - prev_month_data['net_worth']
        pct_change = (change / prev_month_data['net_worth'] * 100) if prev_month_data['net_worth'] != 0 else 0
        result['month_comparison'] = {
            'date': one_month_ago,
            'value': prev_month_data['net_worth'],
            'change': change,
            'pct_change': pct_change
        }
        
        # Year comparison
        change = current['net_worth'] - prev_year_data['net_worth']
        pct_change = (change / prev_year_data['net_worth'] * 100) if prev_year_data['net_worth'] != 0 else 0
        result['year_comparison'] = {
            'date': one_year_ago,
            'value': prev_year_data['net_worth'],
            'change': change,
            'pct_change': pct_change
        }
        
        return result
