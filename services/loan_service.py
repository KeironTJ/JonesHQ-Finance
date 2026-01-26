from models.loans import Loan
from extensions import db
from datetime import datetime


class LoanService:
    @staticmethod
    def calculate_remaining_balance(loan_id):
        """Calculate remaining balance on a loan"""
        pass
    
    @staticmethod
    def calculate_total_interest(loan_id):
        """Calculate total interest to be paid over life of loan"""
        pass
    
    @staticmethod
    def generate_amortization_schedule(loan_id):
        """Generate amortization schedule for a loan"""
        pass
    
    @staticmethod
    def calculate_payoff_date(loan_id, extra_payment=0):
        """Calculate payoff date with optional extra payments"""
        pass
