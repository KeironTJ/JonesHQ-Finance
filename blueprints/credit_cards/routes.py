from flask import render_template, request, redirect, url_for, flash
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from . import credit_cards_bp
from models.credit_cards import CreditCard, CreditCardPromotion
from models.credit_card_transactions import CreditCardTransaction
from models.accounts import Account
from models.transactions import Transaction
from models.categories import Category
from models.settings import Settings
from services.credit_card_service import CreditCardService
from extensions import db


@credit_cards_bp.route('/credit-cards')
def index():
    """List all credit cards with summary"""
    cards = CreditCard.query.order_by(CreditCard.is_active.desc(), CreditCard.card_name).all()
    
    # Calculate actual balance from paid transactions only for each card
    for card in cards:
        if card.is_active:
            # Get the latest PAID transaction
            latest_paid = CreditCardTransaction.query.filter_by(
                credit_card_id=card.id,
                is_paid=True
            ).order_by(CreditCardTransaction.date.desc()).first()
            
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
            card = CreditCard(
                card_name=request.form.get('card_name'),
                annual_apr=float(request.form.get('annual_apr', 0)),
                monthly_apr=float(request.form.get('monthly_apr', 0)),
                min_payment_percent=float(request.form.get('min_payment_percent', 1.0)),
                credit_limit=float(request.form.get('credit_limit', 0)),
                set_payment=float(request.form.get('set_payment', 0)) if request.form.get('set_payment') else None,
                statement_date=int(request.form.get('statement_date')) if request.form.get('statement_date') else None,
                current_balance=float(request.form.get('current_balance', 0)),
                is_active=request.form.get('is_active') == 'on',
                default_payment_account_id=int(request.form.get('default_payment_account_id')) if request.form.get('default_payment_account_id') else None
            )
            
            # Handle start date
            if request.form.get('start_date'):
                card.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
            
            # Handle promotional periods
            if request.form.get('purchase_0_percent_until'):
                card.purchase_0_percent_until = datetime.strptime(request.form.get('purchase_0_percent_until'), '%Y-%m-%d').date()
            
            if request.form.get('balance_transfer_0_percent_until'):
                card.balance_transfer_0_percent_until = datetime.strptime(request.form.get('balance_transfer_0_percent_until'), '%Y-%m-%d').date()
            
            # Calculate available credit
            card.available_credit = float(card.credit_limit) - float(card.current_balance)
            
            db.session.add(card)
            db.session.commit()
            
            flash(f'Credit card "{card.card_name}" added successfully!', 'success')
            return redirect(url_for('credit_cards.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding credit card: {str(e)}', 'danger')
    
    # Get accounts for form
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    return render_template('credit_cards/form.html', card=None, accounts=accounts)


@credit_cards_bp.route('/credit-cards/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit a credit card"""
    card = CreditCard.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            card.card_name = request.form.get('card_name')
            card.annual_apr = float(request.form.get('annual_apr', 0))
            card.monthly_apr = float(request.form.get('monthly_apr', 0))
            card.min_payment_percent = float(request.form.get('min_payment_percent', 1.0))
            card.credit_limit = float(request.form.get('credit_limit', 0))
            card.set_payment = float(request.form.get('set_payment', 0)) if request.form.get('set_payment') else None
            card.statement_date = int(request.form.get('statement_date')) if request.form.get('statement_date') else None
            card.current_balance = float(request.form.get('current_balance', 0))
            card.is_active = request.form.get('is_active') == 'on'
            card.default_payment_account_id = int(request.form.get('default_payment_account_id')) if request.form.get('default_payment_account_id') else None
            card.default_payment_account_id = int(request.form.get('default_payment_account_id')) if request.form.get('default_payment_account_id') else None
            card.default_payment_account_id = int(request.form.get('default_payment_account_id')) if request.form.get('default_payment_account_id') else None
            
            # Handle start date
            if request.form.get('start_date'):
                card.start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
            
            # Handle promotional periods
            if request.form.get('purchase_0_percent_until'):
                card.purchase_0_percent_until = datetime.strptime(request.form.get('purchase_0_percent_until'), '%Y-%m-%d').date()
            else:
                card.purchase_0_percent_until = None
            
            if request.form.get('balance_transfer_0_percent_until'):
                card.balance_transfer_0_percent_until = datetime.strptime(request.form.get('balance_transfer_0_percent_until'), '%Y-%m-%d').date()
            else:
                card.balance_transfer_0_percent_until = None
            
            # Calculate available credit
            card.available_credit = float(card.credit_limit) - float(card.current_balance)
            card.updated_at = datetime.now()
            
            db.session.commit()
            
            flash(f'Credit card "{card.card_name}" updated successfully!', 'success')
            return redirect(url_for('credit_cards.index'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating credit card: {str(e)}', 'danger')
    
    # Get accounts for form
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    return render_template('credit_cards/form.html', card=card, accounts=accounts)


@credit_cards_bp.route('/credit-cards/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a credit card"""
    try:
        card = CreditCard.query.get_or_404(id)
        card_name = card.card_name
        
        db.session.delete(card)
        db.session.commit()
        
        flash(f'Credit card "{card_name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting credit card: {str(e)}', 'danger')
    
    return redirect(url_for('credit_cards.index'))


@credit_cards_bp.route('/credit-cards/<int:id>')
def detail(id):
    """View credit card details and transactions"""
    card = CreditCard.query.get_or_404(id)
    
    # Get transaction ID filter if provided
    transaction_id = request.args.get('txn_id', type=int)
    
    # Get all transactions for this card
    transactions = CreditCardTransaction.query.filter_by(
        credit_card_id=id
    ).order_by(CreditCardTransaction.date.desc()).all()
    
    # Calculate summary stats (only PAID transactions)
    total_purchases = sum([float(t.amount) for t in transactions if t.transaction_type == 'Purchase' and t.is_paid])
    total_payments = sum([abs(float(t.amount)) for t in transactions if t.transaction_type == 'Payment' and t.is_paid])
    total_interest = sum([float(t.amount) for t in transactions if t.transaction_type == 'Interest' and t.is_paid])
    
    # Get promotional offers
    promotions = CreditCardPromotion.query.filter_by(credit_card_id=id).order_by(
        CreditCardPromotion.end_date.desc()
    ).all()
    
    # Check active promotions
    today = date.today()
    active_purchase_promo = card.purchase_0_percent_until and today <= card.purchase_0_percent_until
    active_bt_promo = card.balance_transfer_0_percent_until and today <= card.balance_transfer_0_percent_until
    
    # Get all accounts for the account selector
    accounts = Account.query.filter_by(is_active=True).order_by(Account.name).all()
    
    return render_template('credit_cards/detail.html',
                         card=card,
                         transactions=transactions,
                         promotions=promotions,
                         total_purchases=total_purchases,
                         total_payments=total_payments,
                         total_interest=total_interest,
                         active_purchase_promo=active_purchase_promo,
                         active_bt_promo=active_bt_promo,
                         accounts=accounts,
                         today=today,
                         highlight_transaction_id=transaction_id)


@credit_cards_bp.route('/credit-cards/transaction/<int:txn_id>/toggle-fixed', methods=['POST'])
def toggle_fixed(txn_id):
    """Toggle is_fixed flag on a transaction"""
    try:
        txn = CreditCardTransaction.query.get_or_404(txn_id)
        txn.is_fixed = not txn.is_fixed
        db.session.commit()
        
        status = "locked" if txn.is_fixed else "unlocked"
        flash(f'Transaction {status} successfully!', 'success')
        
        return redirect(url_for('credit_cards.detail', id=txn.credit_card_id))
    except Exception as e:
        db.session.rollback()
        flash(f'Error toggling transaction: {str(e)}', 'danger')
        return redirect(request.referrer or url_for('credit_cards.index'))


@credit_cards_bp.route('/credit-cards/<int:id>/transaction/<int:txn_id>/edit', methods=['POST'])
def edit_transaction(id, txn_id):
    """Edit a credit card transaction"""
    try:
        card = CreditCard.query.get_or_404(id)
        txn = CreditCardTransaction.query.get_or_404(txn_id)
        
        # Verify transaction belongs to this card
        if txn.credit_card_id != card.id:
            flash('Transaction does not belong to this card!', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        # Only allow editing unpaid transactions
        if txn.is_paid:
            flash('Cannot edit a paid transaction!', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        # Get form data
        txn_date_str = request.form.get('txn_date')
        txn_type = request.form.get('txn_type')
        txn_item = request.form.get('txn_item')
        txn_amount = float(request.form.get('txn_amount'))
        txn_fixed = request.form.get('txn_fixed') == '1'
        
        # Update transaction
        if txn_date_str:
            txn.date = datetime.strptime(txn_date_str, '%Y-%m-%d').date()
            txn.day_name = txn.date.strftime('%A')
            txn.week = int(txn.date.strftime('%U'))
            txn.month = txn.date.strftime('%Y-%m')
        
        txn.transaction_type = txn_type
        txn.item = txn_item
        txn.amount = txn_amount
        txn.is_fixed = txn_fixed
        
        db.session.commit()
        
        # Sync changes to linked bank transaction if exists
        if txn.bank_transaction_id:
            CreditCardService.sync_payment_to_bank_transaction(txn)
        
        # Recalculate balance
        CreditCardTransaction.recalculate_card_balance(card.id)
        db.session.commit()
        
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


@credit_cards_bp.route('/credit-cards/<int:id>/transaction/<int:txn_id>/delete', methods=['POST'])
def delete_transaction(id, txn_id):
    """Delete a credit card transaction and linked bank transaction"""
    try:
        card = CreditCard.query.get_or_404(id)
        txn = CreditCardTransaction.query.get_or_404(txn_id)
        
        # Verify transaction belongs to this card
        if txn.credit_card_id != card.id:
            flash('Transaction does not belong to this card!', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        # Delete linked bank transaction if exists
        if txn.bank_transaction_id:
            from models.transactions import Transaction
            bank_txn = Transaction.query.get(txn.bank_transaction_id)
            if bank_txn:
                account_id = bank_txn.account_id
                db.session.delete(bank_txn)
                # Recalculate bank account balance
                if account_id:
                    from models.transactions import Transaction
                    Transaction.recalculate_account_balance(account_id)
        
        # Delete the credit card transaction
        db.session.delete(txn)
        db.session.commit()
        
        # Recalculate credit card balance
        CreditCardTransaction.recalculate_card_balance(card.id)
        
        flash('Transaction deleted successfully!', 'success')
        return redirect(url_for('credit_cards.detail', id=id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting transaction: {str(e)}', 'danger')
        return redirect(url_for('credit_cards.detail', id=id))


@credit_cards_bp.route('/credit-cards/<int:id>/payment/<int:txn_id>/edit', methods=['POST'])
def edit_payment(id, txn_id):
    """Edit a payment transaction amount and automatically lock it"""
    try:
        card = CreditCard.query.get_or_404(id)
        txn = CreditCardTransaction.query.get_or_404(txn_id)
        
        # Verify transaction belongs to this card
        if txn.credit_card_id != card.id:
            flash('Transaction does not belong to this card!', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        # Only allow editing Payment transactions
        if txn.transaction_type != 'Payment':
            flash('Only Payment transactions can be edited!', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        # Only allow editing future unpaid transactions
        if txn.is_paid:
            flash('Cannot edit a paid transaction!', 'danger')
            return redirect(url_for('credit_cards.detail', id=id))
        
        # Get form data
        payment_date_str = request.form.get('payment_date')
        payment_amount = float(request.form.get('payment_amount'))
        account_id = request.form.get('account_id', type=int)
        
        # Update transaction
        if payment_date_str:
            txn.date = datetime.strptime(payment_date_str, '%Y-%m-%d').date()
            # Update day/week/month for date
            txn.day_name = txn.date.strftime('%A')
            txn.week = int(txn.date.strftime('%U'))
            txn.month = txn.date.strftime('%Y-%m')
        
        # Store as positive amount (reduces debt)
        txn.amount = abs(payment_amount)
        
        # Automatically lock when edited
        txn.is_fixed = True
        
        # Handle account linking
        if account_id:
            # Find or create Credit Cards category
            credit_card_category = Category.query.filter_by(
                head_budget='Credit Cards',
                sub_budget='Aqua'  # Default sub-category
            ).first()
            
            if not credit_card_category:
                # Use first Credit Cards category or create generic one
                credit_card_category = Category.query.filter_by(head_budget='Credit Cards').first()
            
            # If there's an existing linked transaction, update it
            if txn.bank_transaction_id:
                bank_txn = Transaction.query.get(txn.bank_transaction_id)
                if bank_txn:
                    bank_txn.transaction_date = txn.date
                    bank_txn.amount = payment_amount  # Positive = expense from bank account
                    bank_txn.account_id = account_id
                    bank_txn.description = f'Payment to {card.card_name}'
                    bank_txn.item = f'Credit Card Payment'
                    if credit_card_category:
                        bank_txn.category_id = credit_card_category.id
                    bank_txn.updated_at = datetime.now()
            else:
                # Create new linked bank transaction
                bank_txn = Transaction(
                    account_id=account_id,
                    category_id=credit_card_category.id if credit_card_category else None,
                    amount=payment_amount,  # Positive = expense from bank account
                    transaction_date=txn.date,
                    description=f'Payment to {card.card_name}',
                    item='Credit Card Payment',
                    payment_type='Transfer',
                    is_paid=txn.is_paid,
                    is_fixed=True,
                    credit_card_id=card.id
                )
                db.session.add(bank_txn)
                db.session.flush()  # Get the ID
                
                # Link back to credit card transaction
                txn.bank_transaction_id = bank_txn.id
        
        db.session.commit()
        
        # Recalculate balance with new payment amount
        CreditCardTransaction.recalculate_card_balance(card.id)
        
        # Recalculate bank account balance if linked
        if account_id:
            Transaction.recalculate_account_balance(account_id)
        
        db.session.commit()
        
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
        txn = CreditCardTransaction.query.get_or_404(txn_id)
        txn.is_paid = not txn.is_paid
        
        # When marking as paid, also lock it to prevent regeneration
        if txn.is_paid:
            txn.is_fixed = True
        
        # Sync with linked expense if exists
        from models.expenses import Expense
        expense = Expense.query.filter_by(credit_card_transaction_id=txn.id).first()
        if expense:
            expense.paid_for = txn.is_paid
        
        db.session.commit()
        
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
        card = CreditCard.query.get_or_404(id)
        
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
