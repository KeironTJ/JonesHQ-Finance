from models.childcare import ChildcareRecord
from extensions import db


class ChildcareService:
    @staticmethod
    def get_monthly_costs(child_name=None):
        """Get monthly childcare costs"""
        pass
    
    @staticmethod
    def get_annual_costs(year, child_name=None):
        """Get annual childcare costs for a specific year"""
        pass
    
    @staticmethod
    def get_costs_by_provider(provider):
        """Get costs grouped by provider"""
        pass
