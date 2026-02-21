"""
Routes for vendor management
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from blueprints.vendors import bp
from extensions import db
from models import Vendor, Category, VendorType
from models.settings import Settings
from services.payday_service import PaydayService
from datetime import datetime, timedelta
from decimal import Decimal
import json
from sqlalchemy import func
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id

DEFAULT_VENDOR_TYPES = [
    'Grocery', 'Fuel', 'Restaurant', 'Online Retailer',
    'Utility', 'Insurance', 'Bank', 'Government',
    'Entertainment', 'Healthcare', 'Education', 'Other'
]

@bp.route('/')
def index():
    """List all vendors"""
    from models.transactions import Transaction
    
    vendor_type = request.args.get('type')
    search = request.args.get('search')
    sort_by = request.args.get('sort', 'usage')  # Default sort by usage
    
    query = family_query(Vendor)
    
    if vendor_type:
        if vendor_type.lower() == 'uncategorized':
            query = query.filter(Vendor.vendor_type_id.is_(None))
        else:
            query = query.join(VendorType, isouter=True).filter(func.lower(VendorType.name) == vendor_type.lower())
    
    if search:
        query = query.filter(Vendor.name.ilike(f'%{search}%'))
    
    vendors = query.all()
    
    # Add transaction count to each vendor
    for vendor in vendors:
        vendor.transaction_count = family_query(Transaction).filter_by(vendor_id=vendor.id).count()
    
    # Sort vendors
    if sort_by == 'usage':
        vendors = sorted(vendors, key=lambda v: v.transaction_count, reverse=True)
    elif sort_by == 'name':
        vendors = sorted(vendors, key=lambda v: v.name.lower())
    
    # Get vendor types for filter
    vendor_types = family_query(VendorType).order_by(VendorType.sort_order.nulls_last(), VendorType.name).all()

    collapse_all_default = Settings.get_value('vendors.collapse_all_default', False)
    
    return render_template('vendors/vendors.html', 
                         vendors=vendors,
                         vendor_types=vendor_types,
                         current_type=vendor_type,
                         current_search=search,
                         current_sort=sort_by,
                         collapse_all_default=collapse_all_default)


@bp.route('/types')
def types_index():
    """Manage vendor types"""
    vendor_types = family_query(VendorType).order_by(VendorType.sort_order.nulls_last(), VendorType.name).all()
    type_counts = {
        vt.id: family_query(Vendor).filter_by(vendor_type_id=vt.id).count()
        for vt in vendor_types
    }
    return render_template(
        'vendors/types.html',
        vendor_types=vendor_types,
        type_counts=type_counts,
        has_types=bool(vendor_types),
        default_types=DEFAULT_VENDOR_TYPES,
    )


@bp.route('/types/add', methods=['POST'])
def add_type():
    """Add a vendor type"""
    name = (request.form.get('name') or '').strip()
    sort_order = request.form.get('sort_order')
    is_active = request.form.get('is_active') == '1'

    if not name:
        flash('Vendor type name is required.', 'danger')
        return redirect(url_for('vendors.types_index'))

    existing = family_query(VendorType).filter(func.lower(VendorType.name) == name.lower()).first()
    if existing:
        flash(f'Vendor type "{name}" already exists.', 'warning')
        return redirect(url_for('vendors.types_index'))

    vendor_type = VendorType(
        name=name,
        is_active=is_active,
        sort_order=int(sort_order) if sort_order else None,
    )
    db.session.add(vendor_type)
    db.session.commit()

    flash(f'Vendor type "{name}" added.', 'success')
    return redirect(url_for('vendors.types_index'))


@bp.route('/types/<int:type_id>/update', methods=['POST'])
def update_type(type_id):
    """Update a vendor type"""
    vendor_type = family_get_or_404(VendorType, type_id)
    name = (request.form.get('name') or '').strip()
    sort_order = request.form.get('sort_order')
    is_active = request.form.get('is_active') == '1'

    if not name:
        flash('Vendor type name is required.', 'danger')
        return redirect(url_for('vendors.types_index'))

    existing = family_query(VendorType).filter(func.lower(VendorType.name) == name.lower(), VendorType.id != type_id).first()
    if existing:
        flash(f'Vendor type "{name}" already exists.', 'warning')
        return redirect(url_for('vendors.types_index'))

    vendor_type.name = name
    vendor_type.is_active = is_active
    vendor_type.sort_order = int(sort_order) if sort_order else None
    db.session.commit()

    flash(f'Vendor type "{name}" updated.', 'success')
    return redirect(url_for('vendors.types_index'))


@bp.route('/types/<int:type_id>/delete', methods=['POST'])
def delete_type(type_id):
    """Delete a vendor type if unused"""
    vendor_type = family_get_or_404(VendorType, type_id)
    usage_count = family_query(Vendor).filter_by(vendor_type_id=vendor_type.id).count()
    if usage_count > 0:
        flash('Cannot delete a vendor type that is in use.', 'warning')
        return redirect(url_for('vendors.types_index'))

    db.session.delete(vendor_type)
    db.session.commit()
    flash(f'Vendor type "{vendor_type.name}" deleted.', 'success')
    return redirect(url_for('vendors.types_index'))


@bp.route('/types/seed', methods=['POST'])
def seed_types():
    """Seed default vendor types if none exist"""
    if family_query(VendorType).count() > 0:
        flash('Vendor types already exist.', 'info')
        return redirect(url_for('vendors.types_index'))

    for index, name in enumerate(DEFAULT_VENDOR_TYPES, start=1):
        db.session.add(VendorType(name=name, is_active=True, sort_order=index))
    db.session.commit()

    flash('Default vendor types added.', 'success')
    return redirect(url_for('vendors.types_index'))


@bp.route('/analytics')
def analytics():
    """Vendor analytics with payday period filters"""
    view_mode = request.args.get('view_mode', 'payday')

    if view_mode == 'monthly':
        return _analytics_monthly()

    from models.transactions import Transaction

    include_future = '1' in request.args.getlist('include_future')
    periods = PaydayService.get_recent_periods(num_periods=18, include_future=include_future)
    period_labels = [p['label'] for p in periods]
    period_display = {p['label']: p['display_name'] for p in periods}

    default_end = period_labels[-1] if period_labels else None
    default_start = period_labels[-6] if period_labels and len(period_labels) >= 6 else (period_labels[0] if period_labels else None)

    start_period = request.args.get('start_period', default_start)
    end_period = request.args.get('end_period', default_end)
    paid_only_values = request.args.getlist('paid_only')
    paid_only = True if not paid_only_values else ('1' in paid_only_values)

    if start_period not in period_labels:
        start_period = default_start
    if end_period not in period_labels:
        end_period = default_end

    if start_period and end_period and start_period > end_period:
        start_period, end_period = end_period, start_period

    filtered_labels = [label for label in period_labels if start_period and end_period and start_period <= label <= end_period]

    query = family_query(Transaction).join(Vendor).filter(Transaction.payday_period.isnot(None))

    if paid_only:
        query = query.filter(Transaction.is_paid.is_(True))

    if start_period and end_period:
        query = query.filter(
            Transaction.payday_period >= start_period,
            Transaction.payday_period <= end_period
        )

    transactions = query.all()

    category_data = {}
    period_totals = {label: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for label in filtered_labels}
    vendor_totals = {}
    total_transactions = 0
    total_income = Decimal('0.00')
    total_expense = Decimal('0.00')

    for txn in transactions:
        period_label = txn.payday_period
        if period_label not in period_totals:
            continue

        vendor = txn.vendor
        if not vendor:
            continue

        head_group = vendor.vendor_type_rel.name if vendor.vendor_type_rel else (vendor.vendor_type or 'Uncategorized')
        vendor_name = vendor.name

        amount_value = Decimal(str(txn.amount))
        income_value = amount_value if amount_value >= 0 else Decimal('0.00')
        expense_value = (amount_value * Decimal('-1')) if amount_value < 0 else Decimal('0.00')

        if head_group not in category_data:
            category_data[head_group] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'total_count': 0,
                'periods': {label: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for label in filtered_labels},
                'subcategories': {}
            }

        if vendor_name not in category_data[head_group]['subcategories']:
            category_data[head_group]['subcategories'][vendor_name] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'total_count': 0,
                'periods': {label: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for label in filtered_labels}
            }

        if vendor_name not in vendor_totals:
            vendor_totals[vendor_name] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'periods': {label: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for label in filtered_labels}
            }

        category_data[head_group]['total_income'] += income_value
        category_data[head_group]['total_expense'] += expense_value
        category_data[head_group]['total_count'] += 1
        category_data[head_group]['periods'][period_label]['income'] += income_value
        category_data[head_group]['periods'][period_label]['expense'] += expense_value

        category_data[head_group]['subcategories'][vendor_name]['total_income'] += income_value
        category_data[head_group]['subcategories'][vendor_name]['total_expense'] += expense_value
        category_data[head_group]['subcategories'][vendor_name]['total_count'] += 1
        category_data[head_group]['subcategories'][vendor_name]['periods'][period_label]['income'] += income_value
        category_data[head_group]['subcategories'][vendor_name]['periods'][period_label]['expense'] += expense_value

        vendor_totals[vendor_name]['total_income'] += income_value
        vendor_totals[vendor_name]['total_expense'] += expense_value
        vendor_totals[vendor_name]['periods'][period_label]['income'] += income_value
        vendor_totals[vendor_name]['periods'][period_label]['expense'] += expense_value

        period_totals[period_label]['income'] += income_value
        period_totals[period_label]['expense'] += expense_value
        total_transactions += 1
        total_income += income_value
        total_expense += expense_value

    sorted_groups = sorted(
        category_data.items(),
        key=lambda x: x[1]['total_income'] + x[1]['total_expense'],
        reverse=True
    )

    sorted_vendors = sorted(
        vendor_totals.items(),
        key=lambda x: x[1]['total_income'] + x[1]['total_expense'],
        reverse=True
    )
    chart_vendors = [vendor for vendor, _ in sorted_vendors[:6]]

    chart_labels = [period_display.get(label, label) for label in filtered_labels]
    income_datasets = []
    expense_datasets = []

    for vendor_name in chart_vendors:
        vendor_data = vendor_totals[vendor_name]
        income_datasets.append({
            'label': f"{vendor_name} (Income)",
            'data': [float(vendor_data['periods'][label]['income']) for label in filtered_labels]
        })
        expense_datasets.append({
            'label': f"{vendor_name} (Expense)",
            'data': [float(vendor_data['periods'][label]['expense']) for label in filtered_labels]
        })

    if len(sorted_vendors) > len(chart_vendors):
        other_vendors = [vendor for vendor, _ in sorted_vendors][len(chart_vendors):]
        other_income = []
        other_expense = []
        for label in filtered_labels:
            income_sum = sum([vendor_totals[v]['periods'][label]['income'] for v in other_vendors], Decimal('0.00'))
            expense_sum = sum([vendor_totals[v]['periods'][label]['expense'] for v in other_vendors], Decimal('0.00'))
            other_income.append(float(income_sum))
            other_expense.append(float(expense_sum))
        income_datasets.append({'label': 'Other (Income)', 'data': other_income})
        expense_datasets.append({'label': 'Other (Expense)', 'data': other_expense})

    chart_payload = json.dumps({
        'labels': chart_labels,
        'income_datasets': income_datasets,
        'expense_datasets': expense_datasets
    })

    net_total = total_income - total_expense
    average_per_period = (net_total / len(filtered_labels)) if filtered_labels else Decimal('0.00')

    return render_template(
        'vendors/analytics.html',
        view_mode='payday',
        periods=periods,
        period_display=period_display,
        period_labels=filtered_labels,
        start_period=start_period,
        end_period=end_period,
        paid_only=paid_only,
        include_future=include_future,
        category_data=sorted_groups,
        period_totals=period_totals,
        total_income=total_income,
        total_expense=total_expense,
        net_total=net_total,
        total_transactions=total_transactions,
        average_per_period=average_per_period,
        chart_payload=chart_payload
    )


def _analytics_monthly():
    """Monthly view with month-on-month vendor comparison"""
    from dateutil.relativedelta import relativedelta
    from models.transactions import Transaction

    paid_only_values = request.args.getlist('paid_only')
    paid_only = True if not paid_only_values else ('1' in paid_only_values)
    num_months = int(request.args.get('num_months', '12'))
    future_months = int(request.args.get('future_months', '0'))

    today = datetime.now()
    months = []
    for i in range(num_months - 1, -future_months - 1, -1):
        month_date = today - relativedelta(months=i)
        months.append({
            'key': month_date.strftime('%Y-%m'),
            'label': month_date.strftime('%b %Y'),
            'start': month_date.replace(day=1),
            'end': (month_date.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        })

    query = family_query(Transaction).join(Vendor).filter(Transaction.transaction_date.isnot(None))

    if paid_only:
        query = query.filter(Transaction.is_paid.is_(True))

    if months:
        query = query.filter(
            Transaction.transaction_date >= months[0]['start'],
            Transaction.transaction_date <= months[-1]['end']
        )

    transactions = query.all()

    category_data = {}
    month_totals = {month['key']: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for month in months}
    vendor_totals = {}
    total_income = Decimal('0.00')
    total_expense = Decimal('0.00')

    for txn in transactions:
        if not txn.transaction_date:
            continue

        month_key = txn.transaction_date.strftime('%Y-%m')
        if month_key not in month_totals:
            continue

        vendor = txn.vendor
        if not vendor:
            continue

        head_group = vendor.vendor_type_rel.name if vendor.vendor_type_rel else (vendor.vendor_type or 'Uncategorized')
        vendor_name = vendor.name

        amount_value = Decimal(str(txn.amount))
        income_value = amount_value if amount_value >= 0 else Decimal('0.00')
        expense_value = (amount_value * Decimal('-1')) if amount_value < 0 else Decimal('0.00')

        if head_group not in category_data:
            category_data[head_group] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'months': {month['key']: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for month in months},
                'subcategories': {}
            }

        if vendor_name not in category_data[head_group]['subcategories']:
            category_data[head_group]['subcategories'][vendor_name] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'months': {month['key']: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for month in months}
            }

        if vendor_name not in vendor_totals:
            vendor_totals[vendor_name] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'months': {month['key']: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for month in months}
            }

        category_data[head_group]['total_income'] += income_value
        category_data[head_group]['total_expense'] += expense_value
        category_data[head_group]['months'][month_key]['income'] += income_value
        category_data[head_group]['months'][month_key]['expense'] += expense_value

        category_data[head_group]['subcategories'][vendor_name]['total_income'] += income_value
        category_data[head_group]['subcategories'][vendor_name]['total_expense'] += expense_value
        category_data[head_group]['subcategories'][vendor_name]['months'][month_key]['income'] += income_value
        category_data[head_group]['subcategories'][vendor_name]['months'][month_key]['expense'] += expense_value

        vendor_totals[vendor_name]['total_income'] += income_value
        vendor_totals[vendor_name]['total_expense'] += expense_value
        vendor_totals[vendor_name]['months'][month_key]['income'] += income_value
        vendor_totals[vendor_name]['months'][month_key]['expense'] += expense_value

        month_totals[month_key]['income'] += income_value
        month_totals[month_key]['expense'] += expense_value
        total_income += income_value
        total_expense += expense_value

    sorted_groups = sorted(
        category_data.items(),
        key=lambda x: x[1]['total_income'] + x[1]['total_expense'],
        reverse=True
    )

    sorted_vendors = sorted(
        vendor_totals.items(),
        key=lambda x: x[1]['total_income'] + x[1]['total_expense'],
        reverse=True
    )
    chart_vendors = [vendor for vendor, _ in sorted_vendors[:6]]

    chart_labels = [month['label'] for month in months]
    income_datasets = []
    expense_datasets = []

    for vendor_name in chart_vendors:
        vendor_data = vendor_totals[vendor_name]
        income_datasets.append({
            'label': f"{vendor_name} (Income)",
            'data': [float(vendor_data['months'][month['key']]['income']) for month in months]
        })
        expense_datasets.append({
            'label': f"{vendor_name} (Expense)",
            'data': [float(vendor_data['months'][month['key']]['expense']) for month in months]
        })

    if len(sorted_vendors) > len(chart_vendors):
        other_vendors = [vendor for vendor, _ in sorted_vendors][len(chart_vendors):]
        other_income = []
        other_expense = []
        for month in months:
            month_key = month['key']
            income_sum = sum([vendor_totals[v]['months'][month_key]['income'] for v in other_vendors], Decimal('0.00'))
            expense_sum = sum([vendor_totals[v]['months'][month_key]['expense'] for v in other_vendors], Decimal('0.00'))
            other_income.append(float(income_sum))
            other_expense.append(float(expense_sum))
        income_datasets.append({'label': 'Other (Income)', 'data': other_income})
        expense_datasets.append({'label': 'Other (Expense)', 'data': other_expense})

    chart_payload = json.dumps({
        'labels': chart_labels,
        'income_datasets': income_datasets,
        'expense_datasets': expense_datasets
    })

    net_total = total_income - total_expense

    return render_template(
        'vendors/analytics.html',
        view_mode='monthly',
        paid_only=paid_only,
        num_months=num_months,
        future_months=future_months,
        months=months,
        category_data=sorted_groups,
        month_totals=month_totals,
        total_income=total_income,
        total_expense=total_expense,
        net_total=net_total,
        chart_payload=chart_payload
    )

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new vendor"""
    if request.method == 'POST':
        name = request.form.get('name')
        vendor_type = request.form.get('vendor_type')
        default_category_id = request.form.get('default_category_id')
        website = request.form.get('website')
        notes = request.form.get('notes')
        vendor_type_id = int(vendor_type) if vendor_type else None
        
        # Check if vendor already exists
        existing = family_query(Vendor).filter_by(name=name).first()
        
        if existing:
            flash(f'Vendor "{name}" already exists!', 'warning')
        else:
            vendor = Vendor(
                name=name,
                vendor_type_id=vendor_type_id,
                vendor_type=vendor_type if vendor_type else None,
                default_category_id=int(default_category_id) if default_category_id else None,
                website=website if website else None,
                notes=notes if notes else None
            )
            
            db.session.add(vendor)
            db.session.commit()
            
            flash(f'Vendor "{name}" added successfully!', 'success')
            return redirect(url_for('vendors.index'))
    
    # Get categories for dropdown
    categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    
    vendor_types = family_query(VendorType).filter_by(is_active=True).order_by(VendorType.sort_order.nulls_last(), VendorType.name).all()
    
    return render_template('vendors/add.html', 
                         categories=categories,
                         vendor_types=vendor_types)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    """Edit an existing vendor"""
    vendor = family_get_or_404(Vendor, id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        vendor_type = request.form.get('vendor_type')
        default_category_id = request.form.get('default_category_id')
        website = request.form.get('website')
        notes = request.form.get('notes')
        is_active = request.form.get('is_active') == 'on'
        vendor_type_id = int(vendor_type) if vendor_type else None
        
        # Check if updated name conflicts
        existing = family_query(Vendor).filter(Vendor.id != id, Vendor.name == name).first()
        
        if existing:
            flash(f'Vendor name "{name}" is already taken!', 'warning')
        else:
            vendor.name = name
            vendor.vendor_type_id = vendor_type_id
            vendor.vendor_type = vendor_type if vendor_type else None
            vendor.default_category_id = int(default_category_id) if default_category_id else None
            vendor.website = website if website else None
            vendor.notes = notes if notes else None
            vendor.is_active = is_active
            vendor.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            flash(f'Vendor "{name}" updated successfully!', 'success')
            return redirect(url_for('vendors.index'))
    
    # Get categories for dropdown
    categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    
    # Predefined vendor types
    vendor_types = [
        'Grocery', 'Fuel', 'Restaurant', 'Online Retailer', 
        'Utility', 'Insurance', 'Bank', 'Government',
        'Entertainment', 'Healthcare', 'Education', 'Other'
    ]
    
    vendor_types = family_query(VendorType).order_by(VendorType.sort_order.nulls_last(), VendorType.name).all()
    return render_template('vendors/edit.html',
                         vendor=vendor,
                         categories=categories,
                         vendor_types=vendor_types)

@bp.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    """Delete a vendor"""
    vendor = family_get_or_404(Vendor, id)
    
    # Check if vendor is being used
    transaction_count = vendor.transactions.count()
    
    if transaction_count > 0:
        flash(f'Cannot delete "{vendor.name}" - it has {transaction_count} transaction(s)!', 'danger')
    else:
        name = vendor.name
        db.session.delete(vendor)
        db.session.commit()
        flash(f'Vendor "{name}" deleted successfully!', 'success')
    
    return redirect(url_for('vendors.index'))

@bp.route('/api/search')
def api_search():
    """API endpoint for vendor autocomplete"""
    query = request.args.get('q', '')
    
    if not query:
        return jsonify([])
    
    vendors = family_query(Vendor).filter(
        Vendor.name.ilike(f'%{query}%'),
        Vendor.is_active == True
    ).limit(10).all()
    
    return jsonify([{
        'id': v.id,
        'name': v.name,
        'vendor_type': v.vendor_type_rel.name if v.vendor_type_rel else v.vendor_type,
        'default_category_id': v.default_category_id
    } for v in vendors])

@bp.route('/api/stats')
def api_stats():
    """API endpoint for vendor statistics"""
    vendor_id = request.args.get('vendor_id')
    
    if not vendor_id:
        return jsonify({'error': 'vendor_id required'}), 400
    
    vendor = family_get_or_404(Vendor, vendor_id)
    
    return jsonify(vendor.to_dict())
