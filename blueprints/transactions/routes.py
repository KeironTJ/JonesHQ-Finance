from flask import render_template, request, redirect, url_for, flash, jsonify, current_app
from sqlalchemy import func, case
from datetime import datetime, timedelta, date, timezone
from decimal import Decimal
from collections import defaultdict
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
from models.users import User
from models.plans import Plan, PlanItem
from services.finance.payday_service import PaydayService
from services.finance.transaction_service import TransactionService
from services.planning.plan_link_service import PlanLinkService
from extensions import db
from models.expenses import Expense
from utils.assignment_helpers import get_assignment_options
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


def get_assigned_people_options():
    """Return family assignment options from members + custom family labels."""
    return get_assignment_options()


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
        target_transaction = family_get(Transaction, transaction_id)
        if target_transaction:
            # Set filters to the transaction's context
            account_id = target_transaction.account_id
            year_month = target_transaction.year_month
            is_paid_filter = None  # Show both paid and unpaid
            per_page = 100  # Increase per page to ensure transaction is visible
    
    # Default to current payday period and pending ONLY on first visit (no query params at all)
    if not request.args:
        today = date.today()
        # Use get_period_for_date to get the correct period that today falls into
        payday_period = PaydayService.get_period_for_date(today)
        is_paid_filter = 'pending'
    
    # Build query
    query = family_query(Transaction)
    
    if account_id:
        query = query.filter(Transaction.account_id == account_id)
    if head_budget:
        # Use a subquery so query never joins Category directly — keeps it safe
        # to join Category separately for the GROUP BY summary below.
        matching_cat_ids = family_query(Category).with_entities(Category.id).filter(
            Category.head_budget == head_budget
        )
        query = query.filter(Transaction.category_id.in_(matching_cat_ids))
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

    # --- Summary stats via a single aggregation query (no full row scan) ---
    stats = query.with_entities(
        func.count(Transaction.id).label('total'),
        func.sum(case((Transaction.amount > 0, Transaction.amount), else_=0)).label('income'),
        func.sum(case((Transaction.amount < 0, Transaction.amount), else_=0)).label('expenses'),
    ).one()
    total_count = stats.total or 0
    total_income = float(stats.income or 0)
    total_expenses = abs(float(stats.expenses or 0))
    net_balance = total_income - total_expenses

    # --- Category summary via GROUP BY (one SQL query, no full row scan) ---
    cat_rows = (
        query.order_by(None)
        .outerjoin(Category, Transaction.category_id == Category.id)
        .with_entities(
            Category.head_budget,
            Category.sub_budget,
            func.count(Transaction.id).label('cnt'),
            func.sum(Transaction.amount).label('total'),
        )
        .group_by(Category.head_budget, Category.sub_budget)
        .all()
    )
    summary = defaultdict(lambda: {'categories': defaultdict(lambda: {'count': 0, 'total': 0})})
    for row in cat_rows:
        if row.head_budget:
            summary[row.head_budget]['categories'][row.sub_budget or '']['count'] += row.cnt
            summary[row.head_budget]['categories'][row.sub_budget or '']['total'] += float(row.total or 0)
    for head in summary:
        summary[head]['total_count'] = sum(cat['count'] for cat in summary[head]['categories'].values())
        summary[head]['total_amount'] = sum(cat['total'] for cat in summary[head]['categories'].values())
    category_summary = dict(sorted(summary.items(), key=lambda x: abs(x[1]['total_amount']), reverse=True))

    # --- Running balance — one query per unique account on the page, not one per row ---
    # Collect the latest transaction date per account visible on this page
    account_max_date = {}
    for txn in transactions:
        if txn.account_id:
            if txn.account_id not in account_max_date or txn.transaction_date > account_max_date[txn.account_id]:
                account_max_date[txn.account_id] = txn.transaction_date

    # For each account, fetch all its transactions up to that date in one query
    # and accumulate running balances into a lookup dict keyed by transaction id.
    balance_map = {}
    for acct_id, max_date in account_max_date.items():
        acct_txns = family_query(Transaction).filter(
            Transaction.account_id == acct_id,
            Transaction.transaction_date <= max_date,
        ).order_by(Transaction.transaction_date.asc(), Transaction.id.asc()).all()
        running = Decimal('0')
        for t in acct_txns:
            running += Decimal(str(t.amount))
            balance_map[t.id] = running

    running_balances = [balance_map.get(txn.id, Decimal('0')) for txn in transactions]
    
    # Get filter options
    accounts = family_query(Account).order_by(Account.name).all()
    
    # Get unique head budgets for primary filter
    head_budgets = family_query(Category).with_entities(Category.head_budget).distinct().order_by(Category.head_budget).all()
    head_budgets = [hb[0] for hb in head_budgets if hb[0]]
    
    # Get categories (filtered by head_budget if selected)
    if head_budget:
        categories = family_query(Category).filter_by(head_budget=head_budget).order_by(Category.sub_budget).all()
    else:
        categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    
    # Get all categories for bulk edit dropdown (unfiltered)
    all_categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    
    vendors = family_query(Vendor).order_by(Vendor.name).all()
    
    # Get unique year_months from transactions
    year_months = family_query(Transaction).with_entities(Transaction.year_month).distinct().order_by(Transaction.year_month.desc()).all()
    year_months = [ym[0] for ym in year_months if ym[0]]
    
    # Get payday periods for filter - generate from min to max transaction dates
    min_date = family_query(Transaction).with_entities(func.min(Transaction.transaction_date)).scalar()
    max_date = family_query(Transaction).with_entities(func.max(Transaction.transaction_date)).scalar()
    
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
    # Expand if any filters are currently active
    has_active_filters = (
        account_id or head_budget or category_id or vendor_id or 
        year_month or payday_period or search or is_paid_filter
    )
    filter_expanded = Settings.get_value('transactions_filter_expanded', False)
    if has_active_filters:
        filter_expanded = True
    assigned_people_options = get_assigned_people_options()
    plans = family_query(Plan).filter(
        Plan.status.in_(['active', 'draft']),
    ).order_by(Plan.target_date.is_(None), Plan.target_date, Plan.title).all()
    plan_items = family_query(PlanItem).join(Plan).filter(
        Plan.status.in_(['active', 'draft']),
        PlanItem.status != 'skipped',
    ).order_by(Plan.title, PlanItem.title).all()
    linked_plan_items = family_query(PlanItem).filter(
        PlanItem.transaction_id.in_([transaction.id for transaction in transactions]),
    ).all() if transactions else []
    transaction_plan_links = {
        item.transaction_id: item for item in linked_plan_items
    }
    
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
        selected_account=family_get(Account, account_id) if account_id else None,
        selected_head_budget=head_budget,
        selected_category=family_get(Category, category_id) if category_id else None,
        selected_vendor=family_get(Vendor, vendor_id) if vendor_id else None,
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
        assigned_people_options=assigned_people_options,
        highlight_transaction_id=transaction_id,
        plans=plans,
        plan_items=plan_items,
        transaction_plan_links=transaction_plan_links,
    )


@transactions_bp.route('/transactions/create', methods=['GET', 'POST'])
def create():
    """Create a new transaction"""
    if request.method == 'POST':
        try:
            is_recurring = request.form.get('is_recurring') == 'on'
            if is_recurring and (
                request.form.get('plan_item_id') or request.form.get('new_plan_item_title')
            ):
                raise ValueError('A recurring batch cannot be linked to one plan item.')
            PlanLinkService.validate_form(request.form)
            transactions = TransactionService.create_transactions(request.form)
            transactions_created = len(transactions)
            PlanLinkService.sync(transactions[0], request.form)
            
            # Recalculate account balance
            Transaction.recalculate_account_balance(transactions[0].account_id)
            db.session.commit()
            
            if is_recurring:
                flash(f'{transactions_created} transactions created successfully! Account balance updated.', 'success')
            else:
                flash('Transaction created successfully! Account balance updated.', 'success')
            # Preserve the original return destination (submitted via hidden field) so
            # repeatedly redirecting back to this form doesn't overwrite it with itself
            return_url = request.form.get('return_url') or url_for('transactions.index')
            return redirect(url_for('transactions.create', return_url=return_url))
        except Exception as e:
            db.session.rollback()
            flash(f'Error creating transaction: {str(e)}', 'danger')
            return redirect(url_for('transactions.index'))
    
    # GET request - show form
    from datetime import date
    accounts = family_query(Account).order_by(Account.name).all()
    categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    vendors = family_query(Vendor).order_by(Vendor.name).all()
    assigned_people_options = get_assigned_people_options()
    plans, plan_items = PlanLinkService.get_options()
    return_url = request.args.get('return_url') or request.referrer or url_for('transactions.index')

    return render_template(
        'transactions/transaction_form.html',
        transaction=None,
        accounts=accounts,
        categories=categories,
        vendors=vendors,
        assigned_people_options=assigned_people_options,
        plans=plans,
        plan_items=plan_items,
        current_plan_item=None,
        action='Create',
        today=date.today(),
        return_url=return_url
    )


@transactions_bp.route('/transactions/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit a transaction"""
    transaction = family_get_or_404(Transaction, id)
    
    if request.method == 'POST':
        try:
            PlanLinkService.validate_form(request.form)
            transaction, old_account_id, linked_account_id = TransactionService.update_transaction(
                id, request.form
            )
            PlanLinkService.sync(transaction, request.form)
            
            # Sync changes to linked credit card payment if exists
            if transaction.credit_card_id:
                from services.finance.credit_card_service import CreditCardService
                CreditCardService.sync_bank_transaction_to_payment(transaction)
            
            # Sync changes to linked loan payment if exists
            if transaction.loan_id:
                from models.loan_payments import LoanPayment
                loan_payment = family_query(LoanPayment).filter_by(
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
    accounts = family_query(Account).order_by(Account.name).all()
    categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    vendors = family_query(Vendor).order_by(Vendor.name).all()
    assigned_people_options = get_assigned_people_options()
    plans, plan_items = PlanLinkService.get_options()
    current_plan_item = PlanLinkService.current_item(transaction.id)
    return_url = request.args.get('return_url') or request.referrer or url_for('transactions.index')

    return render_template(
        'transactions/transaction_form.html',
        transaction=transaction,
        accounts=accounts,
        categories=categories,
        vendors=vendors,
        assigned_people_options=assigned_people_options,
        plans=plans,
        plan_items=plan_items,
        current_plan_item=current_plan_item,
        action='Edit',
        return_url=return_url
    )


@transactions_bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a transaction"""
    try:
        account_id, account_name, linked_card_id, linked_transfer_account_id = (
            TransactionService.delete_transaction(id)
        )
        
        # Recalculate credit card balance if payment was deleted
        if linked_card_id:
            from models.credit_card_transactions import CreditCardTransaction
            CreditCardTransaction.recalculate_card_balance(linked_card_id)
        
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
    try:
        transaction = TransactionService.toggle_paid(id)
        
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
    transaction = family_get_or_404(Transaction, id)
    
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

        update_count, affected_accounts = TransactionService.bulk_edit(
            transaction_ids, request.form
        )
        for account_id in affected_accounts:
            if account_id:
                Transaction.recalculate_account_balance(account_id)
        db.session.commit()
        flash(f'{update_count} transactions updated successfully! All linked records have been synced. Account balances recalculated.', 'success')
        return redirect(request.form.get('return_url') or url_for('transactions.index'))
        
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
        deleted_count, accounts_to_recalc, cards_to_recalc = TransactionService.bulk_delete(
            transaction_ids
        )
        for account_id in accounts_to_recalc:
            if account_id:
                Transaction.recalculate_account_balance(account_id)
        for card_id in cards_to_recalc:
            CreditCardTransaction.recalculate_card_balance(card_id)
        db.session.commit()
        remaining_ids = [
            transaction.id for transaction in family_query(Transaction).filter(
                Transaction.id.in_(transaction_ids)
            ).all()
        ]
        if remaining_ids:
            flash(f'Deleted {deleted_count} transaction(s). However {len(remaining_ids)} could not be deleted: {remaining_ids}', 'warning')
        else:
            flash(f'Successfully deleted {deleted_count} transaction(s)', 'success')
        return redirect(request.form.get('return_url') or url_for('transactions.index'))
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
        return jsonify({'success': False, 'error': 'Unable to update the transaction.'}), 500


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
                accounts = family_query(Account).order_by(Account.name).all()
                categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
                return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories)
            
            amount_str = request.form.get('amount', '')
            if not amount_str:
                flash('Please enter an amount', 'danger')
                accounts = family_query(Account).order_by(Account.name).all()
                categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
                return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories)
            
            amount = abs(float(amount_str))  # Ensure positive
            transfer_date = datetime.strptime(request.form.get('transaction_date'), '%Y-%m-%d').date()
            description = request.form.get('description', 'Transfer')
            category_id = request.form.get('category_id', type=int)
            is_paid = request.form.get('is_paid') == '1'
            
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

            transactions, from_account, to_account = TransactionService.create_transfer(
                request.form
            )
            Transaction.recalculate_account_balance(from_account_id)
            Transaction.recalculate_account_balance(to_account_id)
            db.session.commit()
            transfers_created = len(transactions) // 2
            if is_recurring:
                flash(f'{transfers_created} transfers created: £{amount:.2f} {frequency} from {from_account.name} to {to_account.name}. Both account balances updated.', 'success')
            else:
                flash(f'Transfer created: £{amount:.2f} from {from_account.name} to {to_account.name}. Both account balances updated.', 'success')
            return redirect(request.referrer or url_for('transactions.index'))
            
        except ValueError as e:
            db.session.rollback()
            flash(f'Invalid input: {str(e)}', 'danger')
            accounts = family_query(Account).order_by(Account.name).all()
            categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
            return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories)
        except Exception as e:
            db.session.rollback()
            import traceback
            error_detail = traceback.format_exc()
            print(f"Transfer creation error: {error_detail}")  # Log to console
            flash(f'Error creating transfer: {str(e)}', 'danger')
            from datetime import date
            accounts = family_query(Account).order_by(Account.name).all()
            categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
            return render_template('transactions/transfer_form.html', accounts=accounts, categories=categories, today=date.today())
    
    # GET request - show form
    from datetime import date
    accounts = family_query(Account).order_by(Account.name).all()
    categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    
    return render_template(
        'transactions/transfer_form.html',
        accounts=accounts,
        categories=categories,
        today=date.today()
    )


@transactions_bp.route('/transactions/consolidated')
def consolidated():
    """Consolidated view of all transactions across all sources"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    category_id = request.args.get('category_id', type=int)
    source = request.args.get('source')
    payday_period = request.args.get('payday_period')
    is_paid_filter = request.args.get('is_paid')
    if not request.args:
        payday_period = PaydayService.get_period_for_date(date.today())

    data = TransactionService.get_consolidated_data(
        start_date=start_date,
        end_date=end_date,
        category_id=category_id,
        source=source,
        payday_period=payday_period,
        is_paid_filter=is_paid_filter,
    )
    return render_template(
        'transactions/consolidated.html',
        **data,
        accounts=family_query(Account).order_by(Account.name).all(),
        credit_cards=family_query(CreditCard).order_by(CreditCard.card_name).all(),
        loans=family_query(Loan).order_by(Loan.name).all(),
        categories=family_query(Category).order_by(Category.head_budget, Category.sub_budget).all(),
        selected_source=source,
        selected_category=category_id,
        selected_is_paid=is_paid_filter,
        start_date=start_date,
        end_date=end_date,
    )


