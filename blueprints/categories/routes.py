"""
Routes for category management
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from blueprints.categories import bp
from extensions import db
from models import Category
from datetime import datetime

@bp.route('/')
def index():
    """List all categories grouped by head budget"""
    from models.transactions import Transaction
    
    # Get all head budgets
    head_budgets = db.session.query(Category.head_budget).distinct().order_by(Category.head_budget).all()
    
    # Organize categories by head budget with transaction counts
    categories_by_head = {}
    for (head_budget,) in head_budgets:
        categories = Category.query.filter_by(head_budget=head_budget).order_by(Category.sub_budget).all()
        
        # Add transaction count to each category
        for category in categories:
            category.transaction_count = Transaction.query.filter_by(category_id=category.id).count()
        
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
    
    return render_template('categories/categories.html', 
                         categories_by_head=categories_by_head)

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new category"""
    if request.method == 'POST':
        head_budget = request.form.get('head_budget')
        sub_budget = request.form.get('sub_budget')
        category_type = request.form.get('category_type')
        
        # Check if category already exists
        existing = Category.query.filter_by(
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
    head_budgets = db.session.query(Category.head_budget).distinct().order_by(Category.head_budget).all()
    existing_heads = [h[0] for h in head_budgets]
    
    return render_template('categories/add.html', existing_heads=existing_heads)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    """Edit an existing category"""
    category = Category.query.get_or_404(id)
    
    if request.method == 'POST':
        head_budget = request.form.get('head_budget')
        sub_budget = request.form.get('sub_budget')
        category_type = request.form.get('category_type')
        
        # Check if updated category conflicts with existing
        existing = Category.query.filter(
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
    head_budgets = db.session.query(Category.head_budget).distinct().order_by(Category.head_budget).all()
    existing_heads = [h[0] for h in head_budgets]
    
    return render_template('categories/edit.html', category=category, existing_heads=existing_heads)

@bp.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    """Delete a category"""
    category = Category.query.get_or_404(id)
    
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
    categories = Category.query.filter_by(head_budget=head_budget).all()
    subcategories = [cat.sub_budget for cat in categories if cat.sub_budget]
    return jsonify(subcategories)
