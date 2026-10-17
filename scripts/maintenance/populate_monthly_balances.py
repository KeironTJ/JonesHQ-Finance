"""
Populate Monthly Account Balance Cache
Runs the initial population of the monthly_account_balances table
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from app import create_app
from services.finance.monthly_balance_service import MonthlyBalanceService

def main():
    """Populate the monthly account balance cache"""
    app = create_app()
    
    with app.app_context():
        print("=" * 60)
        print("MONTHLY ACCOUNT BALANCE CACHE POPULATION")
        print("=" * 60)
        print()
        
        print("This rebuilds the monthly_account_balances cache for the signed-in")
        print("household only. Without a signed-in user it does nothing; use the")
        print("Net Worth page's 'Refresh cache' button in each household instead.")
        print()
        
        response = input("Continue? (y/n): ")
        if response.lower() != 'y':
            print("Aborted")
            return
        
        print()
        MonthlyBalanceService.rebuild_all_cache()
        print()
        print("=" * 60)
        print("CACHE POPULATION COMPLETE")
        print("=" * 60)

if __name__ == '__main__':
    main()
