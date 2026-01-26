from models.pensions import Pension
from extensions import db


class PensionService:
    @staticmethod
    def project_retirement_value(pension_id, years_until_retirement):
        """Project pension value at retirement"""
        pass
    
    @staticmethod
    def calculate_total_contributions(pension_id, years):
        """Calculate total contributions over time"""
        pass
    
    @staticmethod
    def get_total_pension_value():
        """Get total value across all pensions"""
        pass
