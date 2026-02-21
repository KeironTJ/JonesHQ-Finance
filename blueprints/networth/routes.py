from flask import render_template, request, redirect, url_for, flash, jsonify
from . import networth_bp
from models.networth import NetWorth
from services.networth_service import NetWorthService
from extensions import db
from datetime import date
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


@networth_bp.route('/networth')
def index():
    """View net worth timeline"""
    from datetime import date
    from dateutil.relativedelta import relativedelta
    
    # Get year and period from query params
    selected_year = request.args.get('year', type=int)
    period_months = request.args.get('period', type=int, default=24)  # Default 24 months
    
    # Limit period to reasonable range (1-240 months = 20 years)
    period_months = max(1, min(period_months, 240))
    
    # Get current calculated values for header (uses cached balances)
    current_values = NetWorthService.calculate_current_networth()
    
    # Get monthly timeline
    if selected_year:
        # If specific year selected, show that year (12 months)
        timeline = NetWorthService.get_monthly_timeline(selected_year, 1, 12)
    else:
        # Default: show period starting from 12 months ago
        selected_year = date.today().year
        timeline = NetWorthService.get_monthly_timeline(None, None, period_months)
    
    # Get trend analysis (12 months)
    trend = NetWorthService.get_networth_trend()
    
    # Get month-over-month and year-over-year comparisons
    comparison = NetWorthService.get_comparison_data()
    
    # Get historical snapshots (if any exist)
    records = family_query(NetWorth).order_by(NetWorth.date.desc()).limit(50).all()
    
    return render_template('networth/index.html', 
                         current_values=current_values,
                         timeline=timeline,
                         records=records,
                         trend=trend,
                         comparison=comparison,
                         selected_year=selected_year,
                         current_year=date.today().year,
                         period_months=period_months)


@networth_bp.route('/networth/snapshot', methods=['POST'])
def create_snapshot():
    """Create a new net worth snapshot"""
    try:
        # Get date from form, or use today
        snapshot_date_str = request.form.get('snapshot_date')
        if snapshot_date_str:
            from datetime import datetime
            snapshot_date = datetime.strptime(snapshot_date_str, '%Y-%m-%d').date()
        else:
            snapshot_date = date.today()
        
        # Create snapshot
        snapshot = NetWorthService.save_networth_snapshot(snapshot_date)
        
        flash(f'Net worth snapshot created for {snapshot_date}', 'success')
    except Exception as e:
        flash(f'Error creating snapshot: {str(e)}', 'danger')
    
    return redirect(url_for('networth.index'))


@networth_bp.route('/networth/<int:id>/delete', methods=['POST'])
def delete_snapshot(id):
    """Delete a net worth snapshot"""
    try:
        snapshot = family_get_or_404(NetWorth, id)
        db.session.delete(snapshot)
        db.session.commit()
        flash('Snapshot deleted successfully', 'success')
    except Exception as e:
        flash(f'Error deleting snapshot: {str(e)}', 'danger')
    
    return redirect(url_for('networth.index'))


@networth_bp.route('/networth/api/current', methods=['GET'])
def api_current():
    """API endpoint to get current net worth calculation"""
    values = NetWorthService.calculate_current_networth()
    return jsonify(values)


@networth_bp.route('/networth/refresh-cache', methods=['POST'])
def refresh_cache():
    """Manually refresh the monthly account balance cache"""
    try:
        from services.monthly_balance_service import MonthlyBalanceService
        
        # Get optional future_months parameter (default 24)
        future_months = request.form.get('future_months', type=int, default=24)
        future_months = max(12, min(future_months, 240))  # Between 12 and 240 months
        
        # Update the service to use this parameter
        MonthlyBalanceService.rebuild_all_cache(future_months=future_months)
        
        flash(f'Cache refreshed successfully (projecting {future_months} months into the future)', 'success')
    except Exception as e:
        flash(f'Error refreshing cache: {str(e)}', 'danger')
    
    return redirect(url_for('networth.index'))
