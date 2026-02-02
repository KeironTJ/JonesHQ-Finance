"""Quick check of monthly balance cache"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from models.monthly_account_balance import MonthlyAccountBalance
from models.accounts import Account
from extensions import db

app = create_app()

with app.app_context():
    # Count total cache entries
    total_entries = MonthlyAccountBalance.query.count()
    print(f"Total cache entries: {total_entries}")
    
    # Get accounts
    accounts = Account.query.filter_by(is_active=True).all()
    print(f"Active accounts: {len(accounts)}")
    
    # Show sample entries for first account
    if accounts:
        first_account = accounts[0]
        print(f"\nSample entries for '{first_account.name}':")
        
        entries = MonthlyAccountBalance.query.filter_by(
            account_id=first_account.id
        ).order_by(MonthlyAccountBalance.year_month.desc()).limit(5).all()
        
        for entry in entries:
            print(f"  {entry.year_month}: Actual={entry.actual_balance:.2f}, Projected={entry.projected_balance:.2f}")
    
    # Show months covered
    all_months = db.session.query(
        MonthlyAccountBalance.year_month
    ).distinct().order_by(MonthlyAccountBalance.year_month).all()
    
    print(f"\nMonths covered: {len(all_months)}")
    if all_months:
        print(f"  From: {all_months[0][0]}")
        print(f"  To: {all_months[-1][0]}")
