from flask import render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import func
from datetime import datetime, timedelta
from . import transactions_bp
from models.transactions import Transaction
from models.accounts import Account
from models.categories import Category
from models.vendors import Vendor
from models.credit_card_transactions import CreditCardTransaction
from models.credit_cards import CreditCard
from models.loan_payments import LoanPayment
from models.loans import Loan
from models.settings import Settings
from services.payday_service import PaydayService
from extensions import db
from flask import current_app
from models.expenses import Expense


@transactions_bp.route('/transactions')
def index():
    """List all transactions with filtering and summary stats"""
    
    # Get filter parameters
    account_id = request.args.get('account_id', type=int)
    transaction_id = request.args.get('id', type=int)
    head_budget = request.args.get('head_budget')
    category_id = request.args.get('category_id', type=int)
    vendor_id = request.args.get('vendor_id', type=int)
    year_month = request.args.get('year_month')
    payday_period = request.args.get('payday_period')
    search = request.args.get('search', '')
    is_paid_filter = request.args.get('is_paid')
    sort_order = request.args.get('sort', 'asc')  # 'asc' or 'desc'
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    
    # If filtering by specific transaction ID, adjust filters to show that transaction
    if transaction_id:
        target_transaction = Transaction.query.get(transaction_id)
        if target_transaction:
            # Set filters to the transaction's context
            account_id = target_transaction.account_id
            year_month = target_transaction.year_month
            is_paid_filter = None  # Show both paid and unpaid
            per_page = 100  # Increase per page to ensure transaction is visible
    
    # Default to current payday period and pending ONLY on first visit (no query params at all)
    if not request.args:
        from datetime import date
        today = date.today()
        current_year = today.year
        current_month = today.month
        _, _, current_period = PaydayService.get_payday_period(current_year, current_month)
        payday_period = current_period
        is_paid_filter = 'pending'
    
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
    if payday_period:
        query = query.filter(Transaction.payday_period == payday_period)
    if search:
        query = query.filter(
            db.or_(
                Transaction.description.ilike(f'%{search}%'),
                Transaction.item.ilike(f'%{search}%')
            )
        )
    if is_paid_filter:
        if is_paid_filter == 'paid':
            query = query.filter(Transaction.is_paid == True)
        elif is_paid_filter == 'pending':
            query = query.filter(Transaction.is_paid == False)
    
    # Order by date based on sort parameter
    if sort_order == 'desc':
        query = query.order_by(Transaction.transaction_date.desc())
    else:
        query = query.order_by(Transaction.transaction_date.asc())
    
    # Get paginated results
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    transactions = pagination.items
    
    # Calculate summary statistics from ALL filtered transactions (not just current page)
    all_filtered_transactions = query.all()
    total_income = sum([t.amount for t in all_filtered_transactions if t.amount > 0])
    total_expenses = sum([abs(t.amount) for t in all_filtered_transactions if t.amount < 0])
    net_balance = total_income - total_expenses
    total_count = len(all_filtered_transactions)
    
    # Calculate running balance for current page transactions
    # Running balance is calculated per account (not globally)
    from decimal import Decimal
    running_balances = []
    
    for txn in transactions:
        # Get ALL transactions from the SAME ACCOUNT up to and including this transaction's date
        # Order by date ascending, then by ID to ensure consistent ordering
        all_txns_up_to_date = Transaction.query.filter(
            Transaction.account_id == txn.account_id,
            db.or_(
                Transaction.transaction_date < txn.transaction_date,
                db.and_(
                    Transaction.transaction_date == txn.transaction_date,
                    Transaction.id <= txn.id
                )
            )
        ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all()
        
        # Calculate running balance from all transactions in this account up to this point
        running_balance = Decimal('0')
        for t in all_txns_up_to_date:
            if t.amount > 0:  # Income
                running_balance += Decimal(str(t.amount))
            else:  # Expense
                running_balance -= abs(Decimal(str(t.amount)))
        
        running_balances.append(running_balance)
    
    # Calculate category summary for all filtered transactions (not just current page)
    from collections import defaultdict
    summary = defaultdict(lambda: {'categories': defaultdict(lambda: {'count': 0, 'total': 0})})
    
    for t in all_filtered_transactions:
        if t.category:
            head = t.category.head_budget
            sub = t.category.sub_budget
            summary[head]['categories'][sub]['count'] += 1
            summary[head]['categories'][sub]['total'] += t.amount
            
    # Calculate totals for each head budget
    for head in summary:
        summary[head]['total_count'] = sum(cat['count'] for cat in summary[head]['categories'].values())
        summary[head]['total_amount'] = sum(cat['total'] for cat in summary[head]['categories'].values())
    
    # Sort by total amount (descending)
    category_summary = dict(sorted(summary.items(), 
                                  key=lambda x: abs(x[1]['total_amount']), 
                                  reverse=True))
    
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
    
    # Get payday periods for filter - generate from min to max transaction dates
    min_date = db.session.query(func.min(Transaction.transaction_date)).scalar()
    max_date = db.session.query(func.max(Transaction.transaction_date)).scalar()
    
    if min_date and max_date:
        # Calculate number of months between min and max
        months_diff = (max_date.year - min_date.year) * 12 + (max_date.month - min_date.month) + 2
        payday_periods = PaydayService.get_recent_periods(
            num_periods=months_diff, 
            include_future=False,
            start_year=min_date.year,
            start_month=min_date.month
        )
    else:
        payday_periods = []
    
    # Calculate previous and next payday periods for navigation
    prev_period = None
    next_period = None
    if payday_period:
        try:
            year, month = map(int, payday_period.split('-'))
            # Previous period
            prev_month = month - 1
            prev_year = year
            if prev_month < 1:
                prev_month = 12
                prev_year -= 1
            _, _, prev_period = PaydayService.get_payday_period(prev_year, prev_month)
            
            # Next period
            next_month = month + 1
            next_year = year
            if next_month > 12:
                next_month = 1
                next_year += 1
            _, _, next_period = PaydayService.get_payday_period(next_year, next_month)
        except:
            pass
    
    # Get filter expanded preference
    filter_expanded = Settings.get_value('transactions_filter_expanded', True)
    
    return render_template(
        'transactions/transactions.html',
        transactions=transactions,
        running_balances=running_balances,
        pagination=pagination,
        accounts=accounts,
        head_budgets=head_budgets,
        categories=categories,
        all_categories=all_categories,
        vendors=vendors,
        year_months=year_months,
        payday_periods=payday_periods,
        total_income=total_income,
        total_expenses=total_expenses,
        net_balance=net_balance,
        total_count=total_count,
        transaction_count=total_count,
        category_summary=category_summary,
        selected_account=Account.query.get(account_id) if account_id else None,
        selected_head_budget=head_budget,
        selected_category=Category.query.get(category_id) if category_id else None,
        selected_vendor=Vendor.query.get(vendor_id) if vendor_id else None,
        selected_year_month=year_month,
        selected_payday_period=payday_period,
        prev_payday_period=prev_period,
        next_payday_period=next_period,
        search_term=search,
        selected_is_paid=is_paid_filter,
        sort=sort_order,
        sort_order=sort_order,
        page=page,
        per_page=per_page,
        filter_expanded=filter_expanded,
        highlight_transaction_id=transaction_id
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
            adjust_working_days = request.form.get('adjust_working_days') == 'on'
            weekend_adjustment = request.form.get('weekend_adjustment', 'previous')  # 'previous' or 'next'
            
            if is_recurring and occurrences < 1:
                flash('Number of occurrences must be at least 1', 'danger')
                return redirect(url_for('transactions.create'))
            
            # Helper functions for working day adjustment
            def is_weekend(date_obj):
                """Check if date falls on Saturday (5) or Sunday (6)"""
                return date_obj.weekday() >= 5
            
            def adjust_to_working_day(date_obj, direction='previous'):
                """Adjust date to working day if it falls on weekend"""
                if not is_weekend(date_obj):
                    return date_obj
                
                if direction == 'previous':
                    # Move to previous Friday
                    while is_weekend(date_obj):
                        date_obj = date_obj - timedelta(days=1)
                else:  # 'next'
                    # Move to next Monday
                    while is_weekend(date_obj):
                        date_obj = date_obj + timedelta(days=1)
                return date_obj
            
            # Create transactions
            transactions_created = 0
            current_date = transaction_date
            
            for i in range(occurrences if is_recurring else 1):
                # Calculate date for this occurrence
                if i > 0:
                    if frequency == 'weekly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transaction_date + relativedelta(weeks=i)
                    elif frequency == '4weekly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transaction_date + relativedelta(weeks=i*4)
                    elif frequency == 'monthly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transaction_date + relativedelta(months=i)
                    elif frequency == 'quarterly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transaction_date + relativedelta(months=i*3)
                    elif frequency == 'yearly':
                        from dateutil.relativedelta import relativedelta
                        current_date = transaction_date + relativedelta(years=i)
                
                # Adjust for working days if enabled
                if adjust_working_days:
                    current_date = adjust_to_working_day(current_date, weekend_adjustment)
                
                # Calculate computed fields
                year_month = current_date.strftime('%Y-%m')
                week_year = f"{current_date.isocalendar()[1]:02d}-{current_date.year}"
                day_name = current_date.strftime('%a')
                payday_period = PaydayService.get_period_for_date(current_date)
                
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
                    day_name=day_name,
                    payday_period=payday_period
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
        'transactions/transaction_form.html',
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
            transaction.is_paid = request.form.get('is_paid') == '1'
            transaction.is_fixed = request.form.get('txn_fixed') == '1'
            
            # Recalculate computed fields
            date = transaction.transaction_date
            transaction.year_month = date.strftime('%Y-%m')
            transaction.week_year = f"{date.isocalendar()[1]:02d}-{date.year}"
            transaction.day_name = date.strftime('%a')
            transaction.payday_period = PaydayService.get_period_for_date(date)
            transaction.updated_at = datetime.now()
            
            # Sync changes to linked transfer transaction if exists (BEFORE commit)
            linked_account_id = None
            if transaction.linked_transaction_id:
                linked_txn = Transaction.query.get(transaction.linked_transaction_id)
                if linked_txn:
                    linked_account_id = linked_txn.account_id
                    
                    # Update the linked transaction with opposite amount
                    linked_txn.amount = -transaction.amount
                    linked_txn.transaction_date = transaction.transaction_date
                    linked_txn.item = transaction.item
                    linked_txn.is_paid = transaction.is_paid
                    
                    # Update description to reflect the correct direction
                    if transaction.amount < 0:  # Current txn is expense (money leaving)
                        # This is the "from" account, linked is the "to" account
                        linked_txn.description = f"Transfer from {transaction.account.name if transaction.account else 'Unknown'}"
                    else:  # Current txn is income (money arriving)
                        # This is the "to" account, linked is the "from" account
                        linked_txn.description = f"Transfer to {transaction.account.name if transaction.account else 'Unknown'}"
                    
                    # Recalculate computed fields for linked transaction
                    linked_txn.year_month = transaction.transaction_date.strftime('%Y-%m')
                    linked_txn.week_year = f"{transaction.transaction_date.isocalendar()[1]:02d}-{transaction.transaction_date.year}"
                    linked_txn.day_name = transaction.transaction_date.strftime('%a')
                    linked_txn.payday_period = PaydayService.get_period_for_date(transaction.transaction_date)
                    linked_txn.updated_at = datetime.now()
            
            db.session.commit()
            
            # Sync changes to linked credit card payment if exists
            if transaction.credit_card_id:
                from services.credit_card_service import CreditCardService
                CreditCardService.sync_bank_transaction_to_payment(transaction)
            
            # Sync changes to linked loan payment if exists
            if transaction.loan_id:
                from models.loan_payments import LoanPayment
                loan_payment = LoanPayment.query.filter_by(
                    bank_transaction_id=transaction.id
                ).first()
                if loan_payment:
                    loan_payment.is_paid = transaction.is_paid
            
            # Recalculate balances for affected accounts
            if old_account_id and old_account_id != transaction.account_id:
                # Account changed - update both old and new
                Transaction.recalculate_account_balance(old_account_id)
                Transaction.recalculate_account_balance(transaction.account_id)
            else:
                # Same account - just update it
                Transaction.recalculate_account_balance(transaction.account_id)
            
            # Also recalculate linked transaction's account if it exists
            if linked_account_id:
                Transaction.recalculate_account_balance(linked_account_id)
            
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
        'transactions/transaction_form.html',
        transaction=transaction,
        accounts=accounts,
        categories=categories,
        vendors=vendors,
        action='Edit'
    )


@transactions_bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a transaction"""
    transaction = Transaction.query.get_or_404(id)
    
    try:
        account_id = transaction.account_id
        account_name = transaction.account.name if transaction.account else 'Unknown'
        linked_cc_payment = None
        linked_transfer_account_id = None
        
        # Delete linked credit card payment if exists
        if transaction.credit_card_id:
            from models.credit_card_transactions import CreditCardTransaction
            linked_cc_payment = CreditCardTransaction.query.filter_by(
                bank_transaction_id=transaction.id
            ).first()
            if linked_cc_payment:
                db.session.delete(linked_cc_payment)
        
        # Delete linked transfer transaction if exists
        if transaction.linked_transaction_id:
            linked_transfer = Transaction.query.get(transaction.linked_transaction_id)
            if linked_transfer:
                linked_transfer_account_id = linked_transfer.account_id
                db.session.delete(linked_transfer)
        
        db.session.delete(transaction)
        db.session.commit()

        # Clear any Expense links pointing to this deleted transaction to avoid automatic recreation
        try:
            linked_expenses = Expense.query.filter(
                (Expense.bank_transaction_id == id) | (Expense.credit_card_transaction_id == id)
            ).all()
            for exp in linked_expenses:
                if getattr(exp, 'bank_transaction_id', None) == id:
                    exp.bank_transaction_id = None
                if getattr(exp, 'credit_card_transaction_id', None) == id:
                    exp.credit_card_transaction_id = None
                db.session.add(exp)
            if linked_expenses:
                db.session.commit()
                current_app.logger.info(f"Cleared expense links for deleted transaction {id}: {[e.id for e in linked_expenses]}")
        except Exception:
            db.session.rollback()
        
        # Recalculate credit card balance if payment was deleted
        if linked_cc_payment:
            from models.credit_card_transactions import CreditCardTransaction
            CreditCardTransaction.recalculate_card_balance(linked_cc_payment.credit_card_id)
        
        # Recalculate balance for the account
        if account_id:
            Transaction.recalculate_account_balance(account_id)
        
        # Recalculate balance for linked transfer account
        if linked_transfer_account_id:
            Transaction.recalculate_account_balance(linked_transfer_account_id)
        
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


@transactions_bp.route('/transactions/<int:id>/toggle_paid', methods=['POST'])
def toggle_paid(id):
    """Toggle the paid status of a transaction and sync with linked loan/credit card payments"""
    transaction = Transaction.query.get_or_404(id)
    
    try:
        transaction.is_paid = not transaction.is_paid
        transaction.updated_at = datetime.now()
        
        # Sync with linked loan payment if exists
        if transaction.loan_id:
            from models.loan_payments import LoanPayment
            loan_payment = LoanPayment.query.filter_by(
                bank_transaction_id=transaction.id
            ).first()
            if loan_payment:
                loan_payment.is_paid = transaction.is_paid
        
        # Sync with linked credit card payment if exists
        if transaction.credit_card_id:
            from models.credit_card_transactions import CreditCardTransaction
            cc_payment = CreditCardTransaction.query.filter_by(
                bank_transaction_id=transaction.id
            ).first()
            if cc_payment:
                cc_payment.is_paid = transaction.is_paid
        
        # Sync with linked transfer transaction if exists
        if transaction.linked_transaction_id:
            linked_txn = Transaction.query.get(transaction.linked_transaction_id)
            if linked_txn:
                linked_txn.is_paid = transaction.is_paid
                linked_txn.updated_at = datetime.now()
        
        # Sync with linked expense if exists
        from models.expenses import Expense
        expense = Expense.query.filter_by(bank_transaction_id=transaction.id).first()
        if expense:
            expense.paid_for = transaction.is_paid
        
        db.session.commit()
        
        status_text = "paid" if transaction.is_paid else "pending"
        flash(f'Transaction marked as {status_text}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating transaction status: {str(e)}', 'danger')
    
    # Redirect with anchor to preserve position
    referrer = request.referrer or url_for('transactions.index')
    # Add anchor to jump back to the transaction row
    if '#' not in referrer:
        referrer += f'#txn-{id}'
    return redirect(referrer)


@transactions_bp.route('/transactions/<int:id>/toggle_fixed', methods=['POST'])
def toggle_fixed(id):
    """Toggle the fixed/locked status of a transaction"""
    transaction = Transaction.query.get_or_404(id)
    
    try:
        transaction.is_fixed = not transaction.is_fixed
        transaction.updated_at = datetime.now()
        db.session.commit()
        
        status_text = "locked" if transaction.is_fixed else "unlocked"
        flash(f'Transaction {status_text}.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating transaction lock status: {str(e)}', 'danger')
    
    # Redirect with anchor to preserve position
    referrer = request.referrer or url_for('transactions.index')
    if '#' not in referrer:
        referrer += f'#txn-{id}'
    return redirect(referrer)


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
        is_paid_str = request.form.get('bulk_is_paid')
        
        # Convert is_paid to boolean if provided
        is_paid = None
        if is_paid_str == '1':
            is_paid = True
        elif is_paid_str == '0':
            is_paid = False
        
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
                if is_paid is not None:
                    transaction.is_paid = is_paid
                    # Sync with linked transfer if exists
                    if transaction.linked_transaction_id:
                        linked_txn = Transaction.query.get(transaction.linked_transaction_id)
                        if linked_txn:
                            linked_txn.is_paid = is_paid
                            if linked_txn.account_id:
                                affected_accounts.add(linked_txn.account_id)
                
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


@transactions_bp.route('/transactions/bulk-delete', methods=['POST'])
def bulk_delete():
    """Bulk delete multiple transactions"""
    try:
        transaction_ids_str = request.form.get('transaction_ids', '')
        # Log received ids for debugging
        current_app.logger.info(f"Bulk delete called with transaction_ids: {transaction_ids_str}")
        if not transaction_ids_str:
            flash('No transactions selected', 'warning')
            # Preserve filters if provided
            return redirect(request.form.get('return_url') or url_for('transactions.index'))
        
        transaction_ids = [int(tid) for tid in transaction_ids_str.split(',') if tid]
        # Inspect which transactions exist before deletion
        existing_before = Transaction.query.filter(Transaction.id.in_(transaction_ids)).all()
        existing_before_ids = [t.id for t in existing_before]
        current_app.logger.info(f"Bulk delete - existing before: {existing_before_ids}")

        deleted_count = 0
        accounts_to_recalc = set()
        cards_to_recalc = set()
        
        for txn_id in transaction_ids:
            transaction = Transaction.query.get(txn_id)
            if transaction:
                accounts_to_recalc.add(transaction.account_id)
                
                # Delete linked credit card payment if exists
                if transaction.credit_card_id:
                    linked_cc_payment = CreditCardTransaction.query.filter_by(
                        bank_transaction_id=transaction.id
                    ).first()
                    if linked_cc_payment:
                        cards_to_recalc.add(linked_cc_payment.credit_card_id)
                        db.session.delete(linked_cc_payment)
                
                db.session.delete(transaction)
                deleted_count += 1
                # Clear any Expense links pointing to this deleted transaction
                try:
                    linked_expenses = Expense.query.filter(
                        (Expense.bank_transaction_id == txn_id) | (Expense.credit_card_transaction_id == txn_id)
                    ).all()
                    for exp in linked_expenses:
                        if getattr(exp, 'bank_transaction_id', None) == txn_id:
                            exp.bank_transaction_id = None
                        if getattr(exp, 'credit_card_transaction_id', None) == txn_id:
                            exp.credit_card_transaction_id = None
                        db.session.add(exp)
                    if linked_expenses:
                        current_app.logger.info(f"Cleared expense links for deleted transaction {txn_id}: {[e.id for e in linked_expenses]}")
                except Exception:
                    db.session.rollback()
        
        db.session.commit()
        # Recalculate balances for affected accounts and credit cards
        for account_id in accounts_to_recalc:
            if account_id:
                Transaction.recalculate_account_balance(account_id)
        
        for card_id in cards_to_recalc:
            CreditCardTransaction.recalculate_card_balance(card_id)
        # Check which of the requested IDs still exist after deletion
        remaining = Transaction.query.filter(Transaction.id.in_(transaction_ids)).all()
        remaining_ids = [t.id for t in remaining]
        current_app.logger.info(f"Bulk delete - remaining after: {remaining_ids}")

        if remaining_ids:
            flash(f'Deleted {deleted_count} transaction(s). However {len(remaining_ids)} could not be deleted: {remaining_ids}', 'warning')
        else:
            flash(f'Successfully deleted {deleted_count} transaction(s)', 'success')
        current_app.logger.info(f"Bulk delete removed {deleted_count} transactions. IDs requested: {transaction_ids}")
        
    except ValueError as e:
        db.session.rollback()
        flash(f'Invalid transaction IDs: {str(e)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting transactions: {str(e)}', 'danger')
    
    # Redirect back to the return_url if provided to preserve filters
    return redirect(request.form.get('return_url') or url_for('transactions.index'))


@transactions_bp.route('/transactions/save-filter-preference', methods=['POST'])
def save_filter_preference():
    """Save user preference for filter section expansion"""
    try:
        data = request.get_json()
        expanded = data.get('expanded', False)
        
        Settings.set_value(
            'transactions_filter_expanded',
            expanded,
            description='Whether the transactions filter section is expanded by default',
            setting_type='boolean'
        )
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


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
                return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories)
            
            amount_str = request.form.get('amount', '')
            if not amount_str:
                flash('Please enter an amount', 'danger')
                accounts = Account.query.order_by(Account.name).all()
                categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
                return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories)
            
            amount = abs(float(amount_str))  # Ensure positive
            transfer_date = datetime.strptime(request.form.get('transaction_date'), '%Y-%m-%d').date()
            description = request.form.get('description', 'Transfer')
            category_id = request.form.get('category_id', type=int)
            is_paid = request.form.get('is_paid') == 'on'
            
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
                    return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories)
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
                payday_period = PaydayService.get_period_for_date(current_date)
                
                # Create transaction in FROM account (money leaving - negative amount)
                from_transaction = Transaction(
                    account_id=from_account_id,
                    category_id=transfer_category.id,
                    vendor_id=from_vendor.id,  # Vendor = destination account
                    amount=-amount,  # Negative = expense/debit (money out)
                    transaction_date=current_date,
                    description=f"Transfer to {to_account.name}",
                    item=description,
                    payment_type='Transfer',
                    is_paid=is_paid,
                    year_month=year_month,
                    week_year=week_year,
                    day_name=day_name,
                    payday_period=payday_period
                )
                
                # Create transaction in TO account (money arriving - positive amount)
                to_transaction = Transaction(
                    account_id=to_account_id,
                    category_id=transfer_category.id,
                    vendor_id=to_vendor.id,  # Vendor = source account
                    amount=amount,  # Positive = income/credit (money in)
                    transaction_date=current_date,
                    description=f"Transfer from {from_account.name}",
                    item=description,
                    payment_type='Transfer',
                    is_paid=is_paid,
                    year_month=year_month,
                    week_year=week_year,
                    day_name=day_name,
                    payday_period=payday_period
                )
                
                db.session.add(from_transaction)
                db.session.add(to_transaction)
                db.session.flush()  # Get IDs assigned
                
                # Link the transactions together
                from_transaction.linked_transaction_id = to_transaction.id
                to_transaction.linked_transaction_id = from_transaction.id
                
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
            return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories)
        except Exception as e:
            db.session.rollback()
            import traceback
            error_detail = traceback.format_exc()
            print(f"Transfer creation error: {error_detail}")  # Log to console
            flash(f'Error creating transfer: {str(e)}', 'danger')
            from datetime import date
            accounts = Account.query.order_by(Account.name).all()
            categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
            return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories, today=date.today())
    
    # GET request - show form
    from datetime import date
    accounts = Account.query.order_by(Account.name).all()
    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    
    return render_template(
        'transactions/transfer_form.html',
        accounts=accounts,
        categories=categories,
        today=date.today()
    )


@transactions_bp.route('/transactions/consolidated')
def consolidated():
    """Consolidated view of all transactions across all sources"""
    
    # Get filter parameters
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category_id = request.args.get('category_id', type=int)
    source = request.args.get('source')  # 'bank', 'credit_card', 'loan', 'all'
    
    # Build unified transaction list
    consolidated_transactions = []
    
    # 1. Bank Account Transactions
    if not source or source == 'all' or source == 'bank':
        bank_txns = Transaction.query
        
        if start_date:
            bank_txns = bank_txns.filter(Transaction.transaction_date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            bank_txns = bank_txns.filter(Transaction.transaction_date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        if category_id:
            bank_txns = bank_txns.filter(Transaction.category_id == category_id)
        
        for txn in bank_txns.all():
            consolidated_transactions.append({
                'id': f'bank_{txn.id}',
                'source': 'Bank Account',
                'source_type': 'bank',
                'source_name': txn.account.name if txn.account else 'Unknown',
                'date': txn.transaction_date,
                'description': txn.description,
                'category': f"{txn.category.head_budget} > {txn.category.sub_budget}" if txn.category else '',
                'amount': float(txn.amount),
                'balance': float(txn.running_balance) if txn.running_balance else None,
                'vendor': txn.vendor.name if txn.vendor else '',
                'type': 'Income' if txn.amount > 0 else 'Expense'
            })
    
    # 2. Credit Card Transactions
    if not source or source == 'all' or source == 'credit_card':
        cc_txns = CreditCardTransaction.query
        
        if start_date:
            cc_txns = cc_txns.filter(CreditCardTransaction.date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            cc_txns = cc_txns.filter(CreditCardTransaction.date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        if category_id:
            cc_txns = cc_txns.filter(CreditCardTransaction.category_id == category_id)
        
        for txn in cc_txns.all():
            consolidated_transactions.append({
                'id': f'cc_{txn.id}',
                'source': 'Credit Card',
                'source_type': 'credit_card',
                'source_name': txn.credit_card.card_name if txn.credit_card else 'Unknown',
                'date': txn.date,
                'description': txn.item,
                'category': f"{txn.head_budget} > {txn.sub_budget}" if txn.head_budget else '',
                'amount': float(txn.amount),
                'balance': float(txn.balance) if txn.balance else None,
                'vendor': '',
                'type': txn.transaction_type
            })
    
    # 3. Loan Payments
    if not source or source == 'all' or source == 'loan':
        loan_txns = LoanPayment.query
        
        if start_date:
            loan_txns = loan_txns.filter(LoanPayment.payment_date >= datetime.strptime(start_date, '%Y-%m-%d').date())
        if end_date:
            loan_txns = loan_txns.filter(LoanPayment.payment_date <= datetime.strptime(end_date, '%Y-%m-%d').date())
        
        for txn in loan_txns.all():
            consolidated_transactions.append({
                'id': f'loan_{txn.id}',
                'source': 'Loan',
                'source_type': 'loan',
                'source_name': txn.loan.name if txn.loan else 'Unknown',
                'date': txn.date,
                'description': f"Payment (Principal: £{txn.amount_paid_off:.2f}, Interest: £{txn.interest_charge:.2f})",
                'category': 'Loans > Payment',
                'amount': float(txn.payment_amount),
                'balance': float(txn.closing_balance) if txn.closing_balance else None,
                'vendor': '',
                'type': 'Loan Payment'
            })
    
    # Sort by date descending
    consolidated_transactions.sort(key=lambda x: x['date'], reverse=True)
    
    # Calculate totals
    total_inflows = sum([t['amount'] for t in consolidated_transactions if t['amount'] > 0])
    total_outflows = sum([abs(t['amount']) for t in consolidated_transactions if t['amount'] < 0])
    net_position = total_inflows - total_outflows
    
    # Get filter options
    accounts = Account.query.order_by(Account.name).all()
    credit_cards = CreditCard.query.order_by(CreditCard.card_name).all()
    loans = Loan.query.order_by(Loan.name).all()
    categories = Category.query.order_by(Category.head_budget, Category.sub_budget).all()
    
    return render_template('transactions/consolidated.html',
                         transactions=consolidated_transactions,
                         total_inflows=total_inflows,
                         total_outflows=total_outflows,
                         net_position=net_position,
                         accounts=accounts,
                         credit_cards=credit_cards,
                         loans=loans,
                         categories=categories,
                         selected_source=source,
                         selected_category=category_id,
                         start_date=start_date,
                         end_date=end_date)
