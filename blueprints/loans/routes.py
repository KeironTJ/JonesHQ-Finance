from flask import render_template, request, redirect, url_for, flash, jsonify
from . import loans_bp
from models.loans import Loan
from models.loan_payments import LoanPayment
from models.loan_term_changes import LoanTermChange
from models.accounts import Account
from models.transactions import Transaction
from extensions import db
from services.loan_service import LoanService
from datetime import datetime, date, timezone
from dateutil.relativedelta import relativedelta
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


@loans_bp.route('/')
def index():
    """List all loans with summary statistics"""
    loans = family_query(Loan).all()
    
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
    """Add a new loan — saves the loan and immediately generates the full amortization schedule."""
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
                principal=float(request.form['loan_value']),
                current_balance=float(request.form.get('current_balance', request.form['loan_value'])),
                annual_apr=float(request.form['annual_apr']),
                monthly_apr=float(request.form['annual_apr']) / 12,
                monthly_payment=float(request.form['monthly_payment']),
                start_date=start_date,
                end_date=end_date,
                term_months=term_months,
                default_payment_account_id=default_payment_account_id,
                weekend_adjustment=request.form.get('weekend_adjustment', 'none'),
                is_active=request.form.get('is_active') == 'on'
            )
            
            db.session.add(loan)
            db.session.commit()

            # Auto-generate amortization schedule immediately
            payments = LoanService.generate_amortization_schedule(
                loan_id=loan.id,
                start_date=loan.start_date,
                end_date=loan.end_date,
                commit=True
            )
            
            flash(f'Loan "{loan.name}" created with {len(payments)} payment records.', 'success')
            return redirect(url_for('loans.detail', id=loan.id))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error adding loan: {str(e)}', 'danger')
            return redirect(url_for('loans.add'))
    
    accounts = family_query(Account).order_by(Account.name).all()
    return render_template('loans/form.html', loan=None, accounts=accounts, has_paid_payments=False)


@loans_bp.route('/<int:id>')
def detail(id):
    """View loan details with payment schedule"""
    loan = family_get_or_404(Loan, id)
    
    # Get all payments ordered by date
    payments = family_query(LoanPayment).filter_by(loan_id=id).order_by(LoanPayment.date).all()
    
    # Get statistics
    stats = LoanService.get_payment_statistics(id)
    
    # Get term change history
    term_changes = family_query(LoanTermChange).filter_by(loan_id=id)\
        .order_by(LoanTermChange.effective_date.desc()).all()
    
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
                         term_changes=term_changes,
                         remaining_months=remaining_months,
                         today=date.today())


@loans_bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    """
    Edit a loan.

    Behaviour depends on whether any payments have been marked paid:

    Live loan (has paid payments):
      Only metadata fields are editable — name, default account, weekend
      adjustment, and active status.  Schedule fields (APR, payment amount,
      dates, term) are locked; use Apply Term Change instead.

    New / unstarted loan (no paid payments):
      All fields are editable.  After saving, the entire payment schedule is
      deleted and regenerated from scratch so it stays in sync.
    """
    from models.accounts import Account
    loan = family_get_or_404(Loan, id)

    # Determine if the loan has any paid payments (period > 0)
    has_paid_payments = family_query(LoanPayment).filter(
        LoanPayment.loan_id == id,
        LoanPayment.is_paid == True,
        LoanPayment.period > 0
    ).first() is not None

    if request.method == 'POST':
        try:
            # Get default payment account
            default_payment_account_id = request.form.get('default_payment_account_id')
            if default_payment_account_id == '':
                default_payment_account_id = None

            # Always-editable metadata fields
            loan.name = request.form['name']
            loan.default_payment_account_id = default_payment_account_id
            loan.weekend_adjustment = request.form.get('weekend_adjustment', 'none')
            loan.is_active = request.form.get('is_active') == 'on'
            loan.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

            if not has_paid_payments:
                # Full edit allowed — update all schedule fields and regenerate
                start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
                term_months = int(request.form['term_months'])
                end_date = start_date + relativedelta(months=term_months)

                loan.loan_value = float(request.form['loan_value'])
                loan.principal = float(request.form['loan_value'])
                loan.current_balance = float(request.form.get('current_balance', request.form['loan_value']))
                loan.annual_apr = float(request.form['annual_apr'])
                loan.monthly_apr = float(request.form['annual_apr']) / 12
                loan.monthly_payment = float(request.form['monthly_payment'])
                loan.start_date = start_date
                loan.end_date = end_date
                loan.term_months = term_months

                db.session.commit()

                # Wipe existing schedule and regenerate from scratch
                LoanService.delete_future_payments(loan_id=id, from_date=loan.start_date, commit=True)
                payments = LoanService.generate_amortization_schedule(
                    loan_id=id,
                    start_date=loan.start_date,
                    end_date=loan.end_date,
                    commit=True
                )
                flash(f'Loan "{loan.name}" updated — schedule regenerated ({len(payments)} payments).', 'success')
            else:
                # Live loan — metadata only, schedule unchanged
                db.session.commit()
                flash(f'Loan "{loan.name}" details updated. To change rates or payment amounts, use Apply Term Change.', 'success')

            return redirect(url_for('loans.detail', id=loan.id))

        except Exception as e:
            db.session.rollback()
            flash(f'Error updating loan: {str(e)}', 'danger')

    accounts = family_query(Account).order_by(Account.name).all()
    return render_template('loans/form.html', loan=loan, accounts=accounts, has_paid_payments=has_paid_payments)


@loans_bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a loan"""
    loan = family_get_or_404(Loan, id)
    
    try:
        # Delete all associated payments
        family_query(LoanPayment).filter_by(loan_id=id).delete()
        
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
    loan = family_get_or_404(Loan, id)
    
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
    loan = family_get_or_404(Loan, id)
    
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
    payment = family_get_or_404(LoanPayment, payment_id)
    
    try:
        payment.is_paid = not payment.is_paid
        
        # Sync bank transaction if it exists
        if payment.bank_transaction_id:
            bank_txn = family_get(Transaction, payment.bank_transaction_id)
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
        loan = family_get_or_404(Loan, id)
        payment = family_get_or_404(LoanPayment, payment_id)
        
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
            bank_txn = family_get(Transaction, payment.bank_transaction_id)
            if bank_txn:
                from services.payday_service import PaydayService
                # Update all relevant transaction fields
                bank_txn.transaction_date = payment.date
                bank_txn.amount = -float(payment.payment_amount)  # Negative = expense (money out)
                bank_txn.description = f"Loan Payment - {loan.name}"
                bank_txn.item = f"Period {payment.period}"
                bank_txn.year_month = payment.date.strftime('%Y-%m')
                bank_txn.week_year = f"{payment.date.isocalendar()[1]:02d}-{payment.date.year}"
                bank_txn.day_name = payment.date.strftime('%a')
                bank_txn.payday_period = PaydayService.get_period_for_date(payment.date)
                bank_txn.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                
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
        loan = family_get_or_404(Loan, id)
        payment = family_get_or_404(LoanPayment, payment_id)
        
        # Verify payment belongs to this loan
        if payment.loan_id != loan.id:
            flash('Payment does not belong to this loan!', 'danger')
            return redirect(url_for('loans.detail', id=id))
        
        # Delete linked bank transaction if exists
        if payment.bank_transaction_id:
            bank_txn = family_get(Transaction, payment.bank_transaction_id)
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
        loan = family_get_or_404(Loan, id)
        payment_ids_str = request.form.get('payment_ids', '')
        
        if not payment_ids_str:
            flash('No payments selected', 'warning')
            return redirect(url_for('loans.detail', id=id))
        
        payment_ids = [int(pid) for pid in payment_ids_str.split(',') if pid]
        
        deleted_count = 0
        accounts_to_recalc = set()
        
        for payment_id in payment_ids:
            payment = family_get(LoanPayment, payment_id)
            if payment and payment.loan_id == loan.id:
                # Delete linked bank transaction if exists
                if payment.bank_transaction_id:
                    bank_txn = family_get(Transaction, payment.bank_transaction_id)
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


@loans_bp.route('/<int:id>/update-payment-day', methods=['POST'])
def update_payment_day(id):
    """Update the day-of-month for all future unpaid payments"""
    loan = family_get_or_404(Loan, id)

    try:
        new_day = int(request.form.get('payment_day', 0))
        if not (1 <= new_day <= 31):
            flash('Payment day must be between 1 and 31.', 'danger')
            return redirect(url_for('loans.detail', id=id))

        updated = LoanService.update_future_payment_dates(
            loan_id=id,
            new_day=new_day,
            from_date=date.today()
        )

        flash(f'Updated {updated} future payment(s) to day {new_day} of each month.', 'success')

    except Exception as e:
        db.session.rollback()
        flash(f'Error updating payment dates: {str(e)}', 'danger')

    return redirect(url_for('loans.detail', id=id))


@loans_bp.route('/<int:id>/apply-term-change', methods=['POST'])
def apply_term_change(id):
    """
    Apply a mid-loan term change (APR, payment amount, payment day, or term length).
    Deletes future unpaid payments and regenerates the schedule from the effective date.
    """
    loan = family_get_or_404(Loan, id)

    try:
        effective_date_str = request.form.get('effective_date', '').strip()
        if not effective_date_str:
            flash('Effective date is required.', 'danger')
            return redirect(url_for('loans.detail', id=id))

        effective_date = datetime.strptime(effective_date_str, '%Y-%m-%d').date()

        # Collect only fields that were actually supplied in the form
        new_monthly_payment = request.form.get('new_monthly_payment', '').strip() or None
        new_annual_apr      = request.form.get('new_annual_apr', '').strip() or None
        new_payment_day_str = request.form.get('new_payment_day', '').strip()
        new_payment_day     = int(new_payment_day_str) if new_payment_day_str else None
        new_term_months_str = request.form.get('new_term_months', '').strip()
        new_term_months     = int(new_term_months_str) if new_term_months_str else None
        notes               = request.form.get('notes', '').strip() or None

        if new_payment_day is not None and not (1 <= new_payment_day <= 31):
            flash('Payment day must be between 1 and 31.', 'danger')
            return redirect(url_for('loans.detail', id=id))

        result = LoanService.apply_term_change(
            loan_id=id,
            effective_date=effective_date,
            new_monthly_payment=new_monthly_payment,
            new_annual_apr=new_annual_apr,
            new_payment_day=new_payment_day,
            new_term_months=new_term_months,
            notes=notes,
        )

        summary = result['term_change'].change_summary
        flash(
            f'Term change applied from {effective_date}: {summary}. '
            f'{result["deleted"]} payment(s) replaced with {result["created"]} new record(s).',
            'success'
        )

    except ValueError as e:
        db.session.rollback()
        flash(str(e), 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error applying term change: {str(e)}', 'danger')

    return redirect(url_for('loans.detail', id=id))


@loans_bp.route('/generate-all', methods=['POST'])
def generate_all():
    """Generate schedules for all active loans"""
    active_loans = family_query(Loan).filter_by(is_active=True).all()
    
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
