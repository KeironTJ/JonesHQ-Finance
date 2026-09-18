from decimal import Decimal

from models.accounts import Account
from models.transactions import Transaction
from models.credit_cards import CreditCard
from models.loans import Loan
from models.mortgage import MortgageProduct
from models.pensions import Pension
from models.settings import Settings
from services.networth_service import NetWorthService
from services.payday_service import PaydayService
from utils.db_helpers import family_get, family_query


class DashboardService:
    @staticmethod
    def get_dashboard_data(selected_account_id=None, selected_year=None):
        accounts = family_query(Account).filter_by(
            is_active=True
        ).order_by(Account.name).all()
        if not selected_account_id:
            joint_account = family_query(Account).filter_by(
                account_type='Joint', is_active=True
            ).first()
            if joint_account:
                selected_account_id = joint_account.id

        for account in accounts:
            paid_transactions = family_query(Transaction).filter_by(
                account_id=account.id,
                is_paid=True,
            ).all()
            account.calculated_balance = float(sum(
                (Decimal(str(transaction.amount)) for transaction in paid_transactions),
                Decimal('0.00'),
            ))

        selected_account = family_get(Account, selected_account_id) if selected_account_id else None
        payday_data = (
            PaydayService.get_payday_summary_for_year(
                selected_account_id, selected_year, include_unpaid=True
            )
            if selected_account_id and selected_year else []
        )

        credit_cards = family_query(CreditCard).filter_by(is_active=True).all()
        credit_card_summary = {
            'count': len(credit_cards),
            'total_balance': sum(Decimal(str(card.current_balance or 0)) for card in credit_cards),
            'total_limit': sum(Decimal(str(card.credit_limit or 0)) for card in credit_cards),
            'total_available': sum(Decimal(str(card.available_credit or 0)) for card in credit_cards),
        }

        loans = family_query(Loan).filter_by(is_active=True).all()
        loan_summary = {
            'count': len(loans),
            'total_balance': sum(Decimal(str(loan.current_balance or 0)) for loan in loans),
            'total_monthly_payment': sum(Decimal(str(loan.monthly_payment or 0)) for loan in loans),
        }

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

        pensions = family_query(Pension).filter_by(is_active=True).all()
        pension_summary = {
            'count': len(pensions),
            'total_current_value': sum(Decimal(str(pension.current_value or 0)) for pension in pensions),
            'total_projected_value': sum(
                Decimal(str(pension.projected_value_at_retirement or 0))
                for pension in pensions
            ),
        }

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
