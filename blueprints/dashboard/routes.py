from flask import render_template, request, redirect, url_for
from flask_login import current_user
from . import dashboard_bp
from services.analytics.dashboard_service import DashboardService
from models.settings import Settings
from services.platform.preference_service import PreferenceService
from datetime import date


@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
def index():
    """Main dashboard view with payday tracking"""
    if not current_user.is_authenticated:
        return redirect(url_for('auth.intro'))

    # Get settings
    payday_day = Settings.get_value('payday_day', 15)
    
    selected_account_id = request.args.get('account_id', type=int)
    
    # Get selected year (default to current year)
    today = date.today()
    selected_year = request.args.get('year', type=int, default=today.year)
    
    dashboard_data = DashboardService.get_dashboard_data(selected_account_id, selected_year)
    onboarding_incomplete = (
        current_user.onboarding_version < 1
        or (
            current_user.is_household_owner
            and current_user.family
            and current_user.family.onboarding_version < 1
        )
    )
    
    return render_template('dashboard/index.html',
                         accounts=dashboard_data['accounts'],
                         selected_account=dashboard_data['selected_account'],
                         payday_data=dashboard_data['payday_data'],
                         payday_day=payday_day,
                         selected_year=selected_year,
                         current_year=today.year,
                         today=today,
                         networth=dashboard_data['networth'],
                         credit_card_summary=dashboard_data['credit_card_summary'],
                         loan_summary=dashboard_data['loan_summary'],
                         mortgage_summary=dashboard_data['mortgage_summary'],
                         pension_summary=dashboard_data['pension_summary'],
                         onboarding_incomplete=onboarding_incomplete,
                         networth_expanded=PreferenceService.get_value('dashboard.networth_expanded'),
                         account_selection_expanded=PreferenceService.get_value('dashboard.account_selection_expanded'),
                         payday_expanded=PreferenceService.get_value('dashboard.payday_expanded'),
                         summaries_expanded=PreferenceService.get_value('dashboard.summaries_expanded'),
                         quick_nav_expanded=PreferenceService.get_value('dashboard.quick_nav_expanded'))
