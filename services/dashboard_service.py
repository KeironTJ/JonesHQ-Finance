from decimal import Decimal

from models.accounts import Account
from models.mortgage import MortgageProduct
from models.settings import Settings
from services.account_service import AccountService
from services.credit_card_service import CreditCardService
from services.loan_service import LoanService
from services.networth_service import NetWorthService
from services.payday_service import PaydayService
from services.pension_service import PensionService
from utils.db_helpers import family_get, family_query


class DashboardService:
    @staticmethod
    def get_dashboard_data(selected_account_id=None, selected_year=None):
        accounts = AccountService.get_active_accounts_with_balances()
        if not selected_account_id:
            joint_account = family_query(Account).filter_by(
                account_type='Joint', is_active=True
            ).first()
            if joint_account:
                selected_account_id = joint_account.id

        selected_account = family_get(Account, selected_account_id) if selected_account_id else None
        payday_data = (
            PaydayService.get_payday_summary_for_year(
                selected_account_id, selected_year, include_unpaid=True
            )
            if selected_account_id and selected_year else []
        )

        credit_card_summary = CreditCardService.get_summary()
        loan_summary = LoanService.get_summary()

        active_mortgage = family_query(MortgageProduct).filter_by(
            is_active=True, is_current=True
        ).first()
        mortgage_summary = None
        if active_mortgage:
            mortgage_summary = {
                'lender': active_mortgage.lender,
                'product_name': active_mortgage.product_name,
                'current_balance': Decimal(str(active_mortgage.current_balance or 0)),
                'monthly_payment': Decimal(str(active_mortgage.monthly_payment or 0)),
                'annual_rate': Decimal(str(active_mortgage.annual_rate or 0)),
            }

        pension_summary = PensionService.get_summary()

        return {
            'accounts': accounts,
            'selected_account': selected_account,
            'payday_data': payday_data,
            'networth': NetWorthService.calculate_current_networth(),
            'credit_card_summary': credit_card_summary,
            'loan_summary': loan_summary,
            'mortgage_summary': mortgage_summary,
            'pension_summary': pension_summary,
        }
