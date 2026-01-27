from flask import render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func
from datetime import datetime
from . import transactions_bp
from models.transactions import Transaction
from models.accounts import Account
from models.categories import Category
from models.vendors import Vendor
from extensions import db


@transactions_bp.route('/transactions')
def index():
    """List all transactions with filtering and summary stats"""
    
    # Get filter parameters
    account_id = request.args.get('account_id', type=int)
    head_budget = request.args.get('head_budget')
    category_id = request.args.get('category_id', type=int)
    vendor_id = request.args.get('vendor_id', type=int)
    year_month = request.args.get('year_month')
    search = request.args.get('search', '')
    
    # Build query
    query = Transaction.query
    
    if account_id:
        query = query.filter(Transaction.account_id == account_id)
    if head_budget:
        # Filter by head_budget (all categories under this head)
        query = query.join(Category).filter(Category.head_budget == head_budget)
    if category_id:
        # Explicitly specify Transaction.category_id to avoid ambiguity after join
        query = query.filter(Transaction.category_id == category_id)
    if vendor_id:
        query = query.filter(Transaction.vendor_id == vendor_id)
    if year_month:
        query = query.filter(Transaction.year_month == year_month)
    if search:
        query = query.filter(
            db.or_(
                Transaction.description.ilike(f'%{search}%'),
                Transaction.item.ilike(f'%{search}%')
            )
        )
    
    # Order by date descending
    transactions = query.order_by(Transaction.transaction_date.desc()).all()
    
    # Calculate summary statistics
    total_income = sum([-t.amount for t in transactions if t.amount < 0])
    total_expenses = sum([t.amount for t in transactions if t.amount > 0])
    net_balance = total_income - total_expenses
    
    # Get filter options
    accounts = Account.query.order_by(Account.name).all()
    
    # Get unique head budgets for primary filter
    head_budgets = db.session.query(Category.head_budget).distinct().order_by(Category.head_budget).all()
    head_budgets = [hb[0] for hb in head_budgets if hb[0]]
    
    # Get categories (filtered by head_budget if selected)
    if head_budget:
        categories = Category.query.filter_by(head_budget=head_budget).order_by(Category.sub_budget).all()
    else:
        categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    
    # Get all categories for bulk edit dropdown (unfiltered)
    all_categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    
    vendors = Vendor.query.order_by(Vendor.name).all()
    
    # Get unique year_months from transactions
    year_months = db.session.query(Transaction.year_month).distinct().order_by(Transaction.year_month.desc()).all()
    year_months = [ym[0] for ym in year_months if ym[0]]
    
    return render_template(
        'transactions.html',
        transactions=transactions,
        accounts=accounts,
        head_budgets=head_budgets,
        categories=categories,
        all_categories=all_categories,
        vendors=vendors,
        year_months=year_months,
        total_income=total_income,
        total_expenses=total_expenses,
        net_balance=net_balance,
        transaction_count=len(transactions),
        selected_account=account_id,
        selected_head_budget=head_budget,
        selected_category=category_id,
        selected_vendor=vendor_id,
        selected_year_month=year_month,
        search_term=search
    )


@transactions_bp.route('/transactions/create', methods=['GET', 'POST'])
def create():
    """Create a new transaction"""
    if request.method == 'POST':
        try:
            # Get basic form data
            account_id = request.form.get('account_id', type=int)
            category_id = request.form.get('category_id', type=int)
            vendor_id = request.form.get('vendor_id', type=int) if request.form.get('vendor_id') else None
            amount = float(request.form.get('amount'))
            transaction_date = datetime.strptime(request.form.get('transaction_date'), '%Y-%m-%d').date()
            description = request.form.get('description', '')
            item = request.form.get('item', '')
            assigned_to = request.form.get('assigned_to', '')
            payment_type = request.form.get('payment_type', '')
            is_paid = request.form.get('is_paid') == 'on'
            
            # Recurring options
            is_recurring = request.form.get('is_recurring') == 'on'
            frequency = request.form.get('frequency', 'monthly')
            occurrences = request.form.get('occurrences', type=int, default=1)
            
            if is_recurring and occurrences < 1:
                flash('Number of occurrences must be at least 1', 'danger')
                return redirect(url_for('transactions.create'))
            
            # Create transactions
            transactions_created = 0
            current_date = transaction_date
            
            for i in range(occurrences if is_recurring else 1):
                # Calculate date for this occurrence
                if i > 0:
                    if frequency == 'weekly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transaction_date + relativedelta(weeks=i)
                    elif frequency == 'monthly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transaction_date + relativedelta(months=i)
                    elif frequency == 'yearly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transaction_date + relativedelta(years=i)
                
                # Calculate computed fields
                year_month = current_date.strftime('%Y-%m')
                week_year = f"{current_date.isocalendar()[1]:02d}-{current_date.year}"
                day_name = current_date.strftime('%a')
                
                # Create transaction
                transaction = Transaction(
                    account_id=account_id,
                    category_id=category_id,
                    vendor_id=vendor_id,
                    amount=amount,
                    transaction_date=current_date,
                    description=description,
                    item=item,
                    assigned_to=assigned_to,
                    payment_type=payment_type,
                    is_paid=is_paid,
                    year_month=year_month,
                    week_year=week_year,
                    day_name=day_name
                )
                
                db.session.add(transaction)
                transactions_created += 1
            
            db.session.commit()
            
            # Recalculate account balance
            Transaction.recalculate_account_balance(account_id)
            db.session.commit()
            
            if is_recurring:
                flash(f'{transactions_created} transactions created successfully! Account balance updated.', 'success')
            else:
                flash('Transaction created successfully! Account balance updated.', 'success')
            # Preserve filters from referrer
            return redirect(request.referrer or url_for('transactions.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating transaction: {str(e)}', 'danger')
            return redirect(url_for('transactions.index'))
    
    # GET request - show form
    accounts = Account.query.order_by(Account.name).all()
    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    vendors = Vendor.query.order_by(Vendor.name).all()
    
    return render_template(
        'transaction_form.html',
        transaction=None,
        accounts=accounts,
        categories=categories,
        vendors=vendors,
        action='Create'
    )


@transactions_bp.route('/transactions/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit a transaction"""
    transaction = Transaction.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Store old account_id before changes
            old_account_id = transaction.account_id
            
            # Update transaction fields
            transaction.account_id = request.form.get('account_id', type=int)
            transaction.category_id = request.form.get('category_id', type=int)
            transaction.vendor_id = request.form.get('vendor_id', type=int) if request.form.get('vendor_id') else None
            transaction.amount = float(request.form.get('amount'))
            transaction.transaction_date = datetime.strptime(request.form.get('transaction_date'), '%Y-%m-%d').date()
            transaction.description = request.form.get('description', '')
            transaction.item = request.form.get('item', '')
            transaction.assigned_to = request.form.get('assigned_to', '')
            transaction.payment_type = request.form.get('payment_type', '')
            transaction.is_paid = request.form.get('is_paid') == 'on'
            
            # Recalculate computed fields
            date = transaction.transaction_date
            transaction.year_month = date.strftime('%Y-%m')
            transaction.week_year = f"{date.isocalendar()[1]:02d}-{date.year}"
            transaction.day_name = date.strftime('%a')
            transaction.updated_at = datetime.now()
            
            db.session.commit()
            
            # Recalculate balances for affected accounts
            if old_account_id and old_account_id != transaction.account_id:
                # Account changed - update both old and new
                Transaction.recalculate_account_balance(old_account_id)
                Transaction.recalculate_account_balance(transaction.account_id)
            else:
                # Same account - just update it
                Transaction.recalculate_account_balance(transaction.account_id)
            
            db.session.commit()
            
            flash('Transaction updated successfully! Account balances updated.', 'success')
            # Use return_url from form, then referrer, then default
            return_url = request.form.get('return_url')
            if return_url:
                return redirect(return_url)
            return redirect(request.referrer or url_for('transactions.index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating transaction: {str(e)}', 'danger')
            return redirect(url_for('transactions.edit', id=id))
    
    # GET request - show form
    accounts = Account.query.order_by(Account.name).all()
    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    vendors = Vendor.query.order_by(Vendor.name).all()
    
    return render_template(
        'transaction_form.html',
        transaction=transaction,
        accounts=accounts,
        categories=categories,
        vendors=vendors,
        action='Edit'
    )


@transactions_bp.route('/transactions/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a transaction"""
    transaction = Transaction.query.get_or_404(id)
    
    try:
        account_id = transaction.account_id
        account_name = transaction.account.name if transaction.account else 'Unknown'
        
        db.session.delete(transaction)
        db.session.commit()
        
        # Recalculate balance for the account
        if account_id:
            Transaction.recalculate_account_balance(account_id)
            db.session.commit()
        
        flash(f'Transaction deleted successfully! {account_name} balance updated.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting transaction: {str(e)}', 'danger')
    
    # Check for return_url from form, then referrer, then default
    return_url = request.form.get('return_url')
    if return_url:
        return redirect(return_url)
    return redirect(request.referrer or url_for('transactions.index'))


@transactions_bp.route('/transactions/bulk-edit', methods=['POST'])
def bulk_edit():
    """Bulk edit multiple transactions"""
    try:
        # Get transaction IDs
        transaction_ids_str = request.form.get('transaction_ids', '')
        if not transaction_ids_str:
            flash('No transactions selected', 'warning')
            return redirect(request.form.get('return_url') or url_for('transactions.index'))
        
        transaction_ids = [int(tid) for tid in transaction_ids_str.split(',') if tid]
        
        # Get update values
        category_id = request.form.get('bulk_category_id', type=int)
        vendor_id = request.form.get('bulk_vendor_id', type=int)
        payment_type = request.form.get('bulk_payment_type')
        assigned_to = request.form.get('bulk_assigned_to')
        
        # Track affected accounts for balance recalculation
        affected_accounts = set()
        update_count = 0
        
        # Update each transaction
        for transaction_id in transaction_ids:
            transaction = Transaction.query.get(transaction_id)
            if transaction:
                affected_accounts.add(transaction.account_id)
                
                # Apply updates only if value is provided
                if category_id:
                    transaction.category_id = category_id
                if vendor_id:
                    transaction.vendor_id = vendor_id
                if payment_type:
                    transaction.payment_type = payment_type
                if assigned_to:
                    transaction.assigned_to = assigned_to
                
                transaction.updated_at = datetime.now()
                update_count += 1
        
        db.session.commit()
        
        # Recalculate balances for affected accounts
        for account_id in affected_accounts:
            if account_id:
                Transaction.recalculate_account_balance(account_id)
        
        db.session.commit()
        
        flash(f'{update_count} transactions updated successfully! Account balances recalculated.', 'success')
        
    except ValueError as e:
        db.session.rollback()
        flash(f'Invalid transaction IDs: {str(e)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating transactions: {str(e)}', 'danger')
    
    return redirect(request.form.get('return_url') or url_for('transactions.index'))


@transactions_bp.route('/transactions/transfer', methods=['GET', 'POST'])
def create_transfer():
    """Create a transfer between two accounts (creates both transactions automatically)"""
    if request.method == 'POST':
        try:
            # Get form data
            from_account_id = request.form.get('from_account_id', type=int)
            to_account_id = request.form.get('to_account_id', type=int)
            
            # Validate required fields first
            if not from_account_id or not to_account_id:
                flash('Please select both accounts', 'danger')
                accounts = Account.query.order_by(Account.name).all()
                categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
                return render_template('transfer_form.html', accounts=accounts, categories=categories)
            
            amount_str = request.form.get('amount', '')
            if not amount_str:
                flash('Please enter an amount', 'danger')
                accounts = Account.query.order_by(Account.name).all()
                categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
                return render_template('transfer_form.html', accounts=accounts, categories=categories)
            
            amount = abs(float(amount_str))  # Ensure positive
            transfer_date = datetime.strptime(request.form.get('transaction_date'), '%Y-%m-%d').date()
            description = request.form.get('description', 'Transfer')
            category_id = request.form.get('category_id', type=int)
            
            # Bulk transfer options
            is_recurring = request.form.get('is_recurring') == 'on'
            frequency = request.form.get('frequency', 'monthly')
            occurrences_str = request.form.get('occurrences', '1')
            occurrences = int(occurrences_str) if occurrences_str else 1
            
            # Additional validation
            if from_account_id == to_account_id:
                flash('Cannot transfer to the same account', 'danger')
                return redirect(url_for('transactions.create_transfer'))
            
            if amount <= 0:
                flash('Amount must be greater than 0', 'danger')
                return redirect(url_for('transactions.create_transfer'))
            
            if is_recurring and occurrences < 1:
                flash('Number of occurrences must be at least 1', 'danger')
                return redirect(url_for('transactions.create_transfer'))
            
            # Get accounts
            from_account = Account.query.get(from_account_id)
            to_account = Account.query.get(to_account_id)
            
            # Get or create vendor entries for accounts (for filtering)
            from_vendor = Vendor.query.filter_by(name=to_account.name).first()
            if not from_vendor:
                from_vendor = Vendor(name=to_account.name)
                db.session.add(from_vendor)
                db.session.flush()
            
            to_vendor = Vendor.query.filter_by(name=from_account.name).first()
            if not to_vendor:
                to_vendor = Vendor(name=from_account.name)
                db.session.add(to_vendor)
                db.session.flush()
            
            # Get category (use selected or default to Transfer)
            if category_id:
                transfer_category = Category.query.get(category_id)
                if not transfer_category:
                    flash('Invalid category selected', 'danger')
                    accounts = Account.query.order_by(Account.name).all()
                    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
                    return render_template('transfer_form.html', accounts=accounts, categories=categories)
            else:
                # Get or create default Transfer category
                transfer_category = Category.query.filter_by(
                    head_budget='Transfer',
                    sub_budget='Account Transfer'
                ).first()
                
                if not transfer_category:
                    transfer_category = Category(
                        name='Account Transfer',
                        head_budget='Transfer',
                        sub_budget='Account Transfer',
                        category_type='Transfer'
                    )
                    db.session.add(transfer_category)
                    db.session.flush()
            
            # Create transfers (single or multiple)
            transfers_created = 0
            current_date = transfer_date
            
            for i in range(occurrences if is_recurring else 1):
                # Calculate date for this occurrence
                if i > 0:
                    if frequency == 'weekly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transfer_date + relativedelta(weeks=i)
                    elif frequency == 'monthly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transfer_date + relativedelta(months=i)
                    elif frequency == 'yearly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transfer_date + relativedelta(years=i)
                
                # Calculate computed fields
                year_month = current_date.strftime('%Y-%m')
                week_year = f"{current_date.isocalendar()[1]:02d}-{current_date.year}"
                day_name = current_date.strftime('%a')
                
                # Create transaction in FROM account (money leaving - positive amount)
                from_transaction = Transaction(
                    account_id=from_account_id,
                    category_id=transfer_category.id,
                    vendor_id=from_vendor.id,  # Vendor = destination account
                    amount=amount,  # Positive = expense/debit
                    transaction_date=current_date,
                    description=f"Transfer to {to_account.name}",
                    item=description,
                    payment_type='Transfer',
                    is_paid=True,
                    year_month=year_month,
                    week_year=week_year,
                    day_name=day_name
                )
                
                # Create transaction in TO account (money arriving - negative amount)
                to_transaction = Transaction(
                    account_id=to_account_id,
                    category_id=transfer_category.id,
                    vendor_id=to_vendor.id,  # Vendor = source account
                    amount=-amount,  # Negative = income/credit
                    transaction_date=current_date,
                    description=f"Transfer from {from_account.name}",
                    item=description,
                    payment_type='Transfer',
                    is_paid=True,
                    year_month=year_month,
                    week_year=week_year,
                    day_name=day_name
                )
                
                db.session.add(from_transaction)
                db.session.add(to_transaction)
                transfers_created += 1
            
            db.session.commit()
            
            # Recalculate both account balances
            Transaction.recalculate_account_balance(from_account_id)
            Transaction.recalculate_account_balance(to_account_id)
            db.session.commit()
            
            if is_recurring:
                flash(f'{transfers_created} transfers created: £{amount:.2f} {frequency} from {from_account.name} to {to_account.name}. Both account balances updated.', 'success')
            else:
                flash(f'Transfer created: £{amount:.2f} from {from_account.name} to {to_account.name}. Both account balances updated.', 'success')
            # Preserve filters from referrer
            return redirect(request.referrer or url_for('transactions.index'))
            
        except ValueError as e:
            db.session.rollback()
            flash(f'Invalid input: {str(e)}', 'danger')
            accounts = Account.query.order_by(Account.name).all()
            categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
            return render_template('transfer_form.html', accounts=accounts, categories=categories)
        except Exception as e:
            db.session.rollback()
            import traceback
            error_detail = traceback.format_exc()
            print(f"Transfer creation error: {error_detail}")  # Log to console
            flash(f'Error creating transfer: {str(e)}', 'danger')
            accounts = Account.query.order_by(Account.name).all()
            categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
            return render_template('transfer_form.html', accounts=accounts, categories=categories)
    
    # GET request - show form
    accounts = Account.query.order_by(Account.name).all()
    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    
    return render_template(
        'transfer_form.html',
        accounts=accounts,
        categories=categories
    )
