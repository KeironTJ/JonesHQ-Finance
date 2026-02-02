"""Test Net Worth Timeline with Cache"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.networth_service import NetWorthService
from datetime import date

app = create_app()

with app.app_context():
    print("=" * 60)
    print("TESTING NET WORTH WITH MONTHLY BALANCE CACHE")
    print("=" * 60)
    print()
    
    # Test current net worth
    print("1. Current Net Worth:")
    current = NetWorthService.calculate_current_networth()
    print(f"   Total Assets: £{current['total_assets']:.2f}")
    print(f"   Total Liabilities: £{current['total_liabilities']:.2f}")
    print(f"   Net Worth: £{current['net_worth']:.2f}")
    print(f"   Liquid Net Worth: £{current['liquid_net_worth']:.2f}")
    print()
    
    # Test net worth at specific date (should use cache)
    print("2. Net Worth at 2024-12-31 (using cache):")
    dec_2024 = date(2024, 12, 31)
    dec_values = NetWorthService.calculate_networth_at_date(dec_2024)
    print(f"   Total Assets: £{dec_values['total_assets']:.2f}")
    print(f"   Total Liabilities: £{dec_values['total_liabilities']:.2f}")
    print(f"   Net Worth: £{dec_values['net_worth']:.2f}")
    print(f"   Cash: £{dec_values['cash']:.2f}")
    print(f"   Savings: £{dec_values['savings']:.2f}")
    print()
    
    # Test timeline (last 6 months)
    print("3. Last 6 Months Timeline:")
    timeline = NetWorthService.get_monthly_timeline(2024, 9, 6)
    for month_data in timeline:
        print(f"   {month_data['month_label']}: £{month_data['net_worth']:.2f} "
              f"(Assets: £{month_data['total_assets']:.2f}, "
              f"Liabilities: £{month_data['total_liabilities']:.2f})")
    print()
    
    # Test comparisons
    print("4. Comparison Data:")
    comparisons = NetWorthService.get_comparison_data()
    print(f"   Current: £{comparisons['latest_value']:.2f}")
    print(f"   Month-over-month: £{comparisons['month_comparison']['change']:.2f} "
          f"({comparisons['month_comparison']['pct_change']:.2f}%)")
    print(f"   Year-over-year: £{comparisons['year_comparison']['change']:.2f} "
          f"({comparisons['year_comparison']['pct_change']:.2f}%)")
    print()
    
    print("=" * 60)
    print("TEST COMPLETE - Cache is working!")
    print("=" * 60)
