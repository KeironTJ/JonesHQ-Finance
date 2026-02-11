from flask import render_template, request
from . import dashboard_bp
from models.accounts import Account
from models.transactions import Transaction
from models.credit_cards import CreditCard
from models.loans import Loan
from models.mortgage import MortgageProduct
from models.pensions import Pension
from services.payday_service import PaydayService
from services.networth_service import NetWorthService
from services.pension_service import PensionService
from models.settings import Settings
from datetime import date
from decimal import Decimal


@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
def index():
    """Main dashboard view with payday tracking"""
    # Get settings
    payday_day = Settings.get_value('payday_day', 15)
    
    # Get account to track (default to first active Joint account)
    selected_account_id = request.args.get('account_id', type=int)
    
    # Get selected year (default to current year)
    today = date.today()
    selected_year = request.args.get('year', type=int, default=today.year)
    
    if not selected_account_id:
        # Default to first Joint account
        joint_account = Account.query.filter_by(account_type='Joint', is_active=True).first()
        if joint_account:
            selected_account_id = joint_account.id
    
    # Get all active accounts for selector
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()

    # Calculate balances from PAID transactions for account cards
    for account in accounts:
        paid_transactions = Transaction.query.filter_by(
            account_id=account.id,
            is_paid=True
        ).all()
        balance = Decimal('0.00')
        for txn in paid_transactions:
            balance += Decimal(str(txn.amount))
        account.calculated_balance = float(balance)
    
    # Get payday summary
    payday_data = []
    selected_account = None
    
    if selected_account_id:
        selected_account = Account.query.get(selected_account_id)
        # Get 12 months of payday data for selected year (including unpaid transactions)
        # Start from January of selected year
        payday_data = PaydayService.get_payday_summary_for_year(selected_account_id, selected_year, include_unpaid=True)
    
    # Get current net worth
    networth = NetWorthService.calculate_current_networth()
    
    # Get Credit Cards Summary
    credit_cards = CreditCard.query.filter_by(is_active=True).all()
    credit_card_summary = {
        'count': len(credit_cards),
        'total_balance': sum(Decimal(str(cc.current_balance or 0)) for cc in credit_cards),
        'total_limit': sum(Decimal(str(cc.credit_limit or 0)) for cc in credit_cards),
        'total_available': sum(Decimal(str(cc.available_credit or 0)) for cc in credit_cards),
    }
    
    # Get Loans Summary
    loans = Loan.query.filter_by(is_active=True).all()
    loan_summary = {
        'count': len(loans),
        'total_balance': sum(Decimal(str(loan.current_balance or 0)) for loan in loans),
        'total_monthly_payment': sum(Decimal(str(loan.monthly_payment or 0)) for loan in loans),
    }
    
    # Get Mortgage Summary
    active_mortgage = MortgageProduct.query.filter_by(is_active=True, is_current=True).first()
    mortgage_summary = None
    if active_mortgage:
        mortgage_summary = {
            'lender': active_mortgage.lender,
            'product_name': active_mortgage.product_name,
            'current_balance': Decimal(str(active_mortgage.current_balance or 0)),
            'monthly_payment': Decimal(str(active_mortgage.monthly_payment or 0)),
            'annual_rate': Decimal(str(active_mortgage.annual_rate or 0)),
        }
    
    # Get Pensions Summary
    pensions = Pension.query.filter_by(is_active=True).all()
    pension_summary = {
        'count': len(pensions),
        'total_current_value': sum(Decimal(str(p.current_value or 0)) for p in pensions),
        'total_projected_value': sum(Decimal(str(p.projected_value_at_retirement or 0)) for p in pensions),
    }
    
    return render_template('dashboard/index.html',
                         accounts=accounts,
                         selected_account=selected_account,
                         payday_data=payday_data,
                         payday_day=payday_day,
                         selected_year=selected_year,
                         current_year=today.year,
                         networth=networth,
                         credit_card_summary=credit_card_summary,
                         loan_summary=loan_summary,
                         mortgage_summary=mortgage_summary,
                         pension_summary=pension_summary,
                         networth_expanded=Settings.get_value('dashboard.networth_expanded', True),
                         account_selection_expanded=Settings.get_value('dashboard.account_selection_expanded', True),
                         payday_expanded=Settings.get_value('dashboard.payday_expanded', True),
                         summaries_expanded=Settings.get_value('dashboard.summaries_expanded', True),
                         quick_nav_expanded=Settings.get_value('dashboard.quick_nav_expanded', True))
