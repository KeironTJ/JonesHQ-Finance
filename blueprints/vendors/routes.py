"""
Routes for vendor management
"""
from flask import render_template, request, redirect, url_for, flash, jsonify
from blueprints.vendors import bp
from extensions import db
from models import Vendor, Category
from datetime import datetime

@bp.route('/')
def index():
    """List all vendors"""
    vendor_type = request.args.get('type')
    search = request.args.get('search')
    
    query = Vendor.query
    
    if vendor_type:
        query = query.filter_by(vendor_type=vendor_type)
    
    if search:
        query = query.filter(Vendor.name.ilike(f'%{search}%'))
    
    vendors = query.order_by(Vendor.name).all()
    
    # Get vendor types for filter
    vendor_types = db.session.query(Vendor.vendor_type).distinct().filter(Vendor.vendor_type.isnot(None)).all()
    vendor_types = [t[0] for t in vendor_types]
    
    return render_template('vendors/vendors.html', 
                         vendors=vendors,
                         vendor_types=vendor_types,
                         current_type=vendor_type,
                         current_search=search)

@bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new vendor"""
    if request.method == 'POST':
        name = request.form.get('name')
        vendor_type = request.form.get('vendor_type')
        default_category_id = request.form.get('default_category_id')
        website = request.form.get('website')
        notes = request.form.get('notes')
        
        # Check if vendor already exists
        existing = Vendor.query.filter_by(name=name).first()
        
        if existing:
            flash(f'Vendor "{name}" already exists!', 'warning')
        else:
            vendor = Vendor(
                name=name,
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
    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    
    # Predefined vendor types
    vendor_types = [
        'Grocery', 'Fuel', 'Restaurant', 'Online Retailer', 
        'Utility', 'Insurance', 'Bank', 'Government',
        'Entertainment', 'Healthcare', 'Education', 'Other'
    ]
    
    return render_template('vendors/add.html', 
                         categories=categories,
                         vendor_types=vendor_types)

@bp.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit(id):
    """Edit an existing vendor"""
    vendor = Vendor.query.get_or_404(id)
    
    if request.method == 'POST':
        name = request.form.get('name')
        vendor_type = request.form.get('vendor_type')
        default_category_id = request.form.get('default_category_id')
        website = request.form.get('website')
        notes = request.form.get('notes')
        is_active = request.form.get('is_active') == 'on'
        
        # Check if updated name conflicts
        existing = Vendor.query.filter(Vendor.id != id, Vendor.name == name).first()
        
        if existing:
            flash(f'Vendor name "{name}" is already taken!', 'warning')
        else:
            vendor.name = name
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
    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    
    # Predefined vendor types
    vendor_types = [
        'Grocery', 'Fuel', 'Restaurant', 'Online Retailer', 
        'Utility', 'Insurance', 'Bank', 'Government',
        'Entertainment', 'Healthcare', 'Education', 'Other'
    ]
    
    return render_template('vendors/edit.html', 
                         vendor=vendor,
                         categories=categories,
                         vendor_types=vendor_types)

@bp.route('/delete/<int:id>', methods=['POST'])
def delete(id):
    """Delete a vendor"""
    vendor = Vendor.query.get_or_404(id)
    
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
    
    vendors = Vendor.query.filter(
        Vendor.name.ilike(f'%{query}%'),
        Vendor.is_active == True
    ).limit(10).all()
    
    return jsonify([{
        'id': v.id,
        'name': v.name,
        'vendor_type': v.vendor_type,
        'default_category_id': v.default_category_id
    } for v in vendors])

@bp.route('/api/stats')
def api_stats():
    """API endpoint for vendor statistics"""
    vendor_id = request.args.get('vendor_id')
    
    if not vendor_id:
        return jsonify({'error': 'vendor_id required'}), 400
    
    vendor = Vendor.query.get_or_404(vendor_id)
    
    return jsonify(vendor.to_dict())
