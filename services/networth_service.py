from models.networth import NetWorth
from models.accounts import Account
from models.loans import Loan
from models.mortgage import Mortgage
from extensions import db


class NetWorthService:
    @staticmethod
    def calculate_current_networth():
        """Calculate current net worth from all accounts and liabilities"""
        pass
    
    @staticmethod
    def get_networth_history(days=365):
        """Get net worth history for specified period"""
        pass
    
    @staticmethod
    def save_networth_snapshot():
        """Save a snapshot of current net worth"""
        pass
    
    @staticmethod
    def get_networth_trend():
        """Analyze net worth trend over time"""
        pass
