from flask import render_template, request, redirect, url_for, flash
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from . import credit_cards_bp
from models.credit_cards import CreditCard, CreditCardPromotion
from models.credit_card_transactions import CreditCardTransaction
from services.credit_card_service import CreditCardService
from extensions import db


@credit_cards_bp.route('/credit-cards')
def index():
    """List all credit cards with summary"""
    cards = CreditCard.query.order_by(CreditCard.is_active.desc(), CreditCard.card_name).all()
    
    # Calculate totals
    total_limit = sum([float(c.credit_limit) for c in cards if c.is_active])
    total_balance = sum([float(c.current_balance) for c in cards if c.is_active])
    total_available = sum([float(c.available_credit or 0) for c in cards if c.is_active])
    total_payments = sum([float(c.set_payment or 0) for c in cards if c.is_active])
    
    # Calculate weighted average APR
    if total_balance > 0:
        weighted_apr = sum([float(c.monthly_apr) * float(c.current_balance) for c in cards if c.is_active]) / total_balance
    else:
        weighted_apr = 0
    
    return render_template('credit_cards/index.html',
                         cards=cards,
                         total_limit=total_limit,
                         total_balance=total_balance,
                         total_available=total_available,
                         total_payments=total_payments,
                         weighted_apr=weighted_apr)


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
                is_active=request.form.get('is_active') == 'on'
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
    
    return render_template('credit_cards/form.html', card=None)


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
    
    return render_template('credit_cards/form.html', card=card)


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
    
    # Get all transactions for this card
    transactions = CreditCardTransaction.query.filter_by(
        credit_card_id=id
    ).order_by(CreditCardTransaction.date.desc()).all()
    
    # Calculate summary stats
    total_purchases = sum([float(t.amount) for t in transactions if t.transaction_type == 'Purchase'])
    total_payments = sum([abs(float(t.amount)) for t in transactions if t.transaction_type == 'Payment'])
    total_interest = sum([float(t.amount) for t in transactions if t.transaction_type == 'Interest'])
    
    # Get promotional offers
    promotions = CreditCardPromotion.query.filter_by(credit_card_id=id).order_by(
        CreditCardPromotion.end_date.desc()
    ).all()
    
    # Check active promotions
    today = date.today()
    active_purchase_promo = card.purchase_0_percent_until and today <= card.purchase_0_percent_until
    active_bt_promo = card.balance_transfer_0_percent_until and today <= card.balance_transfer_0_percent_until
    
    return render_template('credit_cards/detail.html',
                         card=card,
                         transactions=transactions,
                         promotions=promotions,
                         total_purchases=total_purchases,
                         total_payments=total_payments,
                         total_interest=total_interest,
                         active_purchase_promo=active_purchase_promo,
                         active_bt_promo=active_bt_promo)


@credit_cards_bp.route('/credit-cards/<int:id>/generate-future', methods=['POST'])
def generate_future(id):
    """Generate future monthly statements with intelligent payment triggering"""
    try:
        card = CreditCard.query.get_or_404(id)
        
        # Get date range from form or use defaults
        start_date = date.today()
        end_date_str = request.form.get('end_date')
        payment_offset = int(request.form.get('payment_offset', 14))
        
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = start_date + relativedelta(years=5)  # Default 5 years
        
        # Use intelligent statement generation
        results = CreditCardService.generate_future_monthly_statements(
            id, start_date, end_date, payment_offset_days=payment_offset
        )
        
        flash(
            f'Generated {results["statements_created"]} statements for {card.card_name}. '
            f'{results["payments_created"]} payments created, '
            f'{results["zero_balance_statements"]} zero-balance statements (no payment needed).',
            'success'
        )
        
    except Exception as e:
        flash(f'Error generating transactions: {str(e)}', 'danger')
    
    return redirect(url_for('credit_cards.detail', id=id))


@credit_cards_bp.route('/credit-cards/generate-all-future', methods=['POST'])
def generate_all_future():
    """Generate future monthly statements for all active cards with intelligent payment triggering"""
    try:
        end_date_str = request.form.get('end_date')
        payment_offset = int(request.form.get('payment_offset', 14))
        
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = date.today() + relativedelta(years=5)
        
        # Use intelligent statement generation
        results = CreditCardService.generate_all_monthly_statements(
            end_date=end_date,
            payment_offset_days=payment_offset
        )
        
        flash(
            f'Processed {results["cards_processed"]} cards. '
            f'Created {results["statements_created"]} statements and {results["payments_created"]} payments. '
            f'{results["zero_balance_statements"]} statements had zero balance (no payment needed).',
            'success'
        )
        
    except Exception as e:
        flash(f'Error generating transactions: {str(e)}', 'danger')
    
    return redirect(url_for('credit_cards.index'))
