"""
Routes for category management
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from blueprints.categories import bp
from extensions import db
from models import Category
from models.settings import Settings
from models.transactions import Transaction
from services.payday_service import PaydayService
from datetime import datetime
from decimal import Decimal
import json
from sqlalchemy import func
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id

@bp.route('/')
def index():
    """List all categories grouped by head budget"""
    from models.transactions import Transaction
    
    # Get all head budgets
    head_budgets = family_query(Category).with_entities(Category.head_budget).distinct().order_by(Category.head_budget).all()
    
    # Organize categories by head budget with transaction counts
    categories_by_head = {}
    for (head_budget,) in head_budgets:
        categories = family_query(Category).filter_by(head_budget=head_budget).order_by(Category.sub_budget).all()
        
        # Add transaction count to each category
        for category in categories:
            category.transaction_count = family_query(Transaction).filter_by(category_id=category.id).count()
        
        # Calculate total for head budget
        head_transaction_count = sum(c.transaction_count for c in categories)
        
        categories_by_head[head_budget] = {
            'categories': categories,
            'total_count': head_transaction_count
        }
    
    # Sort by transaction count (descending)
    categories_by_head = dict(sorted(categories_by_head.items(), 
                                     key=lambda x: x[1]['total_count'], 
                                     reverse=True))

    collapse_all_default = Settings.get_value('categories.collapse_all_default', False)
    
    return render_template('categories/categories.html', 
                         categories_by_head=categories_by_head,
                         collapse_all_default=collapse_all_default)

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new category"""
    if request.method == 'POST':
        head_budget = request.form.get('head_budget')
        sub_budget = request.form.get('sub_budget')
        category_type = request.form.get('category_type')
        
        # Check if category already exists
        existing = family_query(Category).filter_by(
            head_budget=head_budget,
            sub_budget=sub_budget if sub_budget else None
        ).first()
        
        if existing:
            flash(f'Category "{head_budget} - {sub_budget}" already exists!', 'warning')
        else:
            # Create new category
            name = f"{head_budget}"
            if sub_budget:
                name += f" - {sub_budget}"
            
            category = Category(
                name=name,
                head_budget=head_budget,
                sub_budget=sub_budget if sub_budget else None,
                category_type=category_type
            )
            
            db.session.add(category)
            db.session.commit()
            
            flash(f'Category "{name}" added successfully!', 'success')
            return redirect(url_for('categories.index'))
    
    # Get existing head budgets for dropdown
    head_budgets = family_query(Category).with_entities(Category.head_budget).distinct().order_by(Category.head_budget).all()
    existing_heads = [h[0] for h in head_budgets]
    
    return render_template('categories/add.html', existing_heads=existing_heads)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    """Edit an existing category"""
    category = family_get_or_404(Category, id)
    
    if request.method == 'POST':
        head_budget = request.form.get('head_budget')
        sub_budget = request.form.get('sub_budget')
        category_type = request.form.get('category_type')
        
        # Check if updated category conflicts with existing
        existing = family_query(Category).filter(
            Category.id != id,
            Category.head_budget == head_budget,
            Category.sub_budget == (sub_budget if sub_budget else None)
        ).first()
        
        if existing:
            flash(f'Category "{head_budget} - {sub_budget}" already exists!', 'warning')
        else:
            # Update category
            category.head_budget = head_budget
            category.sub_budget = sub_budget if sub_budget else None
            category.category_type = category_type
            category.name = f"{head_budget}" + (f" - {sub_budget}" if sub_budget else "")
            category.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            flash(f'Category "{category.name}" updated successfully!', 'success')
            return redirect(url_for('categories.index'))
    
    # Get existing head budgets for dropdown
    head_budgets = family_query(Category).with_entities(Category.head_budget).distinct().order_by(Category.head_budget).all()
    existing_heads = [h[0] for h in head_budgets]
    
    return render_template('categories/edit.html', category=category, existing_heads=existing_heads)

@bp.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    """Delete a category"""
    category = family_get_or_404(Category, id)
    
    # Check if category is being used
    if category.transactions:
        flash(f'Cannot delete "{category.name}" - it has {len(category.transactions)} transactions!', 'danger')
    elif category.budgets:
        flash(f'Cannot delete "{category.name}" - it has {len(category.budgets)} budgets!', 'danger')
    else:
        name = category.name
        db.session.delete(category)
        db.session.commit()
        flash(f'Category "{name}" deleted successfully!', 'success')
    
    return redirect(url_for('categories.index'))

@bp.route('/api/subcategories/<head_budget>')
def get_subcategories(head_budget):
    """API endpoint to get sub-categories for a head budget"""
    categories = family_query(Category).filter_by(head_budget=head_budget).all()
    subcategories = [cat.sub_budget for cat in categories if cat.sub_budget]
    return jsonify(subcategories)


@bp.route('/analytics')
def analytics():
    """Category spending analytics with payday period filters"""
    view_mode = request.args.get('view_mode', 'payday')  # 'payday' or 'monthly'
    
    if view_mode == 'monthly':
        return _analytics_monthly()
    
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

    query = family_query(Transaction).join(Category).filter(
        Transaction.payday_period.isnot(None),
        func.lower(Category.category_type).in_(['income', 'expense'])
    )

    if paid_only:
        query = query.filter(Transaction.is_paid.is_(True))

    if start_period and end_period:
        query = query.filter(
            Transaction.payday_period >= start_period,
            Transaction.payday_period <= end_period
        )

    transactions = query.all()

    # Build hierarchical structure: head_budget -> sub_budget -> period -> totals
    category_data = {}
    period_totals = {label: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for label in filtered_labels}
    total_transactions = 0
    total_income = Decimal('0.00')
    total_expense = Decimal('0.00')

    for txn in transactions:
        period_label = txn.payday_period
        if period_label not in period_totals:
            continue

        category = txn.category
        head_budget = category.head_budget or 'Uncategorized'
        sub_budget = category.sub_budget or 'General'

        amount_value = Decimal(str(txn.amount))
        income_value = amount_value if amount_value >= 0 else Decimal('0.00')
        expense_value = (amount_value * Decimal('-1')) if amount_value < 0 else Decimal('0.00')

        # Initialize category structure
        if head_budget not in category_data:
            category_data[head_budget] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'total_count': 0,
                'periods': {label: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for label in filtered_labels},
                'subcategories': {}
            }

        if sub_budget not in category_data[head_budget]['subcategories']:
            category_data[head_budget]['subcategories'][sub_budget] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'total_count': 0,
                'periods': {label: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for label in filtered_labels}
            }

        # Aggregate
        category_data[head_budget]['total_income'] += income_value
        category_data[head_budget]['total_expense'] += expense_value
        category_data[head_budget]['total_count'] += 1
        category_data[head_budget]['periods'][period_label]['income'] += income_value
        category_data[head_budget]['periods'][period_label]['expense'] += expense_value

        category_data[head_budget]['subcategories'][sub_budget]['total_income'] += income_value
        category_data[head_budget]['subcategories'][sub_budget]['total_expense'] += expense_value
        category_data[head_budget]['subcategories'][sub_budget]['total_count'] += 1
        category_data[head_budget]['subcategories'][sub_budget]['periods'][period_label]['income'] += income_value
        category_data[head_budget]['subcategories'][sub_budget]['periods'][period_label]['expense'] += expense_value

        period_totals[period_label]['income'] += income_value
        period_totals[period_label]['expense'] += expense_value
        total_transactions += 1
        total_income += income_value
        total_expense += expense_value

    # Sort categories by total activity
    sorted_categories = sorted(
        category_data.items(),
        key=lambda x: x[1]['total_income'] + x[1]['total_expense'],
        reverse=True
    )
    
    chart_heads = [cat for cat, _ in sorted_categories[:6]]

    chart_labels = [period_display.get(label, label) for label in filtered_labels]
    chart_keys = filtered_labels
    income_datasets = []
    expense_datasets = []

    for head in chart_heads:
        cat_data = category_data[head]
        income_datasets.append({
            'label': f"{head} (Income)",
            'data': [float(cat_data['periods'][label]['income']) for label in chart_keys]
        })
        expense_datasets.append({
            'label': f"{head} (Expense)",
            'data': [float(cat_data['periods'][label]['expense']) for label in chart_keys]
        })

    if len(sorted_categories) > len(chart_heads):
        other_cats = [cat for cat, _ in sorted_categories][len(chart_heads):]
        other_income = []
        other_expense = []
        for label in chart_keys:
            income_sum = sum([category_data[cat]['periods'][label]['income'] for cat in other_cats], Decimal('0.00'))
            expense_sum = sum([category_data[cat]['periods'][label]['expense'] for cat in other_cats], Decimal('0.00'))
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
        'categories/analytics.html',
        view_mode='payday',
        periods=periods,
        period_display=period_display,
        period_labels=filtered_labels,
        start_period=start_period,
        end_period=end_period,
        paid_only=paid_only,
        include_future=include_future,
        category_data=sorted_categories,
        period_totals=period_totals,
        total_income=total_income,
        total_expense=total_expense,
        net_total=net_total,
        total_transactions=total_transactions,
        average_per_period=average_per_period,
        chart_payload=chart_payload
    )

def _analytics_monthly():
    """Monthly view with month-on-month comparison"""
    from datetime import datetime, timedelta
    from dateutil.relativedelta import relativedelta
    
    paid_only_values = request.args.getlist('paid_only')
    paid_only = True if not paid_only_values else ('1' in paid_only_values)
    num_months = int(request.args.get('num_months', '12'))
    future_months = int(request.args.get('future_months', '0'))
    
    # Generate list of months
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
    
    query = family_query(Transaction).join(Category).filter(
        Transaction.transaction_date.isnot(None),
        func.lower(Category.category_type).in_(['income', 'expense'])
    )
    
    if paid_only:
        query = query.filter(Transaction.is_paid.is_(True))
    
    # Filter by date range
    if months:
        query = query.filter(
            Transaction.transaction_date >= months[0]['start'],
            Transaction.transaction_date <= months[-1]['end']
        )
    
    transactions = query.all()
    
    # Build hierarchical structure: head_budget -> sub_budget -> month -> totals
    category_data = {}
    month_totals = {month['key']: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for month in months}
    total_income = Decimal('0.00')
    total_expense = Decimal('0.00')
    
    for txn in transactions:
        if not txn.transaction_date:
            continue
            
        month_key = txn.transaction_date.strftime('%Y-%m')
        if month_key not in month_totals:
            continue
        
        category = txn.category
        head_budget = category.head_budget or 'Uncategorized'
        sub_budget = category.sub_budget or 'General'
        
        amount_value = Decimal(str(txn.amount))
        income_value = amount_value if amount_value >= 0 else Decimal('0.00')
        expense_value = (amount_value * Decimal('-1')) if amount_value < 0 else Decimal('0.00')
        
        # Initialize category structure
        if head_budget not in category_data:
            category_data[head_budget] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'months': {month['key']: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for month in months},
                'subcategories': {}
            }
        
        if sub_budget not in category_data[head_budget]['subcategories']:
            category_data[head_budget]['subcategories'][sub_budget] = {
                'total_income': Decimal('0.00'),
                'total_expense': Decimal('0.00'),
                'months': {month['key']: {'income': Decimal('0.00'), 'expense': Decimal('0.00')} for month in months}
            }
        
        # Aggregate
        category_data[head_budget]['total_income'] += income_value
        category_data[head_budget]['total_expense'] += expense_value
        category_data[head_budget]['months'][month_key]['income'] += income_value
        category_data[head_budget]['months'][month_key]['expense'] += expense_value
        
        category_data[head_budget]['subcategories'][sub_budget]['total_income'] += income_value
        category_data[head_budget]['subcategories'][sub_budget]['total_expense'] += expense_value
        category_data[head_budget]['subcategories'][sub_budget]['months'][month_key]['income'] += income_value
        category_data[head_budget]['subcategories'][sub_budget]['months'][month_key]['expense'] += expense_value
        
        month_totals[month_key]['income'] += income_value
        month_totals[month_key]['expense'] += expense_value
        total_income += income_value
        total_expense += expense_value
    
    # Sort categories by total activity (income + expense)
    sorted_categories = sorted(
        category_data.items(),
        key=lambda x: x[1]['total_income'] + x[1]['total_expense'],
        reverse=True
    )
    
    # Build chart data (top 6 categories)
    chart_categories = [cat for cat, _ in sorted_categories[:6]]
    chart_labels = [month['label'] for month in months]
    income_datasets = []
    expense_datasets = []
    
    for cat_name in chart_categories:
        cat_data = category_data[cat_name]
        income_datasets.append({
            'label': f"{cat_name} (Income)",
            'data': [float(cat_data['months'][month['key']]['income']) for month in months]
        })
        expense_datasets.append({
            'label': f"{cat_name} (Expense)",
            'data': [float(cat_data['months'][month['key']]['expense']) for month in months]
        })
    
    chart_payload = json.dumps({
        'labels': chart_labels,
        'income_datasets': income_datasets,
        'expense_datasets': expense_datasets
    })
    
    net_total = total_income - total_expense
    
    return render_template(
        'categories/analytics.html',
        view_mode='monthly',
        paid_only=paid_only,
        num_months=num_months,
        future_months=future_months,
        months=months,
        category_data=sorted_categories,
        month_totals=month_totals,
        total_income=total_income,
        total_expense=total_expense,
        net_total=net_total,
        chart_payload=chart_payload
    )
