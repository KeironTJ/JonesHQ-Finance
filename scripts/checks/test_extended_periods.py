"""Test Extended Period Functionality"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.networth_service import NetWorthService
from services.monthly_balance_service import MonthlyBalanceService
from datetime import date

app = create_app()

with app.app_context():
    print("=" * 80)
    print("TESTING EXTENDED PERIOD FUNCTIONALITY")
    print("=" * 80)
    print()
    
    # Test 1: Timeline with different periods
    print("1. Timeline Generation with Different Periods:")
    print("-" * 80)
    
    for months in [24, 60, 120]:
        timeline = NetWorthService.get_monthly_timeline(None, None, months)
        print(f"  {months} months: Generated {len(timeline)} data points")
        print(f"    First month: {timeline[0]['month_label']}")
        print(f"    Last month:  {timeline[-1]['month_label']}")
        print(f"    Last net worth: £{timeline[-1]['net_worth']:,.2f}")
        print()
    
    # Test 2: Check current cache coverage
    print("2. Current Cache Coverage:")
    print("-" * 80)
    from models.monthly_account_balance import MonthlyAccountBalance
    from extensions import db
    
    total_entries = MonthlyAccountBalance.query.count()
    months = db.session.query(
        db.func.count(db.func.distinct(MonthlyAccountBalance.year_month))
    ).scalar()
    
    # Get date range
    first = db.session.query(db.func.min(MonthlyAccountBalance.year_month)).scalar()
    last = db.session.query(db.func.max(MonthlyAccountBalance.year_month)).scalar()
    
    print(f"  Total cache entries: {total_entries}")
    print(f"  Unique months: {months}")
    print(f"  Coverage: {first} to {last}")
    print()
    
    # Test 3: Projection quality check
    print("3. Projection Quality Check:")
    print("-" * 80)
    
    from dateutil.relativedelta import relativedelta
    today = date.today()
    
    # Check 1, 5, 10 years from now
    for years in [1, 5, 10]:
        target_date = today + relativedelta(years=years)
        try:
            projection = NetWorthService.calculate_networth_at_date(target_date)
            print(f"  {years} year(s) from now ({target_date.strftime('%b %Y')}):")
            print(f"    Assets: £{projection['total_assets']:,.2f}")
            print(f"    Liabilities: £{projection['total_liabilities']:,.2f}")
            print(f"    Net Worth: £{projection['net_worth']:,.2f}")
        except Exception as e:
            print(f"  {years} year(s): ERROR - {str(e)}")
        print()
    
    print("=" * 80)
    print("TESTING COMPLETE")
    print("=" * 80)
