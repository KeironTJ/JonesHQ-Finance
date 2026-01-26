from models.accounts import Account
from models.transactions import Transaction
from extensions import db


class AccountService:
    @staticmethod
    def get_account_balance(account_id):
        """Get current balance for an account"""
        pass
    
    @staticmethod
    def update_balance(account_id, new_balance):
        """Update account balance"""
        pass
    
    @staticmethod
    def get_account_transactions(account_id, start_date=None, end_date=None):
        """Get transactions for an account within date range"""
        pass
    
    @staticmethod
    def reconcile_account(account_id, statement_balance):
        """Reconcile account with statement balance"""
        pass
