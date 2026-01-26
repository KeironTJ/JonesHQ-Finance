from models.budgets import Budget
from models.transactions import Transaction
from extensions import db


class BudgetService:
    @staticmethod
    def get_budget_status(budget_id):
        """Get current status of a budget including spent vs allocated"""
        pass
    
    @staticmethod
    def create_budget(category_id, amount, period_start, period_end):
        """Create a new budget"""
        pass
    
    @staticmethod
    def check_budget_alerts(user_id=None):
        """Check for budgets that are close to or over limit"""
        pass
