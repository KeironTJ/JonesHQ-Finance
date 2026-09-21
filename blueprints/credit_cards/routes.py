from flask import render_template, request, redirect, url_for, flash
from datetime import datetime, date, timezone
from dateutil.relativedelta import relativedelta
from decimal import Decimal
from . import credit_cards_bp
from models.credit_cards import CreditCard, CreditCardPromotion
from models.credit_card_transactions import CreditCardTransaction
from models.accounts import Account
from models.transactions import Transaction
from models.categories import Category
from models.vendors import Vendor
from models.settings import Settings
from models.plans import PlanItem
from services.finance.credit_card_service import CreditCardService
from services.finance.payday_service import PaydayService
from services.planning.plan_link_service import PlanLinkService
from extensions import db
from utils.assignment_helpers import get_assignment_options
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


@credit_cards_bp.route('/credit-cards')
def index():
    """List all credit cards with summary"""
    cards = family_query(CreditCard).order_by(CreditCard.is_active.desc(), CreditCard.card_name).all()
    
    # Calculate actual balance from paid transactions only for each card
    for card in cards:
        # Get the latest PAID transaction (with consistent ordering)
        latest_paid = family_query(CreditCardTransaction).filter_by(
            credit_card_id=card.id,
            is_paid=True
        ).order_by(CreditCardTransaction.date.desc(), CreditCardTransaction.id.desc()).first()
        
        if latest_paid:
            card.current_balance = latest_paid.balance
            card.available_credit = latest_paid.credit_available
        else:
            # No paid transactions yet, use opening balance
            card.current_balance = 0.00
            card.available_credit = float(card.credit_limit)
    
    # Calculate totals based on actual paid balances
    total_limit = sum([float(c.credit_limit) for c in cards if c.is_active])
    total_balance = sum([float(c.current_balance) for c in cards if c.is_active])
    total_available = sum([float(c.available_credit or 0) for c in cards if c.is_active])
    total_payments = sum([float(c.set_payment or 0) for c in cards if c.is_active])
    
    # Calculate weighted average APR based on absolute balance (debt owed)
    total_debt = sum([abs(float(c.current_balance)) for c in cards if c.is_active and c.current_balance < 0])
    if total_debt > 0:
        weighted_apr = sum([float(c.monthly_apr) * abs(float(c.current_balance)) for c in cards if c.is_active and c.current_balance < 0]) / total_debt
    else:
        weighted_apr = 0
    
    return render_template('credit_cards/index.html',
                         cards=cards,
                         total_limit=total_limit,
                         total_balance=total_balance,
                         total_available=total_available,
                         total_payments=total_payments,
                         weighted_apr=weighted_apr,
                         today=date.today())


@credit_cards_bp.route('/credit-cards/add', methods=['GET', 'POST'])
def add():
    """Add a new credit card"""
    if request.method == 'POST':
        try:
            card = CreditCardService.create_card(request.form)
            
            flash(f'Credit card "{card.card_name}" added successfully!', 'success')
            return redirect(url_for('credit_cards.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding credit card: {str(e)}', 'danger')
    
    # Get accounts for form
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    return render_template('credit_cards/form.html', card=None, accounts=accounts)


@credit_cards_bp.route('/credit-cards/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit a credit card"""
    card = family_get_or_404(CreditCard, id)
    
    if request.method == 'POST':
        try:
            card = CreditCardService.update_card(id, request.form)
            
            flash(f'Credit card "{card.card_name}" updated successfully!', 'success')
            return redirect(url_for('credit_cards.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating credit card: {str(e)}', 'danger')
    
    # Get accounts for form
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    return render_template('credit_cards/form.html', card=card, accounts=accounts)


@credit_cards_bp.route('/credit-cards/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a credit card"""
    try:
        card_name = CreditCardService.delete_card(id)
        
        flash(f'Credit card "{card_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting credit card: {str(e)}', 'danger')
    
    return redirect(url_for('credit_cards.index'))


@credit_cards_bp.route('/credit-cards/transfer', methods=['GET', 'POST'])
def create_balance_transfer():
    """Create a balance transfer between two of the family's credit cards"""
    cards = family_query(CreditCard).filter_by(is_active=True).order_by(CreditCard.card_name).all()

    if request.method == 'GET':
        from_card_id = request.args.get('from_card_id', type=int)
        return render_template('credit_cards/transfer_form.html',
                                cards=cards, from_card_id=from_card_id, today=date.today())

    try:
        from_card_id = request.form.get('from_card_id', type=int)
        to_card_id = request.form.get('to_card_id', type=int)

        if not from_card_id or not to_card_id:
            flash('Please select both cards', 'danger')
            return redirect(url_for('credit_cards.create_balance_transfer'))

        if from_card_id == to_card_id:
            flash('Source and destination cards must be different', 'danger')
            return redirect(url_for('credit_cards.create_balance_transfer'))

        amount_str = request.form.get('amount', '')
        if not amount_str or float(amount_str) <= 0:
            flash('Please enter a transfer amount greater than 0', 'danger')
            return redirect(url_for('credit_cards.create_balance_transfer'))

        result = CreditCardService.create_balance_transfer(request.form)
        flash(
            f"Balance transfer created: £{float(amount_str):.2f} moved from "
            f"{result['from_card'].card_name} to {result['to_card'].card_name}"
            + (f" (fee £{result['fee_amount']:.2f})" if result['fee_amount'] else '')
            + '.',
            'success'
        )
        return redirect(url_for('credit_cards.detail', id=to_card_id))
    except ValueError as e:
        db.session.rollback()
        flash(f'Invalid input: {str(e)}', 'danger')
        return redirect(url_for('credit_cards.create_balance_transfer'))
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating balance transfer: {str(e)}', 'danger')
        return redirect(url_for('credit_cards.create_balance_transfer'))


@credit_cards_bp.route('/credit-cards/<int:id>')
def detail(id):
    """View credit card details and transactions"""
    card = family_get_or_404(CreditCard, id)
    
    # Get transaction ID filter if provided
    transaction_id = request.args.get('txn_id', type=int)
    
    # Get all transactions for this card
    # Order by date DESC, then ID DESC for display (newest first)
    # This ensures same-day transactions appear in reverse chronological order
    all_transactions = family_query(CreditCardTransaction).filter_by(
        credit_card_id=id
    ).order_by(CreditCardTransaction.date.desc(), CreditCardTransaction.id.desc()).all()

    # Calculate current balance from latest PAID transaction
    # Must use same ordering as display (date DESC, id DESC) to get the truly latest
    latest_paid = family_query(CreditCardTransaction).filter_by(
        credit_card_id=id,
        is_paid=True
    ).order_by(CreditCardTransaction.date.desc(), CreditCardTransaction.id.desc()).first()
    
    if latest_paid:
        card.current_balance = latest_paid.balance
        card.available_credit = latest_paid.credit_available
    else:
        # No paid transactions yet, use opening balance
        card.current_balance = 0.00
        card.available_credit = float(card.credit_limit)
    
    # Calculate summary stats (only PAID transactions, across the whole card - not the filtered page)
    total_purchases = sum([float(t.amount) for t in all_transactions if t.transaction_type == 'Purchase' and t.is_paid])
    total_payments = sum([abs(float(t.amount)) for t in all_transactions if t.transaction_type == 'Payment' and t.is_paid])
    total_interest = sum([float(t.amount) for t in all_transactions if t.transaction_type == 'Interest' and t.is_paid])

    # --- Filters (search / type / status) ---
    search = request.args.get('search', '')
    txn_type_filter = request.args.get('txn_type', '')
    is_paid_filter = request.args.get('is_paid', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Default to pending-only on first visit (no query params at all)
    if not request.args:
        is_paid_filter = 'pending'

    filtered = all_transactions
    if search:
        search_lower = search.lower()
        filtered = [t for t in filtered if t.item and search_lower in t.item.lower()]
    if txn_type_filter:
        filtered = [t for t in filtered if t.transaction_type == txn_type_filter]
    if is_paid_filter == 'paid':
        filtered = [t for t in filtered if t.is_paid]
    elif is_paid_filter == 'pending':
        filtered = [t for t in filtered if not t.is_paid]

    transaction_count = len(filtered)
    total_pages = max(1, (transaction_count + per_page - 1) // per_page)
    page = min(max(page, 1), total_pages)
    start = (page - 1) * per_page
    transactions = filtered[start:start + per_page]

    # Get promotional offers
    promotions = family_query(CreditCardPromotion).filter_by(credit_card_id=id).order_by(
        CreditCardPromotion.end_date.desc()
    ).all()
    
    # Check active promotions
    today = date.today()
    active_purchase_promo = card.purchase_0_percent_until and today <= card.purchase_0_percent_until
    active_bt_promo = card.balance_transfer_0_percent_until and today <= card.balance_transfer_0_percent_until
    
    # Get all accounts for the account selector
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    
    # Get all categories for the add transaction modal
    categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
    plans, plan_items = PlanLinkService.get_options()
    linked_plan_items = family_query(PlanItem).filter(
        PlanItem.credit_card_transaction_id.in_([txn.id for txn in transactions]),
    ).all() if transactions else []
    transaction_plan_links = {item.credit_card_transaction_id: item for item in linked_plan_items}

    # Other active cards (for the "Balance Transfer" quick action)
    other_cards = family_query(CreditCard).filter(
        CreditCard.is_active == True, CreditCard.id != id
    ).order_by(CreditCard.card_name).all()

    return render_template('credit_cards/detail.html',
                         card=card,
                         transactions=transactions,
                         transaction_count=transaction_count,
                         page=page,
                         per_page=per_page,
                         total_pages=total_pages,
                         search_term=search,
                         selected_txn_type=txn_type_filter,
                         selected_is_paid=is_paid_filter,
                         other_cards=other_cards,
                         promotions=promotions,
                         total_purchases=total_purchases,
                         total_payments=total_payments,
                         total_interest=total_interest,
                         active_purchase_promo=active_purchase_promo,
                         active_bt_promo=active_bt_promo,
                         accounts=accounts,
                         categories=categories,
                         plans=plans,
                         plan_items=plan_items,
                         transaction_plan_links=transaction_plan_links,
                         assignment_options=get_assignment_options(),
                         today=today,
                         highlight_transaction_id=transaction_id)


@credit_cards_bp.route('/credit-cards/<int:id>/transaction/add', methods=['GET', 'POST'])
def add_transaction(id):
    """Add a new credit card transaction"""
    card = family_get_or_404(CreditCard, id)

    if request.method == 'GET':
        accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
        categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
        vendors = family_query(Vendor).filter_by(is_active=True).order_by(Vendor.name).all()
        plans, plan_items = PlanLinkService.get_options()
        return render_template('credit_cards/transaction_form.html',
                                card=card, transaction=None, accounts=accounts,
                                categories=categories, vendors=vendors, today=date.today(),
                                plans=plans, plan_items=plan_items,
                                assignment_options=get_assignment_options(),
                                current_plan_item=None)

    try:
        # Get form data
        txn_date_str = request.form.get('txn_date')
        txn_type = request.form.get('txn_type')
        txn_item = request.form.get('txn_item')
        txn_amount_str = request.form.get('txn_amount', '0')
        category_id = request.form.get('category_id') or None
        txn_fixed = request.form.get('txn_fixed') == '1'
        txn_paid = request.form.get('txn_paid') == '1'
        account_id_str = request.form.get('account_id')
        
        # Recurring options
        is_recurring = request.form.get('is_recurring') == 'on'
        frequency = request.form.get('frequency', 'monthly')
        occurrences = request.form.get('occurrences', type=int, default=1)
        
        # Validate required fields
        if not txn_date_str:
            flash('Date is required', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        if not txn_type:
            flash('Transaction type is required', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        if not txn_item:
            flash('Description is required', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        if is_recurring and occurrences < 1:
            flash('Number of occurrences must be at least 1', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        if is_recurring and (request.form.get('plan_item_id') or request.form.get('new_plan_item_title')):
            raise ValueError('A recurring batch cannot be linked to one plan item.')
        PlanLinkService.validate_form(request.form)
        
        # Parse amount
        try:
            txn_amount = float(txn_amount_str)
        except (ValueError, TypeError):
            flash('Invalid amount entered', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        # Parse account ID
        account_id = None
        if account_id_str and account_id_str.strip():
            try:
                account_id = int(account_id_str)
            except (ValueError, TypeError):
                flash('Invalid account selected', 'danger')
                return redirect(url_for('credit_cards.detail', id=id))
        
        # Parse date
        try:
            txn_date = datetime.strptime(txn_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('Invalid date format', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))

        transactions = CreditCardService.create_transactions(id, request.form)
        PlanLinkService.sync_credit_card(transactions[0], request.form)
        db.session.commit()
        if is_recurring:
            flash(f'{len(transactions)} transactions created successfully!', 'success')
        else:
            flash('Transaction added successfully!', 'success')
        return redirect(url_for('credit_cards.detail', id=id))
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding transaction: {str(e)}', 'danger')
        return redirect(url_for('credit_cards.add_transaction', id=id))


@credit_cards_bp.route('/credit-cards/transaction/<int:txn_id>/toggle-fixed', methods=['POST'])
def toggle_fixed(txn_id):
    """Toggle is_fixed flag on a transaction"""
    try:
        txn = CreditCardService.toggle_transaction_fixed(txn_id)
        
        status = "locked" if txn.is_fixed else "unlocked"
        flash(f'Transaction {status} successfully!', 'success')
        
        return redirect(url_for('credit_cards.detail', id=txn.credit_card_id))
    except Exception as e:
        db.session.rollback()
        flash(f'Error toggling transaction: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('credit_cards.index'))


@credit_cards_bp.route('/credit-cards/<int:id>/transaction/<int:txn_id>/edit', methods=['GET', 'POST'])
def edit_transaction(id, txn_id):
    """Edit a credit card transaction"""
    card = family_get_or_404(CreditCard, id)
    txn = family_get_or_404(CreditCardTransaction, txn_id)
    if txn.credit_card_id != card.id:
        flash('Transaction does not belong to this card!', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))

    if request.method == 'GET':
        accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
        categories = family_query(Category).order_by(Category.head_budget, Category.sub_budget).all()
        vendors = family_query(Vendor).filter_by(is_active=True).order_by(Vendor.name).all()
        plans, plan_items = PlanLinkService.get_options()
        current_plan_item = PlanLinkService.current_credit_card_item(txn.id)
        return render_template('credit_cards/transaction_form.html',
                                card=card, transaction=txn, accounts=accounts,
                                categories=categories, vendors=vendors, today=date.today(),
                                plans=plans, plan_items=plan_items,
                                assignment_options=get_assignment_options(),
                                current_plan_item=current_plan_item)

    try:
        PlanLinkService.validate_form(request.form)
        txn = CreditCardService.update_transaction(txn_id, request.form)
        PlanLinkService.sync_credit_card(txn, request.form)
        
        # Sync changes to linked bank transaction if exists
        if txn.bank_transaction_id:
            CreditCardService.sync_payment_to_bank_transaction(txn)
        
        # Recalculate balance (commits internally)
        CreditCardTransaction.recalculate_card_balance(card.id, commit=True)
        
        flash(f'Transaction updated successfully!', 'success')
        return redirect(url_for('credit_cards.detail', id=id))
        
    except ValueError:
        db.session.rollback()
        flash('Invalid transaction data!', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating transaction: {str(e)}', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))


@credit_cards_bp.route('/credit-cards/transaction/<int:txn_id>/link-plan', methods=['POST'])
def link_transaction_to_plan(txn_id):
    txn = family_get_or_404(CreditCardTransaction, txn_id)
    try:
        item = PlanLinkService.sync_credit_card(txn, request.form)
        db.session.commit()
    except ValueError as error:
        db.session.rollback()
        flash(str(error), 'danger')
        return redirect(url_for('credit_cards.detail', id=txn.credit_card_id, txn_id=txn.id))

    if item is None:
        flash('Credit-card transaction unlinked from its plan item.', 'success')
    else:
        flash(f'Credit-card transaction linked to {item.plan.title}: {item.title}.', 'success')
    return redirect(url_for('credit_cards.detail', id=txn.credit_card_id, txn_id=txn.id))


@credit_cards_bp.route('/credit-cards/<int:id>/transaction/<int:txn_id>/delete', methods=['POST'])
def delete_transaction(id, txn_id):
    """Delete a credit card transaction and linked bank transaction"""
    try:
        card = family_get_or_404(CreditCard, id)
        txn = family_get_or_404(CreditCardTransaction, txn_id)
        
        # Verify transaction belongs to this card
        if txn.credit_card_id != card.id:
            flash('Transaction does not belong to this card!', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        deleted_card_id, account_id = CreditCardService.delete_transaction(txn_id)
        if account_id:
            Transaction.recalculate_account_balance(account_id)
        
        flash('Transaction deleted successfully!', 'success')
        return redirect(url_for('credit_cards.detail', id=id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting transaction: {str(e)}', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))


@credit_cards_bp.route('/credit-cards/<int:id>/payment/<int:txn_id>/edit', methods=['GET', 'POST'])
def edit_payment(id, txn_id):
    """Edit a payment transaction amount and automatically lock it"""
    card = family_get_or_404(CreditCard, id)
    txn = family_get_or_404(CreditCardTransaction, txn_id)

    if txn.credit_card_id != card.id:
        flash('Transaction does not belong to this card!', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))

    if txn.transaction_type != 'Payment':
        flash('Only Payment transactions can be edited!', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))

    if txn.is_paid:
        flash('Cannot edit a paid transaction!', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))

    if request.method == 'GET':
        accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
        return render_template('credit_cards/payment_form.html', card=card, transaction=txn, accounts=accounts)

    try:
        txn, account_id = CreditCardService.update_payment_transaction(
            txn_id, request.form
        )
        payment_amount = float(txn.amount)
        CreditCardTransaction.recalculate_card_balance(card.id, commit=True)
        
        # Recalculate bank account balance if linked
        if account_id:
            Transaction.recalculate_account_balance(account_id)
        
        flash(f'Payment updated to £{payment_amount:.2f} and locked successfully!', 'success')
        return redirect(url_for('credit_cards.detail', id=id))
        
    except ValueError:
        db.session.rollback()
        flash('Invalid payment amount!', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating payment: {str(e)}', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))


@credit_cards_bp.route('/credit-cards/transaction/<int:txn_id>/toggle-paid', methods=['POST'])
def toggle_paid(txn_id):
    """Toggle is_paid flag on a transaction and lock it when paid"""
    try:
        txn = CreditCardService.toggle_transaction_paid(txn_id)
        
        status = "paid and locked" if txn.is_paid else "unpaid"
        flash(f'Transaction marked as {status} successfully!', 'success')
        
        return redirect(url_for('credit_cards.detail', id=txn.credit_card_id))
    except Exception as e:
        db.session.rollback()
        flash(f'Error toggling paid status: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('credit_cards.index'))


@credit_cards_bp.route('/credit-cards/<int:id>/generate-future', methods=['POST'])
def generate_future(id):
    """Regenerate future monthly statements (deletes unlocked, keeps locked)"""
    try:
        card = family_get_or_404(CreditCard, id)
        
        # Get date range from form or use defaults
        start_date = date.today()
        end_date_str = request.form.get('end_date')
        payment_offset = int(request.form.get('payment_offset', 14))
        
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            # Use configured default or 10 years
            default_years = Settings.get_value('default_generation_years', 10)
            end_date = start_date + relativedelta(years=default_years)
        
        # Use regenerate to delete non-fixed and recreate
        results = CreditCardService.regenerate_future_transactions(
            id, start_date, end_date, payment_offset_days=payment_offset
        )
        
        flash(
            f'Regenerated transactions for {card.card_name}. '
            f'Deleted {results["deleted_count"]} unlocked transactions, '
            f'created {results["statements_created"]} statements and '
            f'{results["payments_created"]} payments.',
            'success'
        )
        
    except Exception as e:
        flash(f'Error generating transactions: {str(e)}', 'danger')
    
    return redirect(url_for('credit_cards.detail', id=id))


@credit_cards_bp.route('/credit-cards/generate-all-future', methods=['POST'])
def generate_all_future():
    """Regenerate future monthly statements for all active cards (deletes unlocked, keeps locked)"""
    try:
        end_date_str = request.form.get('end_date')
        payment_offset = int(request.form.get('payment_offset', 14))
        
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            # Use configured default or 10 years
            default_years = Settings.get_value('default_generation_years', 10)
            end_date = date.today() + relativedelta(years=default_years)
        
        # Use regenerate to delete non-fixed and recreate
        results = CreditCardService.regenerate_all_future_transactions(
            end_date=end_date,
            payment_offset_days=payment_offset
        )
        
        flash(
            f'Processed {results["cards_processed"]} cards. '
            f'Deleted {results["total_deleted"]} unlocked transactions. '
            f'Created {results["total_statements"]} statements and {results["total_payments"]} payments.',
            'success'
        )
        
    except Exception as e:
        flash(f'Error generating transactions: {str(e)}', 'danger')
    
    return redirect(url_for('credit_cards.index'))
