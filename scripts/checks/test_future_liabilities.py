"""Test Future Loan and Credit Card Projections"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.networth_service import NetWorthService
from datetime import date
from dateutil.relativedelta import relativedelta

app = create_app()

with app.app_context():
    print("=" * 80)
    print("TESTING FUTURE LOAN & CREDIT CARD BALANCE PROJECTIONS")
    print("=" * 80)
    print()
    
    today = date.today()
    
    # Test future months (next 12 months)
    print("Future Monthly Projections (Next 12 Months):")
    print("-" * 80)
    print(f"{'Month':<12} {'Assets':<15} {'Liabilities':<15} {'Net Worth':<15} {'Change'}")
    print("-" * 80)
    
    timeline = NetWorthService.get_monthly_timeline(today.year, today.month, 12)
    
    prev_liabilities = None
    for i, month_data in enumerate(timeline):
        is_current = month_data['year'] == today.year and month_data['month'] == today.month
        marker = "→" if is_current else " "
        
        liabilities = month_data['total_liabilities']
        change = ""
        if prev_liabilities is not None:
            diff = liabilities - prev_liabilities
            if diff < 0:
                change = f"↓ £{abs(diff):.2f}"
            elif diff > 0:
                change = f"↑ £{diff:.2f}"
            else:
                change = "  £0.00"
        
        print(f"{marker} {month_data['month_label']:<10} "
              f"£{month_data['total_assets']:>12,.2f} "
              f"£{month_data['total_liabilities']:>12,.2f} "
              f"£{month_data['net_worth']:>12,.2f} "
              f"{change}")
        
        prev_liabilities = liabilities
    
    print("-" * 80)
    print()
    
    # Show detailed breakdown for current month vs 6 months out
    print("Detailed Breakdown Comparison:")
    print("-" * 80)
    
    current_data = NetWorthService.calculate_networth_at_date(today)
    future_date = today + relativedelta(months=6)
    future_data = NetWorthService.calculate_networth_at_date(future_date)
    
    print(f"\n{'Category':<20} {'Current (Feb 2026)':<20} {'Future (+6 months)':<20} {'Change'}")
    print("-" * 80)
    
    def format_change(current, future):
        diff = future - current
        if diff < 0:
            return f"↓ £{abs(diff):,.2f}"
        elif diff > 0:
            return f"↑ £{diff:,.2f}"
        else:
            return "  £0.00"
    
    print(f"{'Credit Cards':<20} £{current_data['credit_cards']:>17,.2f} "
          f"£{future_data['credit_cards']:>17,.2f} "
          f"{format_change(current_data['credit_cards'], future_data['credit_cards'])}")
    
    print(f"{'Loans':<20} £{current_data['loans']:>17,.2f} "
          f"£{future_data['loans']:>17,.2f} "
          f"{format_change(current_data['loans'], future_data['loans'])}")
    
    print(f"{'Mortgage':<20} £{current_data['mortgage']:>17,.2f} "
          f"£{future_data['mortgage']:>17,.2f} "
          f"{format_change(current_data['mortgage'], future_data['mortgage'])}")
    
    print("-" * 80)
    print(f"{'Total Liabilities':<20} £{current_data['total_liabilities']:>17,.2f} "
          f"£{future_data['total_liabilities']:>17,.2f} "
          f"{format_change(current_data['total_liabilities'], future_data['total_liabilities'])}")
    
    print()
    print("=" * 80)
    
    # Verify liabilities are decreasing
    if future_data['total_liabilities'] < current_data['total_liabilities']:
        print("✓ SUCCESS: Liabilities are decreasing over time (as expected)")
    else:
        print("✗ WARNING: Liabilities are NOT decreasing!")
    
    print("=" * 80)
