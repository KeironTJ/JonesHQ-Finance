from flask import render_template, request, redirect, url_for, flash, jsonify
from . import loans_bp
from models.loans import Loan
from models.loan_payments import LoanPayment
from models.accounts import Account
from models.transactions import Transaction
from extensions import db
from services.loan_service import LoanService
from datetime import datetime, date
from dateutil.relativedelta import relativedelta


@loans_bp.route('/')
def index():
    """List all loans with summary statistics"""
    loans = Loan.query.all()
    
    # Calculate summary statistics for active loans
    active_loans = [loan for loan in loans if loan.is_active]
    
    # Calculate totals - use actual payment schedule data
    total_balance = 0.0
    total_monthly_payment = sum(float(loan.monthly_payment) for loan in active_loans)
    total_original = sum(float(loan.loan_value) for loan in active_loans)
    
    # Calculate actual paid amounts across all active loans
    total_paid = 0.0
    total_interest_paid = 0.0
    total_principal_paid = 0.0
    
    # Store principal paid for each loan for progress bars
    loan_principal_paid = {}
    
    for loan in active_loans:
        # Get actual current balance from payment schedule
        actual_balance = LoanService.calculate_remaining_balance(loan.id)
        total_balance += actual_balance
        
        # Update loan record if balance has changed
        if abs(float(loan.current_balance) - actual_balance) > 0.01:
            loan.current_balance = actual_balance
            db.session.add(loan)
        
        stats = LoanService.get_payment_statistics(loan.id)
        total_paid += stats['total_amount_paid']
        total_interest_paid += stats['total_interest_paid']
        total_principal_paid += stats['total_principal_paid']
        
        # Store principal paid for this loan
        loan_principal_paid[loan.id] = stats['total_principal_paid']
    
    # Commit any balance updates
    db.session.commit()
    
    active_count = len(active_loans)
    inactive_count = sum(1 for loan in loans if not loan.is_active)
    
    return render_template('loans/index.html', 
                         loans=loans,
                         total_balance=total_balance,
                         total_monthly_payment=total_monthly_payment,
                         total_original=total_original,
                         total_paid=total_paid,
                         total_interest_paid=total_interest_paid,
                         total_principal_paid=total_principal_paid,
                         loan_principal_paid=loan_principal_paid,
                         active_count=active_count,
                         inactive_count=inactive_count)


@loans_bp.route('/add', methods=['GET', 'POST'])
def add():
    """Add a new loan"""
    from models.accounts import Account
    
    if request.method == 'POST':
        try:
            # Parse dates
            start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
            term_months = int(request.form['term_months'])
            end_date = start_date + relativedelta(months=term_months)
            
            # Get default payment account
            default_payment_account_id = request.form.get('default_payment_account_id')
            if default_payment_account_id == '':
                default_payment_account_id = None
            
            loan = Loan(
                name=request.form['name'],
                loan_value=float(request.form['loan_value']),
                principal=float(request.form['loan_value']),  # Same as loan_value
                current_balance=float(request.form.get('current_balance', request.form['loan_value'])),
                annual_apr=float(request.form['annual_apr']),
                monthly_apr=float(request.form['annual_apr']) / 12,
                monthly_payment=float(request.form['monthly_payment']),
                start_date=start_date,
                end_date=end_date,
                term_months=term_months,
                default_payment_account_id=default_payment_account_id,
                is_active=request.form.get('is_active') == 'on'
            )
            
            db.session.add(loan)
            db.session.commit()
            
            flash(f'Loan "{loan.name}" added successfully!', 'success')
            return redirect(url_for('loans.detail', id=loan.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding loan: {str(e)}', 'danger')
            return redirect(url_for('loans.add'))
    
    accounts = Account.query.order_by(Account.name).all()
    return render_template('loans/form.html', loan=None, accounts=accounts)


@loans_bp.route('/<int:id>')
def detail(id):
    """View loan details with payment schedule"""
    loan = Loan.query.get_or_404(id)
    
    # Get all payments ordered by date
    payments = LoanPayment.query.filter_by(loan_id=id).order_by(LoanPayment.date).all()
    
    # Get statistics
    stats = LoanService.get_payment_statistics(id)
    
    # Calculate remaining months
    if payments:
        last_payment = payments[-1]
        remaining_months = loan.term_months - last_payment.period
    else:
        remaining_months = loan.term_months
    
    return render_template('loans/detail.html',
                         loan=loan,
                         payments=payments,
                         stats=stats,
                         remaining_months=remaining_months)


@loans_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """Edit a loan"""
    from models.accounts import Account
    loan = Loan.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            # Parse dates
            start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
            term_months = int(request.form['term_months'])
            end_date = start_date + relativedelta(months=term_months)
            
            # Get default payment account
            default_payment_account_id = request.form.get('default_payment_account_id')
            if default_payment_account_id == '':
                default_payment_account_id = None
            
            loan.name = request.form['name']
            loan.loan_value = float(request.form['loan_value'])
            loan.principal = float(request.form['loan_value'])
            loan.current_balance = float(request.form.get('current_balance', request.form['loan_value']))
            loan.annual_apr = float(request.form['annual_apr'])
            loan.monthly_apr = float(request.form['annual_apr']) / 12
            loan.monthly_payment = float(request.form['monthly_payment'])
            loan.start_date = start_date
            loan.end_date = end_date
            loan.term_months = term_months
            loan.default_payment_account_id = default_payment_account_id
            loan.is_active = request.form.get('is_active') == 'on'
            loan.updated_at = datetime.utcnow()
            
            db.session.commit()
            
            flash(f'Loan "{loan.name}" updated successfully!', 'success')
            return redirect(url_for('loans.detail', id=loan.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error updating loan: {str(e)}', 'danger')
    
    accounts = Account.query.order_by(Account.name).all()
    return render_template('loans/form.html', loan=loan, accounts=accounts)


@loans_bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a loan"""
    loan = Loan.query.get_or_404(id)
    
    try:
        # Delete all associated payments
        LoanPayment.query.filter_by(loan_id=id).delete()
        
        name = loan.name
        db.session.delete(loan)
        db.session.commit()
        
        flash(f'Loan "{name}" deleted successfully!', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting loan: {str(e)}', 'danger')
    
    return redirect(url_for('loans.index'))


@loans_bp.route('/<int:id>/generate', methods=['POST'])
def generate_schedule(id):
    """Generate amortization schedule for a loan"""
    loan = Loan.query.get_or_404(id)
    
    try:
        # Get end date from form, default to loan's end date
        end_date_str = request.form.get('end_date')
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = loan.end_date
        
        # Generate schedule
        payments = LoanService.generate_amortization_schedule(
            loan_id=id,
            start_date=loan.start_date,
            end_date=end_date
        )
        
        flash(f'Generated {len(payments)} payment records for "{loan.name}"', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error generating schedule: {str(e)}', 'danger')
    
    return redirect(url_for('loans.detail', id=id))


@loans_bp.route('/<int:id>/regenerate', methods=['POST'])
def regenerate_schedule(id):
    """Regenerate amortization schedule from today"""
    loan = Loan.query.get_or_404(id)
    
    try:
        # Get end date from form
        end_date_str = request.form.get('end_date')
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = loan.end_date
        
        # Regenerate from today
        result = LoanService.regenerate_schedule(
            loan_id=id,
            from_date=date.today(),
            end_date=end_date
        )
        
        flash(f'Regenerated schedule: {result["deleted"]} deleted, {result["created"]} created', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error regenerating schedule: {str(e)}', 'danger')
    
    return redirect(url_for('loans.detail', id=id))


@loans_bp.route('/<int:id>/payment/<int:payment_id>/toggle-paid', methods=['POST'])
def toggle_payment_paid(id, payment_id):
    """Toggle payment paid status and sync with bank transaction"""
    payment = LoanPayment.query.get_or_404(payment_id)
    
    try:
        payment.is_paid = not payment.is_paid
        
        # Sync bank transaction if it exists
        if payment.bank_transaction_id:
            bank_txn = Transaction.query.get(payment.bank_transaction_id)
            if bank_txn:
                bank_txn.is_paid = payment.is_paid
                # Recalculate account balance
                Transaction.recalculate_account_balance(bank_txn.account_id)
        
        db.session.commit()
        
        status = 'paid' if payment.is_paid else 'unpaid'
        return jsonify({'success': True, 'is_paid': payment.is_paid, 'status': status})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@loans_bp.route('/<int:id>/payment/<int:payment_id>/edit', methods=['POST'])
def edit_payment(id, payment_id):
    """Edit a loan payment"""
    try:
        loan = Loan.query.get_or_404(id)
        payment = LoanPayment.query.get_or_404(payment_id)
        
        # Verify payment belongs to this loan
        if payment.loan_id != loan.id:
            flash('Payment does not belong to this loan!', 'danger')
            return redirect(url_for('loans.detail', id=id))
        
        # Only allow editing Period 0 or unpaid payments
        if payment.is_paid and payment.period > 0:
            flash('Cannot edit a paid payment!', 'danger')
            return redirect(url_for('loans.detail', id=id))
        
        # Get form data
        payment_date_str = request.form.get('payment_date')
        payment_amount = request.form.get('payment_amount')
        interest_charge = request.form.get('interest_charge')
        amount_paid_off = request.form.get('amount_paid_off')
        
        # Update payment
        if payment_date_str:
            payment.date = datetime.strptime(payment_date_str, '%Y-%m-%d').date()
            payment.year_month = payment.date.strftime('%Y-%m')
        
        if payment_amount:
            payment.payment_amount = float(payment_amount)
        
        if interest_charge:
            payment.interest_charge = float(interest_charge)
        
        if amount_paid_off:
            payment.amount_paid_off = float(amount_paid_off)
        
        # Recalculate closing balance
        payment.closing_balance = payment.opening_balance - payment.amount_paid_off
        
        db.session.commit()
        
        # Sync changes to linked bank transaction if exists
        if payment.bank_transaction_id:
            bank_txn = Transaction.query.get(payment.bank_transaction_id)
            if bank_txn:
                # Update all relevant transaction fields
                bank_txn.transaction_date = payment.date
                bank_txn.amount = float(payment.payment_amount)
                bank_txn.description = f"Loan Payment - {loan.name}"
                bank_txn.item = f"Period {payment.period}"
                bank_txn.year_month = payment.date.strftime('%Y-%m')
                bank_txn.week_year = f"{payment.date.isocalendar()[1]:02d}-{payment.date.year}"
                bank_txn.day_name = payment.date.strftime('%a')
                bank_txn.updated_at = datetime.utcnow()
                
                db.session.commit()
                # Recalculate bank account balance
                Transaction.recalculate_account_balance(bank_txn.account_id)
        
        flash('Payment updated successfully!', 'success')
        return redirect(url_for('loans.detail', id=id))
        
    except ValueError:
        db.session.rollback()
        flash('Invalid payment data!', 'danger')
        return redirect(url_for('loans.detail', id=id))
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating payment: {str(e)}', 'danger')
        return redirect(url_for('loans.detail', id=id))


@loans_bp.route('/<int:id>/payment/<int:payment_id>/delete', methods=['POST'])
def delete_payment(id, payment_id):
    """Delete a loan payment and linked bank transaction"""
    try:
        loan = Loan.query.get_or_404(id)
        payment = LoanPayment.query.get_or_404(payment_id)
        
        # Verify payment belongs to this loan
        if payment.loan_id != loan.id:
            flash('Payment does not belong to this loan!', 'danger')
            return redirect(url_for('loans.detail', id=id))
        
        # Delete linked bank transaction if exists
        if payment.bank_transaction_id:
            bank_txn = Transaction.query.get(payment.bank_transaction_id)
            if bank_txn:
                account_id = bank_txn.account_id
                db.session.delete(bank_txn)
                # Recalculate bank account balance
                if account_id:
                    Transaction.recalculate_account_balance(account_id)
        
        # Delete the loan payment
        db.session.delete(payment)
        db.session.commit()
        
        flash('Payment deleted successfully!', 'success')
        return redirect(url_for('loans.detail', id=id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting payment: {str(e)}', 'danger')
        return redirect(url_for('loans.detail', id=id))


@loans_bp.route('/<int:id>/payments/bulk-delete', methods=['POST'])
def bulk_delete_payments(id):
    """Bulk delete multiple loan payments"""
    try:
        loan = Loan.query.get_or_404(id)
        payment_ids_str = request.form.get('payment_ids', '')
        
        if not payment_ids_str:
            flash('No payments selected', 'warning')
            return redirect(url_for('loans.detail', id=id))
        
        payment_ids = [int(pid) for pid in payment_ids_str.split(',') if pid]
        
        deleted_count = 0
        accounts_to_recalc = set()
        
        for payment_id in payment_ids:
            payment = LoanPayment.query.get(payment_id)
            if payment and payment.loan_id == loan.id:
                # Delete linked bank transaction if exists
                if payment.bank_transaction_id:
                    bank_txn = Transaction.query.get(payment.bank_transaction_id)
                    if bank_txn:
                        accounts_to_recalc.add(bank_txn.account_id)
                        db.session.delete(bank_txn)
                
                db.session.delete(payment)
                deleted_count += 1
        
        db.session.commit()
        
        # Recalculate balances for affected accounts
        for account_id in accounts_to_recalc:
            if account_id:
                Transaction.recalculate_account_balance(account_id)
        
        flash(f'Deleted {deleted_count} payment(s) successfully!', 'success')
        return redirect(url_for('loans.detail', id=id))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting payments: {str(e)}', 'danger')
        return redirect(url_for('loans.detail', id=id))


@loans_bp.route('/generate-all', methods=['POST'])
def generate_all():
    """Generate schedules for all active loans"""
    active_loans = Loan.query.filter_by(is_active=True).all()
    
    try:
        total_created = 0
        
        for loan in active_loans:
            payments = LoanService.generate_amortization_schedule(
                loan_id=loan.id,
                start_date=loan.start_date,
                end_date=loan.end_date,
                commit=False
            )
            total_created += len(payments)
        
        db.session.commit()
        
        flash(f'Generated {total_created} payment records for {len(active_loans)} active loans', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error generating schedules: {str(e)}', 'danger')
    
    return redirect(url_for('loans.index'))
