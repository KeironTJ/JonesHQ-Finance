from flask import render_template, request, redirect, url_for, flash, jsonify
from . import mortgage_bp
from models.property import Property
from models.mortgage import Mortgage, MortgageProduct
from models.mortgage_payments import MortgagePayment, MortgageSnapshot
from models.accounts import Account
from models.vendors import Vendor
from models.categories import Category
from services.mortgage_service import MortgageService
from extensions import db
from decimal import Decimal
from datetime import datetime
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


@mortgage_bp.route('/mortgage')
def index():
    """List all properties with their mortgages"""
    properties = family_query(Property).filter_by(is_active=True).all()
    
    # Calculate summary data for each property
    property_data = []
    for prop in properties:
        active_products = [p for p in prop.mortgage_products if p.is_active]
        total_balance = sum([p.current_balance for p in active_products])
        
        property_data.append({
            'property': prop,
            'total_balance': total_balance,
            'active_products': active_products,
            'ltv': MortgageService.calculate_ltv(prop.id)
        })
    
    return render_template('mortgage/index.html', property_data=property_data)


@mortgage_bp.route('/mortgage/property/<int:property_id>')
def property_detail(property_id):
    """View detailed information for a property"""
    prop = family_get_or_404(Property, property_id)
    products = family_query(MortgageProduct).filter_by(property_id=property_id).order_by(
        MortgageProduct.start_date
    ).all()
    
    return render_template('mortgage/property_detail.html', property=prop, products=products)


@mortgage_bp.route('/mortgage/property/<int:property_id>/projections')
def projections(property_id):
    """View Excel-style projection timeline"""
    prop = family_get_or_404(Property, property_id)
    
    # Get scenario from query params
    scenario = request.args.get('scenario', 'base')
    
    # Get timeline data
    timeline = MortgageService.get_combined_timeline(property_id, scenario)
    
    # Get available scenarios
    scenarios = family_query(MortgageSnapshot).with_entities(MortgageSnapshot.scenario_name).join(
        MortgageProduct
    ).filter(
        MortgageProduct.property_id == property_id,
        MortgageSnapshot.is_projection == True
    ).distinct().all()
    
    scenario_list = [s[0] for s in scenarios]
    
    return render_template('mortgage/projections.html', 
                         property=prop, 
                         timeline=timeline, 
                         current_scenario=scenario,
                         scenarios=scenario_list)


@mortgage_bp.route('/mortgage/property/<int:property_id>/comparison')
def scenario_comparison(property_id):
    """Compare different overpayment scenarios"""
    prop = family_get_or_404(Property, property_id)
    
    scenarios = MortgageService.get_scenario_comparison(property_id)
    
    return render_template('mortgage/comparison.html', 
                         property=prop, 
                         scenarios=scenarios)


@mortgage_bp.route('/mortgage/property/<int:property_id>/generate-projections', methods=['POST'])
def generate_projections(property_id):
    """Generate projections for all scenarios"""
    prop = family_get_or_404(Property, property_id)
    
    # Get scenario parameters from form
    scenarios = [
        {'name': 'base', 'overpayment': Decimal('0')},
    ]
    
    # Check if user wants overpayment scenarios
    aggressive_overpayment = request.form.get('aggressive_overpayment')
    if aggressive_overpayment:
        scenarios.append({
            'name': 'aggressive', 
            'overpayment': Decimal(str(aggressive_overpayment))
        })
    
    conservative_overpayment = request.form.get('conservative_overpayment')
    if conservative_overpayment:
        scenarios.append({
            'name': 'conservative', 
            'overpayment': Decimal(str(conservative_overpayment))
        })
    
    success = MortgageService.generate_projections(property_id, scenarios)
    
    if success:
        flash('Mortgage projections generated successfully!', 'success')
    else:
        flash('Failed to generate projections.', 'error')
    
    return redirect(url_for('mortgage.property_detail', property_id=property_id))


@mortgage_bp.route('/mortgage/snapshot/<int:snapshot_id>/confirm', methods=['POST'])
def confirm_snapshot(snapshot_id):
    """Convert projected snapshot to actual"""
    snapshot = family_get_or_404(MortgageSnapshot, snapshot_id)
    
    # Get optional actual values from form
    actual_balance = request.form.get('actual_balance')
    actual_valuation = request.form.get('actual_valuation')
    
    if actual_balance:
        actual_balance = Decimal(str(actual_balance))
    else:
        actual_balance = None
    
    if actual_valuation:
        actual_valuation = Decimal(str(actual_valuation))
    else:
        actual_valuation = None
    
    success = MortgageService.confirm_snapshot(snapshot_id, actual_balance, actual_valuation)
    
    if success:
        flash('Snapshot confirmed as actual!', 'success')
        # Regenerate projections to account for new actual data
        property_id = snapshot.mortgage_product.property_id
        MortgageService.generate_projections(property_id)
    else:
        flash('Failed to confirm snapshot.', 'error')
    
    return redirect(request.referrer or url_for('mortgage.index'))


@mortgage_bp.route('/mortgage/property/create', methods=['GET', 'POST'])
def create_property():
    """Create a new property"""
    if request.method == 'POST':
        prop = Property(
            address=request.form.get('address'),
            purchase_date=datetime.strptime(request.form.get('purchase_date'), '%Y-%m-%d').date() if request.form.get('purchase_date') else None,
            purchase_price=Decimal(request.form.get('purchase_price')) if request.form.get('purchase_price') else None,
            current_valuation=Decimal(request.form.get('current_valuation')) if request.form.get('current_valuation') else None,
            annual_appreciation_rate=Decimal(request.form.get('annual_appreciation_rate', '3.0')),
            is_primary_residence=request.form.get('is_primary_residence') == 'on'
        )
        
        db.session.add(prop)
        db.session.commit()
        
        flash('Property created successfully!', 'success')
        return redirect(url_for('mortgage.property_detail', property_id=prop.id))
    
    return render_template('mortgage/create_property.html')


@mortgage_bp.route('/mortgage/property/<int:property_id>/product/create', methods=['GET', 'POST'])
def create_product(property_id):
    """Create a new mortgage product for a property"""
    prop = family_get_or_404(Property, property_id)
    
    if request.method == 'POST':
        account_id = request.form.get('account_id')
        vendor_id = request.form.get('vendor_id')
        category_id = request.form.get('category_id')
        
        product = MortgageProduct(
            property_id=property_id,
            account_id=int(account_id) if account_id else None,
            vendor_id=int(vendor_id) if vendor_id else None,
            category_id=int(category_id) if category_id else None,
            lender=request.form.get('lender'),
            product_name=request.form.get('product_name'),
            start_date=datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date(),
            end_date=datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date(),
            term_months=int(request.form.get('term_months')),
            initial_balance=Decimal(request.form.get('initial_balance')),
            current_balance=Decimal(request.form.get('current_balance')),
            annual_rate=Decimal(request.form.get('annual_rate')),
            monthly_payment=Decimal(request.form.get('monthly_payment')),
            payment_day=int(request.form.get('payment_day', 1)),
            is_active=request.form.get('is_active') == 'on',
            is_current=request.form.get('is_current') == 'on',
            ltv_ratio=Decimal(request.form.get('ltv_ratio')) if request.form.get('ltv_ratio') else None
        )
        
        db.session.add(product)
        db.session.commit()
        
        flash('Mortgage product created successfully!', 'success')
        return redirect(url_for('mortgage.property_detail', property_id=property_id))
    
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    vendors = family_query(Vendor).filter_by(is_active=True).order_by(Vendor.name).all()
    categories = family_query(Category).filter_by(category_type='expense').order_by(Category.head_budget, Category.sub_budget).all()
    return render_template('mortgage/create_product.html', property=prop, accounts=accounts, vendors=vendors, categories=categories)


@mortgage_bp.route('/mortgage/product/<int:product_id>/edit', methods=['GET', 'POST'])
def edit_product(product_id):
    """Edit an existing mortgage product"""
    product = family_get_or_404(MortgageProduct, product_id)
    prop = product.property
    
    if request.method == 'POST':
        account_id = request.form.get('account_id')
        vendor_id = request.form.get('vendor_id')
        category_id = request.form.get('category_id')
        
        product.account_id = int(account_id) if account_id else None
        product.vendor_id = int(vendor_id) if vendor_id else None
        product.category_id = int(category_id) if category_id else None
        product.lender = request.form.get('lender')
        product.product_name = request.form.get('product_name')
        product.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        product.end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        product.term_months = int(request.form.get('term_months'))
        product.initial_balance = Decimal(request.form.get('initial_balance'))
        product.current_balance = Decimal(request.form.get('current_balance'))
        product.annual_rate = Decimal(request.form.get('annual_rate'))
        product.monthly_payment = Decimal(request.form.get('monthly_payment'))
        product.payment_day = int(request.form.get('payment_day', 1))
        product.is_active = request.form.get('is_active') == 'on'
        product.is_current = request.form.get('is_current') == 'on'
        product.ltv_ratio = Decimal(request.form.get('ltv_ratio')) if request.form.get('ltv_ratio') else None
        
        db.session.commit()
        
        flash('Mortgage product updated successfully!', 'success')
        return redirect(url_for('mortgage.property_detail', property_id=prop.id))
    
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    vendors = family_query(Vendor).filter_by(is_active=True).order_by(Vendor.name).all()
    categories = family_query(Category).filter_by(category_type='expense').order_by(Category.head_budget, Category.sub_budget).all()
    return render_template('mortgage/edit_product.html', product=product, property=prop, accounts=accounts, vendors=vendors, categories=categories)


@mortgage_bp.route('/mortgage/product/<int:product_id>/delete', methods=['POST'])
def delete_product(product_id):
    """Delete a mortgage product"""
    product = family_get_or_404(MortgageProduct, product_id)
    property_id = product.property_id
    
    # The cascade delete will automatically remove all snapshots
    db.session.delete(product)
    db.session.commit()
    
    flash(f'Product "{product.lender} - {product.product_name}" deleted successfully!', 'success')
    return redirect(url_for('mortgage.property_detail', property_id=property_id))


@mortgage_bp.route('/mortgage/property/<int:property_id>/edit', methods=['GET', 'POST'])
def edit_property(property_id):
    """Edit an existing property"""
    prop = family_get_or_404(Property, property_id)
    
    if request.method == 'POST':
        prop.address = request.form.get('address')
        prop.purchase_date = datetime.strptime(request.form.get('purchase_date'), '%Y-%m-%d').date() if request.form.get('purchase_date') else None
        prop.purchase_price = Decimal(request.form.get('purchase_price')) if request.form.get('purchase_price') else None
        prop.current_valuation = Decimal(request.form.get('current_valuation')) if request.form.get('current_valuation') else None
        prop.annual_appreciation_rate = Decimal(request.form.get('annual_appreciation_rate', '3.0'))
        prop.is_primary_residence = request.form.get('is_primary_residence') == 'on'
        prop.is_active = request.form.get('is_active') == 'on'
        
        db.session.commit()
        
        flash('Property updated successfully!', 'success')
        return redirect(url_for('mortgage.property_detail', property_id=property_id))
    
    return render_template('mortgage/edit_property.html', property=prop)


@mortgage_bp.route('/mortgage/property/<int:property_id>/delete', methods=['POST'])
def delete_property(property_id):
    """Delete a property and all associated mortgage products"""
    prop = family_get_or_404(Property, property_id)
    
    # The cascade delete will automatically remove all mortgage products and snapshots
    db.session.delete(prop)
    db.session.commit()
    
    flash(f'Property "{prop.address}" deleted successfully!', 'success')
    return redirect(url_for('mortgage.index'))


@mortgage_bp.route('/mortgage/create', methods=['POST'])
def create():
    """Create a new mortgage (legacy endpoint)"""
    # Implementation here
    return redirect(url_for('mortgage.index'))


@mortgage_bp.route('/mortgage/snapshot/<int:snapshot_id>/create_transaction', methods=['POST'])
def create_transaction_for_snapshot(snapshot_id):
    """Create a transaction for an existing snapshot"""
    snapshot = family_get_or_404(MortgageSnapshot, snapshot_id)
    
    if snapshot.transaction_id:
        flash('Transaction already exists for this snapshot.', 'warning')
    else:
        success = MortgageService.create_transaction_for_snapshot(snapshot_id)
        
        if success:
            flash('Transaction created successfully!', 'success')
        else:
            flash('Failed to create transaction. Make sure the product has a linked account.', 'error')
    
    return redirect(request.referrer or url_for('mortgage.property_detail', property_id=snapshot.mortgage_product.property_id))


@mortgage_bp.route('/mortgage/snapshot/<int:snapshot_id>/mark_paid', methods=['POST'])
def mark_snapshot_paid(snapshot_id):
    """Mark a projection as paid by linking to an existing transaction"""
    snapshot = family_get_or_404(MortgageSnapshot, snapshot_id)
    transaction_id = request.form.get('transaction_id')
    
    if transaction_id:
        snapshot.transaction_id = int(transaction_id)
        db.session.commit()
        flash('Snapshot linked to transaction!', 'success')
    else:
        flash('No transaction ID provided.', 'error')
    
    return redirect(request.referrer or url_for('mortgage.property_detail', property_id=snapshot.mortgage_product.property_id))


@mortgage_bp.route('/mortgage/snapshot/<int:snapshot_id>/unlink_transaction', methods=['POST'])
def unlink_transaction(snapshot_id):
    """Remove transaction link from snapshot"""
    snapshot = family_get_or_404(MortgageSnapshot, snapshot_id)
    
    snapshot.transaction_id = None
    db.session.commit()
    
    flash('Transaction unlinked from snapshot.', 'info')
    return redirect(request.referrer or url_for('mortgage.property_detail', property_id=snapshot.mortgage_product.property_id))


@mortgage_bp.route('/mortgage/snapshot/<int:snapshot_id>/delete', methods=['POST'])
def delete_snapshot(snapshot_id):
    """Delete a snapshot and its linked transaction if exists"""
    snapshot = family_get_or_404(MortgageSnapshot, snapshot_id)
    property_id = snapshot.mortgage_product.property_id
    
    # Delete linked transaction if exists
    if snapshot.transaction_id:
        transaction = family_get(Transaction, snapshot.transaction_id)
        if transaction:
            db.session.delete(transaction)
    
    # Delete the snapshot
    db.session.delete(snapshot)
    db.session.commit()
    
    flash('Snapshot and associated transaction deleted successfully.', 'success')
    return redirect(request.referrer or url_for('mortgage.property_detail', property_id=property_id))
