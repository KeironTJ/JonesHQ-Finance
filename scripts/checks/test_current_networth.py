"""Test Current Net Worth with Cache"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.networth_service import NetWorthService

app = create_app()

with app.app_context():
    print("=" * 80)
    print("TESTING CURRENT NET WORTH (USING CACHE)")
    print("=" * 80)
    print()
    
    values = NetWorthService.calculate_current_networth()
    
    print("ASSETS:")
    print(f"  Cash:        £{values['cash']:,.2f}")
    print(f"  Savings:     £{values['savings']:,.2f}")
    print(f"  Pensions:    £{values['pensions_value']:,.2f}")
    print(f"  House:       £{values['house_value']:,.2f}")
    print(f"  TOTAL ASSETS: £{values['total_assets']:,.2f}")
    print()
    
    print("LIABILITIES:")
    print(f"  Credit Cards: £{values['credit_cards']:,.2f}")
    print(f"  Loans:        £{values['loans']:,.2f}")
    print(f"  Mortgage:     £{values['mortgage']:,.2f}")
    print(f"  TOTAL LIABILITIES: £{values['total_liabilities']:,.2f}")
    print()
    
    print("NET WORTH:")
    print(f"  Total Net Worth:  £{values['net_worth']:,.2f}")
    print(f"  Liquid Net Worth: £{values['liquid_net_worth']:,.2f}")
    print()
    
    print("ACCOUNT DETAILS:")
    for acc in values['account_details']:
        print(f"  {acc['name']} ({acc['type']}): £{acc['balance']:,.2f}")
    print()
    
    print("=" * 80)
