from flask import render_template, request, redirect, url_for, flash
from flask import jsonify
from . import settings_bp
from models.settings import Settings
from models.accounts import Account
from models.categories import Category
from models.vendors import Vendor
from models.tax_settings import TaxSettings
from extensions import db
from decimal import Decimal
from datetime import datetime
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


@settings_bp.route('/settings')
def index():
    """Display application settings"""
    # Get or create default settings
    default_generation_years = Settings.get_value('default_generation_years', 10)
    payday_day = Settings.get_value('payday_day', 15)
    
    # Expense settings
    expense_reimburse_account = Settings.get_value('expenses.reimburse_account_id')
    expense_payment_account = Settings.get_value('expenses.payment_account_id')
    expense_auto_sync = Settings.get_value('expenses.auto_sync', True)
    expense_period_mode = Settings.get_value('expenses.period_mode', 'calendar_month')
    expense_reimburse_category_id = Settings.get_value('expenses.reimburse_category_id')
    expense_reimburse_vendor_id   = Settings.get_value('expenses.reimburse_vendor_id')

    # Net Worth settings
    networth_start_date = Settings.get_value('networth.start_date', '')

    # Dashboard preferences
    networth_expanded = Settings.get_value('dashboard.networth_expanded', True)
    account_selection_expanded = Settings.get_value('dashboard.account_selection_expanded', True)
    payday_expanded = Settings.get_value('dashboard.payday_expanded', True)
    summaries_expanded = Settings.get_value('dashboard.summaries_expanded', True)
    quick_nav_expanded = Settings.get_value('dashboard.quick_nav_expanded', True)

    
    # Get all active accounts
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    vendors    = family_query(Vendor).order_by(Vendor.name).all()
    
    return render_template('settings/index.html',
                         default_generation_years=default_generation_years,
                         payday_day=payday_day,
                         expense_reimburse_account=int(expense_reimburse_account) if expense_reimburse_account else None,
                         expense_payment_account=int(expense_payment_account) if expense_payment_account else None,
                         expense_auto_sync=expense_auto_sync,
                         expense_period_mode=expense_period_mode,
                         expense_reimburse_category_id=int(expense_reimburse_category_id) if expense_reimburse_category_id else None,
                         expense_reimburse_vendor_id=int(expense_reimburse_vendor_id) if expense_reimburse_vendor_id else None,
                         accounts=accounts,
                         categories=categories,
                         vendors=vendors,
                         networth_start_date=networth_start_date,
                         networth_expanded=networth_expanded,
                         account_selection_expanded=account_selection_expanded,
                         payday_expanded=payday_expanded,
                         summaries_expanded=summaries_expanded,
                         quick_nav_expanded=quick_nav_expanded)


@settings_bp.route('/settings/update', methods=['POST'])
def update():
    """Update application settings"""
    try:
        # Credit Card Settings
        generation_years = int(request.form.get('default_generation_years', 10))
        
        # Payday Settings
        payday_day = int(request.form.get('payday_day', 15))
        
        # Validate
        if generation_years < 1 or generation_years > 50:
            flash('Generation period must be between 1 and 50 years!', 'danger')
            return redirect(url_for('settings.index'))
        
        if payday_day < 1 or payday_day > 31:
            flash('Payday must be between 1 and 31!', 'danger')
            return redirect(url_for('settings.index'))
        
        # Update settings
        Settings.set_value(
            'default_generation_years',
            generation_years,
            'Default number of years to generate future credit card transactions',
            'int'
        )
        
        Settings.set_value(
            'payday_day',
            payday_day,
            'Day of month when payday occurs (adjusted for weekends)',
            'int'
        )
        
        # Expense Settings
        expense_reimburse_account = request.form.get('expense_reimburse_account')
        expense_payment_account = request.form.get('expense_payment_account')
        expense_auto_sync = request.form.get('expense_auto_sync') == '1'
        
        if expense_reimburse_account:
            Settings.set_value(
                'expenses.reimburse_account_id',
                int(expense_reimburse_account),
                'Account where expense reimbursements are deposited',
                'int'
            )
        
        if expense_payment_account:
            Settings.set_value(
                'expenses.payment_account_id',
                int(expense_payment_account),
                'Default account for bank-paid expenses',
                'int'
            )
        
        Settings.set_value(
            'expenses.auto_sync',
            expense_auto_sync,
            'Automatically sync expense transactions',
            'bool'
        )

        expense_reimburse_category = request.form.get('expense_reimburse_category')
        if expense_reimburse_category:
            Settings.set_value('expenses.reimburse_category_id', int(expense_reimburse_category),
                               'Category for reimbursement/bank-expense transactions', 'int')
        expense_reimburse_vendor = request.form.get('expense_reimburse_vendor')
        if expense_reimburse_vendor:
            Settings.set_value('expenses.reimburse_vendor_id', int(expense_reimburse_vendor),
                               'Vendor for reimbursement/bank-expense transactions', 'int')

        expense_period_mode = request.form.get('expense_period_mode', 'calendar_month')
        if expense_period_mode not in ('calendar_month', 'payday_period'):
            expense_period_mode = 'calendar_month'
        Settings.set_value(
            'expenses.period_mode',
            expense_period_mode,
            'Expense accumulation period: calendar_month or payday_period',
            'string'
        )

        # Net Worth Settings
        networth_start_date_str = request.form.get('networth_start_date', '').strip()
        if networth_start_date_str:
            datetime.strptime(networth_start_date_str, '%Y-%m-%d')  # validate
            Settings.set_value(
                'networth.start_date',
                networth_start_date_str,
                'Earliest date to show on the net worth timeline',
                'date'
            )
        else:
            # Blank = clear the setting (revert to 5-year default)
            existing = Settings.query.filter_by(key='networth.start_date').first()
            if existing:
                db.session.delete(existing)

        # Dashboard Preferences
        networth_expanded = request.form.get('dashboard_networth_expanded') == '1'
        account_selection_expanded = request.form.get('dashboard_account_selection_expanded') == '1'
        payday_expanded = request.form.get('dashboard_payday_expanded') == '1'
        summaries_expanded = request.form.get('dashboard_summaries_expanded') == '1'
        quick_nav_expanded = request.form.get('dashboard_quick_nav_expanded') == '1'

        Settings.set_value(
            'dashboard.networth_expanded',
            networth_expanded,
            'Default expanded state for Net Worth Summary on dashboard',
            'boolean'
        )
        Settings.set_value(
            'dashboard.account_selection_expanded',
            account_selection_expanded,
            'Default expanded state for Account Selection on dashboard',
            'boolean'
        )
        Settings.set_value(
            'dashboard.payday_expanded',
            payday_expanded,
            'Default expanded state for Payday Period Tracking on dashboard',
            'boolean'
        )
        Settings.set_value(
            'dashboard.summaries_expanded',
            summaries_expanded,
            'Default expanded state for Financial Summaries on dashboard',
            'boolean'
        )
        Settings.set_value(
            'dashboard.quick_nav_expanded',
            quick_nav_expanded,
            'Default expanded state for Quick Navigation on dashboard',
            'boolean'
        )

        
        db.session.commit()
        flash(f'Settings updated successfully! Payday set to {payday_day} of each month.', 'success')
        
    except ValueError:
        db.session.rollback()
        flash('Invalid value provided!', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating settings: {str(e)}', 'danger')
    
    return redirect(url_for('settings.index'))


@settings_bp.route('/settings/save_preference', methods=['POST'])
def save_preference():
    """Save a lightweight user preference (AJAX)"""
    data = request.get_json() or {}
    key = data.get('key')
    value = data.get('value')

    if not key:
        return jsonify({'success': False, 'error': 'Missing preference key'}), 400

    setting_type = 'boolean' if isinstance(value, bool) else 'string'
    Settings.set_value(key, value, f'User preference: {key}', setting_type)
    db.session.commit()

    return jsonify({'success': True})


@settings_bp.route('/settings/tax')
def tax_settings():
    """Display tax and NI settings"""
    tax_years = family_query(TaxSettings).order_by(TaxSettings.effective_from.desc()).all()
    return render_template('settings/tax_settings.html', tax_years=tax_years)
        


@settings_bp.route('/settings/tax/<int:id>/edit', methods=['GET', 'POST'])
def edit_tax_settings(id):
    """Edit tax settings for a specific tax year"""
    tax_year = family_get_or_404(TaxSettings, id)
    
    if request.method == 'POST':
        try:
            # Update tax settings
            tax_year.personal_allowance = Decimal(request.form['personal_allowance'])
            tax_year.basic_rate_limit = Decimal(request.form['basic_rate_limit'])
            tax_year.higher_rate_limit = Decimal(request.form['higher_rate_limit'])
            tax_year.basic_rate = Decimal(request.form['basic_rate']) / 100  # Convert % to decimal
            tax_year.higher_rate = Decimal(request.form['higher_rate']) / 100
            tax_year.additional_rate = Decimal(request.form['additional_rate']) / 100
            
            # Update NI settings
            tax_year.ni_threshold = Decimal(request.form['ni_threshold'])
            tax_year.ni_upper_earnings = Decimal(request.form['ni_upper_earnings'])
            tax_year.ni_basic_rate = Decimal(request.form['ni_basic_rate']) / 100
            tax_year.ni_additional_rate = Decimal(request.form['ni_additional_rate']) / 100
            
            tax_year.notes = request.form.get('notes', '')
            tax_year.is_active = request.form.get('is_active') == 'on'
            
            db.session.commit()
            flash(f'Tax settings for {tax_year.tax_year} updated successfully!', 'success')
            return redirect(url_for('settings.tax_settings'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating tax settings: {str(e)}', 'danger')
    
    return render_template('settings/edit_tax_settings.html', tax_year=tax_year)
