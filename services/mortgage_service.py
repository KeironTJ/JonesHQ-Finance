from models.mortgage import Mortgage
from extensions import db
from datetime import datetime


class MortgageService:
    @staticmethod
    def calculate_remaining_balance(mortgage_id):
        """Calculate remaining balance on mortgage"""
        pass
    
    @staticmethod
    def generate_amortization_schedule(mortgage_id):
        """Generate amortization schedule"""
        pass
    
    @staticmethod
    def calculate_equity(mortgage_id, property_value):
        """Calculate home equity"""
        pass
    
    @staticmethod
    def calculate_early_payoff(mortgage_id, extra_payment):
        """Calculate impact of extra payments"""
        pass
