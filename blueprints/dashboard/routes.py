from flask import render_template, request
from . import dashboard_bp
from models.accounts import Account
from services.payday_service import PaydayService
from models.settings import Settings


@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
def index():
    """Main dashboard view with payday tracking"""
    # Get settings
    payday_day = Settings.get_value('payday_day', 15)
    
    # Get account to track (default to first active Joint account)
    selected_account_id = request.args.get('account_id', type=int)
    
    if not selected_account_id:
        # Default to first Joint account
        joint_account = Account.query.filter_by(account_type='Joint', is_active=True).first()
        if joint_account:
            selected_account_id = joint_account.id
    
    # Get all active accounts for selector
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    
    # Get payday summary
    payday_data = []
    selected_account = None
    
    if selected_account_id:
        selected_account = Account.query.get(selected_account_id)
        # Get 12 months of payday data (including unpaid transactions)
        payday_data = PaydayService.get_payday_summary(selected_account_id, num_periods=12, include_unpaid=True)
    
    return render_template('dashboard/index.html',
                         accounts=accounts,
                         selected_account=selected_account,
                         payday_data=payday_data,
                         payday_day=payday_day)
