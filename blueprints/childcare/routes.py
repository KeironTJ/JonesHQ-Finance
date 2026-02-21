from flask import render_template, request, redirect, url_for, flash, jsonify
from . import childcare_bp
from models.childcare import Child, ChildActivityType, DailyChildcareActivity, MonthlyChildcareSummary
from models.accounts import Account
from models.transactions import Transaction
from services.childcare_service import ChildcareService
from extensions import db
from datetime import datetime, date
from decimal import Decimal
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


@childcare_bp.route('/childcare')
def index():
    """Main childcare tracking page - calendar view"""
    # Get current month or from query params
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    # Get calendar data
    calendar_data, children = ChildcareService.get_monthly_calendar(year, month)
    
    # Get monthly totals
    monthly_totals = ChildcareService.get_monthly_totals(year, month)
    
    # Get all accounts for transaction creation
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    
    # Check for existing monthly summaries/transactions
    year_month = f"{year}-{month:02d}"
    summaries = family_query(MonthlyChildcareSummary).filter_by(year_month=year_month).all()
    
    # Clear transaction_id from summaries where the transaction no longer exists
    for summary in summaries:
        if summary.transaction_id:
            transaction_exists = family_get(Transaction, summary.transaction_id)
            if not transaction_exists:
                summary.transaction_id = None
                db.session.commit()
    
    return render_template(
        'childcare/index.html',
        calendar_data=calendar_data,
        children=children,
        monthly_totals=monthly_totals,
        accounts=accounts,
        summaries=summaries,
        current_year=year,
        current_month=month,
        year_month=year_month
    )


@childcare_bp.route('/childcare/update_activity', methods=['POST'])
def update_activity():
    """Update a single activity (checkbox toggle)"""
    from calendar import monthrange
    
    data = request.get_json()
    
    activity_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
    child_id = int(data['child_id'])
    activity_type_id = int(data['activity_type_id'])
    occurred = data['occurred']
    
    activity = ChildcareService.update_daily_activity(
        activity_date,
        child_id,
        activity_type_id,
        occurred
    )
    
    # Recalculate daily total for this child
    day_activities = family_query(DailyChildcareActivity).filter_by(
        date=activity_date,
        child_id=child_id,
        occurred=True
    ).all()
    
    daily_total = sum([a.actual_cost for a in day_activities], Decimal('0'))
    
    # Calculate monthly total for this child - use proper date range
    year = activity_date.year
    month = activity_date.month
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    
    month_activities = family_query(DailyChildcareActivity).filter(
        DailyChildcareActivity.child_id == child_id,
        DailyChildcareActivity.date >= first_day,
        DailyChildcareActivity.date <= last_day,
        DailyChildcareActivity.occurred == True
    ).all()
    
    monthly_total = sum([a.actual_cost for a in month_activities], Decimal('0'))
    
    return jsonify({
        'success': True,
        'daily_total': float(daily_total),
        'monthly_total': float(monthly_total),
        'cost': float(activity.actual_cost)
    })


@childcare_bp.route('/childcare/create_transaction/<int:child_id>', methods=['POST'])
def create_transaction(child_id):
    """Create a transaction for a child's monthly childcare costs"""
    year = int(request.form.get('year'))
    month = int(request.form.get('month'))
    account_id = int(request.form.get('account_id'))
    
    transaction = ChildcareService.create_monthly_transaction(year, month, child_id, account_id)
    
    if transaction:
        flash(f'Transaction created: {transaction.description} - £{abs(transaction.amount):.2f}', 'success')
    else:
        flash('No costs to create transaction for this month', 'warning')
    
    return redirect(url_for('childcare.index', year=year, month=month))


@childcare_bp.route('/childcare/update_transaction', methods=['POST'])
def update_transaction():
    """Update an existing transaction amount when childcare schedule changes"""
    from models.transactions import Transaction
    
    data = request.get_json()
    transaction_id = int(data['transaction_id'])
    child_id = int(data['child_id'])
    new_amount = Decimal(str(data['new_amount']))
    
    try:
        # Get the transaction
        transaction = family_get(Transaction, transaction_id)
        if not transaction:
            return jsonify({'success': False, 'error': 'Transaction not found'})
        
        # Update the amount (negative because it's an expense)
        transaction.amount = -new_amount
        
        # Update the monthly summary
        summary = family_query(MonthlyChildcareSummary).filter_by(
            transaction_id=transaction_id,
            child_id=child_id
        ).first()
        
        if summary:
            summary.total_cost = new_amount
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'new_amount': float(new_amount),
            'message': 'Transaction updated successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@childcare_bp.route('/childcare/set_default_account', methods=['POST'])
def set_default_account():
    """Save default account for a child"""
    data = request.get_json()
    child_id = int(data['child_id'])
    account_id = int(data['account_id'])
    
    try:
        child = family_get(Child, child_id)
        if child:
            child.default_account_id = account_id
            db.session.commit()
            return jsonify({'success': True})
        return jsonify({'success': False, 'error': 'Child not found'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@childcare_bp.route('/childcare/bulk_create_transactions', methods=['POST'])
def bulk_create_transactions():
    """Create transactions for multiple children at once"""
    data = request.get_json()
    year = int(data['year'])
    month = int(data['month'])
    transactions_data = data['transactions']
    
    try:
        created_count = 0
        for trans_data in transactions_data:
            child_id = trans_data['child_id']
            account_id = trans_data['account_id']
            
            # Check if transaction already exists
            year_month = f"{year}-{month:02d}"
            existing_summary = family_query(MonthlyChildcareSummary).filter_by(
                year_month=year_month,
                child_id=child_id
            ).first()
            
            if not existing_summary or not existing_summary.transaction_id:
                transaction = ChildcareService.create_monthly_transaction(year, month, child_id, account_id)
                if transaction:
                    created_count += 1
        
        db.session.commit()
        return jsonify({
            'success': True,
            'created': created_count,
            'message': f'{created_count} transactions created successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)})


@childcare_bp.route('/childcare/setup')
def setup():
    """Setup page for managing children and activity types"""
    from models.categories import Category
    from models.vendors import Vendor
    
    children = family_query(Child).order_by(Child.sort_order, Child.name).all()
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    categories = family_query(Category).filter(
        db.func.lower(Category.category_type) == 'expense'
    ).order_by(Category.head_budget, Category.sub_budget).all()
    vendors = family_query(Vendor).filter_by(is_active=True).order_by(Vendor.name).all()
    
    # Get activity types for each child
    children_with_activities = []
    for child in children:
        activity_types = family_query(ChildActivityType).filter_by(child_id=child.id).order_by(ChildActivityType.sort_order, ChildActivityType.name).all()
        children_with_activities.append({
            'child': child,
            'activity_types': activity_types
        })
    
    return render_template(
        'childcare/setup.html',
        children_with_activities=children_with_activities,
        accounts=accounts,
        categories=categories,
        vendors=vendors
    )


@childcare_bp.route('/childcare/add_child', methods=['POST'])
def add_child():
    """Add a new child"""
    name = request.form.get('name')
    year_group = request.form.get('year_group')
    transaction_day = int(request.form.get('transaction_day', 28))
    
    # Validate transaction day
    if transaction_day < 1 or transaction_day > 28:
        transaction_day = 28
    
    if not name:
        flash('Child name is required', 'danger')
        return redirect(url_for('childcare.setup'))
    
    # Check if child already exists
    existing = family_query(Child).filter_by(name=name).first()
    if existing:
        flash(f'{name} already exists', 'warning')
        return redirect(url_for('childcare.setup'))
    
    child = Child(name=name, year_group=year_group, transaction_day=transaction_day)
    
    # Add category and vendor if provided
    category_id = request.form.get('category_id')
    vendor_id = request.form.get('vendor_id')
    
    if category_id:
        child.category_id = int(category_id)
    if vendor_id:
        child.vendor_id = int(vendor_id)
    
    db.session.add(child)
    db.session.commit()
    
    flash(f'Added child: {name}', 'success')
    return redirect(url_for('childcare.setup'))


@childcare_bp.route('/childcare/update_child/<int:child_id>', methods=['POST'])
def update_child(child_id):
    """Update child details"""
    child = family_get_or_404(Child, child_id)
    
    child.name = request.form.get('name', child.name)
    child.year_group = request.form.get('year_group', child.year_group)
    child.is_active = request.form.get('is_active') == 'on'
    
    # Update transaction day
    transaction_day = request.form.get('transaction_day')
    if transaction_day:
        transaction_day = int(transaction_day)
        if 1 <= transaction_day <= 28:
            child.transaction_day = transaction_day
    
    # Update category and vendor
    category_id = request.form.get('category_id')
    vendor_id = request.form.get('vendor_id')
    
    if category_id:
        child.category_id = int(category_id) if category_id else None
    if vendor_id:
        child.vendor_id = int(vendor_id) if vendor_id else None
    
    db.session.commit()
    flash(f'Updated {child.name}', 'success')
    return redirect(url_for('childcare.setup'))


@childcare_bp.route('/childcare/delete_child/<int:child_id>', methods=['POST'])
def delete_child(child_id):
    """Delete a child (and all their data)"""
    child = family_get_or_404(Child, child_id)
    name = child.name
    
    db.session.delete(child)
    db.session.commit()
    
    flash(f'Deleted {name} and all associated data', 'success')
    return redirect(url_for('childcare.setup'))


@childcare_bp.route('/childcare/add_activity_type/<int:child_id>', methods=['POST'])
def add_activity_type(child_id):
    """Add an activity type for a child"""
    child = family_get_or_404(Child, child_id)
    
    name = request.form.get('name')
    cost = request.form.get('cost', type=float)
    provider = request.form.get('provider')
    
    if not name or cost is None:
        flash('Activity name and cost are required', 'danger')
        return redirect(url_for('childcare.setup'))
    
    activity_type = ChildActivityType(
        child_id=child_id,
        name=name,
        cost=cost,
        provider=provider,
        occurs_monday=request.form.get('occurs_monday') == 'on',
        occurs_tuesday=request.form.get('occurs_tuesday') == 'on',
        occurs_wednesday=request.form.get('occurs_wednesday') == 'on',
        occurs_thursday=request.form.get('occurs_thursday') == 'on',
        occurs_friday=request.form.get('occurs_friday') == 'on',
        occurs_saturday=request.form.get('occurs_saturday') == 'on',
        occurs_sunday=request.form.get('occurs_sunday') == 'on'
    )
    db.session.add(activity_type)
    db.session.commit()
    
    flash(f'Added activity: {name} for {child.name}', 'success')
    return redirect(url_for('childcare.setup'))


@childcare_bp.route('/childcare/update_activity_type/<int:activity_type_id>', methods=['POST'])
def update_activity_type(activity_type_id):
    """Update an activity type"""
    activity_type = family_get_or_404(ChildActivityType, activity_type_id)
    
    activity_type.name = request.form.get('name', activity_type.name)
    activity_type.cost = request.form.get('cost', type=float, default=activity_type.cost)
    activity_type.provider = request.form.get('provider', activity_type.provider)
    activity_type.is_active = request.form.get('is_active') == 'on'
    activity_type.occurs_monday = request.form.get('occurs_monday') == 'on'
    activity_type.occurs_tuesday = request.form.get('occurs_tuesday') == 'on'
    activity_type.occurs_wednesday = request.form.get('occurs_wednesday') == 'on'
    activity_type.occurs_thursday = request.form.get('occurs_thursday') == 'on'
    activity_type.occurs_friday = request.form.get('occurs_friday') == 'on'
    activity_type.occurs_saturday = request.form.get('occurs_saturday') == 'on'
    activity_type.occurs_sunday = request.form.get('occurs_sunday') == 'on'
    
    db.session.commit()
    flash(f'Updated activity type: {activity_type.name}', 'success')
    return redirect(url_for('childcare.setup'))


@childcare_bp.route('/childcare/delete_activity_type/<int:activity_type_id>', methods=['POST'])
def delete_activity_type(activity_type_id):
    """Delete an activity type"""
    activity_type = family_get_or_404(ChildActivityType, activity_type_id)
    name = activity_type.name
    
    db.session.delete(activity_type)
    db.session.commit()
    
    flash(f'Deleted activity type: {name}', 'success')
    return redirect(url_for('childcare.setup'))


@childcare_bp.route('/childcare/reports')
def reports():
    """Annual and historical reports"""
    year = request.args.get('year', datetime.now().year, type=int)
    
    # Get annual totals
    annual_data = ChildcareService.get_annual_costs(year)
    
    # Get all years with data
    all_summaries = family_query(MonthlyChildcareSummary).all()
    years = sorted(list(set([int(s.year_month.split('-')[0]) for s in all_summaries])), reverse=True)
    
    return render_template(
        'childcare/reports.html',
        annual_data=annual_data,
        years=years,
        current_year=year
    )


@childcare_bp.route('/childcare/apply_templates', methods=['POST'])
def apply_templates():
    """Apply weekly templates to fill entire month"""
    year = int(request.form.get('year'))
    month = int(request.form.get('month'))
    
    count = ChildcareService.apply_templates_to_month(year, month)
    
    flash(f'Applied templates: {count} activities created', 'success')
    return redirect(url_for('childcare.index', year=year, month=month))


@childcare_bp.route('/childcare/copy_previous_month', methods=['POST'])
def copy_previous_month():
    """Copy previous month's activities to current month"""
    year = int(request.form.get('year'))
    month = int(request.form.get('month'))
    
    count = ChildcareService.copy_previous_month(year, month)
    
    flash(f'Copied {count} activities from previous month', 'success')
    return redirect(url_for('childcare.index', year=year, month=month))


@childcare_bp.route('/childcare/clear_month', methods=['POST'])
def clear_month():
    """Clear all activities for a month"""
    year = int(request.form.get('year'))
    month = int(request.form.get('month'))
    
    count = ChildcareService.clear_month(year, month)
    
    flash(f'Cleared {count} activities', 'warning')
    return redirect(url_for('childcare.index', year=year, month=month))
