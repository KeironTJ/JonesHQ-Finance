"""
Net Worth Service
=================
Calculates and tracks household net worth across all asset and liability categories.

Asset categories
----------------
  Cash      — Joint + Personal bank account balances
  Savings   — Savings account balances
  Property  — current_valuation of active properties (projected forward for future dates)
  Pensions  — sum of current_value / projected PensionSnapshots

Liability categories
--------------------
  Credit cards — sum of negative balances (paid transactions for past; all for future)
  Loans        — closing_balance of latest LoanPayment (paid for past; all for future)
  Mortgage     — MortgageSnapshot balance (actual for past; 'base' projection for future)

Past vs future
--------------
For dates <= today the service uses only is_paid=True / is_projection=False records.
For future dates it includes unpaid/projected records and applies property appreciation
using the property's annual_appreciation_rate.

Balance cache
-------------
Bank account balances are read from MonthlyAccountBalance (the cache managed by
MonthlyBalanceService) rather than summing transactions on the fly.

Primary entry points
--------------------
  calculate_current_networth()      — snapshot of today's position
  calculate_networth_at_date()      — point-in-time calculation for any date
  get_monthly_timeline()            — list of monthly snapshots over a date range
  save_networth_snapshot()          — persist a NetWorth record for today
  get_networth_trend()              — trend label + average monthly change
  get_comparison_data()             — month-over-month and year-over-year comparisons
"""
from models.networth import NetWorth
from models.accounts import Account
from models.loans import Loan
from models.mortgage import Mortgage, MortgageProduct
from models.mortgage_payments import MortgagePayment, MortgageSnapshot
from models.property import Property
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.loan_payments import LoanPayment
from models.pensions import Pension
from extensions import db
from datetime import date, datetime, timedelta
from decimal import Decimal
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


class NetWorthService:
    """
    Calculates net worth from all asset and liability categories.

    Uses the MonthlyAccountBalance cache for bank account balances.  Falls back to
    account.balance on cache miss.
    """

    @staticmethod
    def calculate_current_networth():
        """
        Calculate today's net worth across all asset and liability categories.

        Delegates core number calculation to calculate_networth_at_date(today) so
        that the summary cards and the timeline's current-month row always agree.
        Adds detail breakdowns (account_details, cc_details, etc.) for template display.

        Returns a dict with all keys from calculate_networth_at_date plus:
          account_details, pension_details, cc_details, loan_details,
          mortgage_balance, property_details.
        """
        from services.monthly_balance_service import MonthlyBalanceService

        today = date.today()

        # Single source of truth for all totals
        base = NetWorthService.calculate_networth_at_date(today)

        # --- Detail breakdowns (display only, do not affect totals) ---

        # Account details
        active_accounts = family_query(Account).filter_by(is_active=True).all()
        account_details = []
        for acc in active_accounts:
            balance = MonthlyBalanceService.get_balance_for_month(
                acc.id, today.year, today.month, use_projected=True
            )
            if balance is None:
                balance = float(acc.balance)
            account_details.append({'name': acc.name, 'type': acc.account_type, 'balance': balance})

        # Pension details
        active_pensions = family_query(Pension).filter_by(is_active=True).all()
        pension_details = [
            {'name': p.provider, 'value': float(p.current_value)}
            for p in active_pensions
        ]

        # Credit card details
        active_credit_cards = family_query(CreditCard).filter_by(is_active=True).all()
        cc_details = []
        for card in active_credit_cards:
            latest_txn = family_query(CreditCardTransaction).filter_by(
                credit_card_id=card.id,
                is_paid=True
            ).order_by(CreditCardTransaction.date.desc(), CreditCardTransaction.id.desc()).first()
            if latest_txn:
                balance = float(latest_txn.balance)
                cc_details.append({'name': card.card_name, 'balance': balance, 'owed': abs(balance) if balance < 0 else 0})
            else:
                cc_details.append({'name': card.card_name, 'balance': 0, 'owed': 0})

        # Loan details
        active_loans = family_query(Loan).filter_by(is_active=True).all()
        loan_details = []
        for loan in active_loans:
            latest_payment = family_query(LoanPayment).filter_by(
                loan_id=loan.id,
                is_paid=True
            ).order_by(LoanPayment.date.desc(), LoanPayment.id.desc()).first()
            if latest_payment:
                remaining = float(latest_payment.closing_balance)
            else:
                remaining = float(loan.loan_value)
            loan_details.append({'name': loan.name, 'balance': remaining})

        # Property / mortgage details
        active_properties = family_query(Property).filter_by(is_active=True).all()
        property_details = []
        for prop in active_properties:
            active_products = family_query(MortgageProduct).filter_by(
                property_id=prop.id,
                is_active=True
            ).all()
            property_mortgage = sum(float(p.current_balance) for p in active_products)
            property_details.append({
                'address': prop.address,
                'valuation': float(prop.current_valuation) if prop.current_valuation else 0,
                'mortgage': property_mortgage,
                'equity': float(prop.current_equity)
            })

        return {
            **base,
            'account_details': account_details,
            'pension_details': pension_details,
            'cc_details': cc_details,
            'loan_details': loan_details,
            'mortgage_balance': base['mortgage'],
            'property_details': property_details
        }
    
    @staticmethod
    def calculate_networth_at_date(target_date):
        """
        Calculate net worth as of a specific date (past, present, or future).

        For past/present dates: uses only is_paid=True / is_projection=False records.
        For future dates: includes unpaid/projected records and applies property
        appreciation forward from current_valuation using annual_appreciation_rate.

        Returns the same dict structure as calculate_current_networth() plus 'date'.
        """
        # ASSETS - Accounts
        # Use monthly balance cache for efficient lookups
        from services.monthly_balance_service import MonthlyBalanceService
        
        active_accounts = family_query(Account).filter_by(is_active=True).all()
        cash = 0.00
        savings = 0.00
        
        today = date.today()
        
        for acc in active_accounts:
            # Determine if we should use actual or projected balance.
            # Use projected for today too so it matches calculate_current_networth.
            use_projected = target_date >= today
            
            # Try to get balance from cache
            balance = MonthlyBalanceService.get_balance_for_month(
                acc.id, 
                target_date.year, 
                target_date.month,
                use_projected=use_projected
            )
            
            if balance is None:
                # Cache miss — for future/today use current balance as best estimate;
                # for past months we have no data so report 0 to avoid showing stale values.
                if use_projected:
                    balance = float(acc.balance)
                else:
                    balance = 0.0
            
            if balance != 0:
                if acc.account_type in ['Joint', 'Personal']:
                    cash += balance
                elif acc.account_type == 'Savings':
                    savings += balance
        
        # ASSETS - Pensions
        # Get pension values - use actual for past/present, projections for future
        from models.pension_snapshots import PensionSnapshot
        
        all_pensions = family_query(Pension).filter_by(is_active=True).all()
        pensions_value = 0.00
        is_future_date = target_date > datetime.now().date()
        
        for pension in all_pensions:
            if is_future_date:
                # For future dates, use projected snapshots (default scenario)
                latest_snapshot = family_query(PensionSnapshot).filter(
                    PensionSnapshot.pension_id == pension.id,
                    PensionSnapshot.review_date <= target_date,
                    PensionSnapshot.is_projection == True,
                    PensionSnapshot.scenario_name == 'default'
                ).order_by(PensionSnapshot.review_date.desc()).first()
                
                # If no projection yet, fall back to current value
                if latest_snapshot:
                    pensions_value += float(latest_snapshot.value)
                elif pension.current_value:
                    pensions_value += float(pension.current_value)
            else:
                # For past/present dates, use actual snapshots only
                latest_snapshot = family_query(PensionSnapshot).filter(
                    PensionSnapshot.pension_id == pension.id,
                    PensionSnapshot.review_date <= target_date,
                    PensionSnapshot.is_projection == False
                ).order_by(PensionSnapshot.review_date.desc()).first()
                
                if latest_snapshot:
                    pensions_value += float(latest_snapshot.value)
                # No fallback to current_value for past dates — show 0 if no actual snapshot exists
        
        house_value = 0.00
        total_assets = cash + savings + house_value + pensions_value
        liquid_assets = cash + savings
        
        # LIABILITIES - Credit Cards
        active_credit_cards = family_query(CreditCard).filter_by(is_active=True).all()
        credit_cards_total = 0.00
        
        for card in active_credit_cards:
            # For future dates, include unpaid transactions; for past, only paid
            query = family_query(CreditCardTransaction).filter(
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
        active_loans = family_query(Loan).filter_by(is_active=True).all()
        loans_total = 0.00
        
        for loan in active_loans:
            # For future dates, include unpaid payments; for past, only paid
            query = family_query(LoanPayment).filter(
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
        
        # LIABILITIES - Mortgage & Property Values
        from models.property_valuation_snapshot import PropertyValuationSnapshot

        mortgage_total = 0.00
        house_value = 0.00

        is_future_date = target_date > today
        active_properties = family_query(Property).filter_by(is_active=True).all()

        for prop in active_properties:
            # Exclude property before its purchase date (skip entirely for those months).
            # If purchase_date is not set we can't gate by date, so include for all months.
            if prop.purchase_date and prop.purchase_date > target_date:
                continue

            if is_future_date:
                # For future dates: use a projection snapshot if available, otherwise
                # compound forward from the latest actual snapshot (or current_valuation).
                proj_snapshot = family_query(PropertyValuationSnapshot).filter(
                    PropertyValuationSnapshot.property_id == prop.id,
                    PropertyValuationSnapshot.valuation_date <= target_date,
                    PropertyValuationSnapshot.is_projection == True,
                ).order_by(PropertyValuationSnapshot.valuation_date.desc()).first()

                if proj_snapshot:
                    house_value += float(proj_snapshot.value)
                else:
                    # Fall back: compound from latest actual snapshot or current_valuation
                    latest_actual = family_query(PropertyValuationSnapshot).filter(
                        PropertyValuationSnapshot.property_id == prop.id,
                        PropertyValuationSnapshot.is_projection == False,
                    ).order_by(PropertyValuationSnapshot.valuation_date.desc()).first()

                    if latest_actual:
                        base_value = float(latest_actual.value)
                        # Compound from the snapshot date, not from today
                        base_date = latest_actual.valuation_date
                    else:
                        base_value = float(prop.current_valuation) if prop.current_valuation else 0
                        base_date = today

                    if prop.annual_appreciation_rate and base_value:
                        months_diff = (target_date.year - base_date.year) * 12 + (target_date.month - base_date.month)
                        monthly_rate = Decimal(str(prop.annual_appreciation_rate)) / Decimal('12') / Decimal('100')
                        projected_val = Decimal(str(base_value)) * ((Decimal('1') + monthly_rate) ** months_diff)
                        house_value += float(projected_val)
                    else:
                        house_value += base_value
            else:
                # For past/present dates: interpolate between surrounding actual snapshots
                # to show smooth monthly growth rather than a flat staircase.
                prev_snap = family_query(PropertyValuationSnapshot).filter(
                    PropertyValuationSnapshot.property_id == prop.id,
                    PropertyValuationSnapshot.valuation_date <= target_date,
                    PropertyValuationSnapshot.is_projection == False,
                ).order_by(PropertyValuationSnapshot.valuation_date.desc()).first()

                next_snap = family_query(PropertyValuationSnapshot).filter(
                    PropertyValuationSnapshot.property_id == prop.id,
                    PropertyValuationSnapshot.valuation_date > target_date,
                    PropertyValuationSnapshot.is_projection == False,
                ).order_by(PropertyValuationSnapshot.valuation_date.asc()).first()

                if prev_snap and next_snap:
                    # Interpolate linearly between the two known valuations
                    prev_val = float(prev_snap.value)
                    next_val = float(next_snap.value)
                    prev_d = prev_snap.valuation_date
                    next_d = next_snap.valuation_date
                    span = (next_d.year - prev_d.year) * 12 + (next_d.month - prev_d.month)
                    elapsed = ((target_date.year - prev_d.year) * 12
                               + (target_date.month - prev_d.month))
                    fraction = elapsed / span if span > 0 else 0
                    house_value += prev_val + (next_val - prev_val) * fraction

                elif prev_snap:
                    # After the last known snapshot: compound forward at annual_appreciation_rate
                    base_val = float(prev_snap.value)
                    base_d = prev_snap.valuation_date
                    months_elapsed = ((target_date.year - base_d.year) * 12
                                      + (target_date.month - base_d.month))
                    if prop.annual_appreciation_rate and months_elapsed > 0:
                        monthly_rate = (Decimal(str(prop.annual_appreciation_rate))
                                        / Decimal('12') / Decimal('100'))
                        projected = Decimal(str(base_val)) * ((Decimal('1') + monthly_rate) ** months_elapsed)
                        house_value += float(projected)
                    else:
                        house_value += base_val

                elif next_snap:
                    # Before the first snapshot: interpolate from purchase price → first snapshot,
                    # but only if we know both when and at what price it was acquired.
                    # Without a purchase_date we can't anchor the curve, so show 0.
                    if prop.purchase_date and prop.purchase_price:
                        next_val = float(next_snap.value)
                        next_d = next_snap.valuation_date
                        anchor_val = float(prop.purchase_price)
                        span = ((next_d.year - prop.purchase_date.year) * 12
                                + (next_d.month - prop.purchase_date.month))
                        elapsed = ((target_date.year - prop.purchase_date.year) * 12
                                   + (target_date.month - prop.purchase_date.month))
                        fraction = elapsed / span if span > 0 else 0
                        house_value += anchor_val + (next_val - anchor_val) * fraction

                else:
                    # No snapshots at all: purchase_price is the best known historical value.
                    # Do NOT fall back to current_valuation — that's today's value, wrong for history.
                    if prop.purchase_price:
                        house_value += float(prop.purchase_price)

            # Get mortgage products for this property (runs for past AND future)
            active_products = family_query(MortgageProduct).filter_by(
                property_id=prop.id,
                is_active=True
            ).all()

            for product in active_products:
                # Skip if product hasn't started yet
                if product.start_date > target_date:
                    continue

                # Get snapshot at or before target date
                if is_future_date:
                    # Use projection
                    snapshot = family_query(MortgageSnapshot).filter(
                        MortgageSnapshot.mortgage_product_id == product.id,
                        MortgageSnapshot.date <= target_date,
                        MortgageSnapshot.is_projection == True,
                        MortgageSnapshot.scenario_name == 'base'
                    ).order_by(MortgageSnapshot.date.desc()).first()
                else:
                    # Use actual
                    snapshot = family_query(MortgageSnapshot).filter(
                        MortgageSnapshot.mortgage_product_id == product.id,
                        MortgageSnapshot.date <= target_date,
                        MortgageSnapshot.is_projection == False
                    ).order_by(MortgageSnapshot.date.desc()).first()

                if snapshot:
                    mortgage_total += float(snapshot.balance)
                elif product.start_date <= target_date:
                    # Product started but no snapshot yet — use current_balance, not initial
                    mortgage_total += float(product.current_balance)
        
        # Recalculate now that house_value is populated from the property loop
        total_assets = cash + savings + house_value + pensions_value

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
            # Always show exactly 5 years (60 months) of history.
            # num_months = 60 past + however many future months the caller wants.
            start_date = today - relativedelta(months=60)
            start_year = start_date.year
            start_month = start_date.month
        
        timeline = []
        current_date = date(start_year, start_month, 1)
        
        for i in range(num_months):
            # Calculate net worth at end of each month
            _, last_day = calendar.monthrange(current_date.year, current_date.month)
            month_end = date(current_date.year, current_date.month, last_day)
            
            # Past months: month_end is settled history.
            # Current/future months: month_end is a projection.
            is_future = month_end > today
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
        existing = family_query(NetWorth).filter_by(date=snapshot_date).first()
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
        prev_1m = family_query(NetWorth).filter(NetWorth.date < snapshot.date)\
            .order_by(NetWorth.date.desc()).first()
        
        if prev_1m and float(prev_1m.net_worth) != 0:
            change = float(snapshot.net_worth) - float(prev_1m.net_worth)
            snapshot.one_month_track = Decimal(str((change / float(prev_1m.net_worth)) * 100))
        
        # Find snapshot closest to 3 months ago
        prev_3m = family_query(NetWorth).filter(NetWorth.date <= three_months_ago)\
            .order_by(NetWorth.date.desc()).first()
        
        if prev_3m and float(prev_3m.net_worth) != 0:
            change = float(snapshot.net_worth) - float(prev_3m.net_worth)
            snapshot.three_month_track = Decimal(str((change / float(prev_3m.net_worth)) * 100))
    
    @staticmethod
    def get_networth_trend():
        """Analyze net worth trend over time"""
        recent_snapshots = family_query(NetWorth).order_by(NetWorth.date.desc()).limit(12).all()
        
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
