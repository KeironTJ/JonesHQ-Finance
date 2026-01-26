from models.transactions import Transaction
from models.planned import PlannedTransaction
from datetime import datetime, timedelta


class ForecastingService:
    @staticmethod
    def forecast_balance(account_id, days_ahead=30):
        """Forecast account balance based on planned transactions"""
        pass
    
    @staticmethod
    def predict_spending(category_id, period_days=30):
        """Predict spending for a category based on historical data"""
        pass
    
    @staticmethod
    def calculate_runway(current_balance, monthly_expenses):
        """Calculate how long funds will last at current spending rate"""
        pass
