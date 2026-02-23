from flask import render_template, request, redirect, url_for, flash, jsonify
from . import expenses_bp
from extensions import db
from extensions import limiter
from models.expenses import Expense
from models.credit_cards import CreditCard
from models.credit_card_transactions import CreditCardTransaction
from models.accounts import Account
from models.vehicles import Vehicle
from models.trips import Trip
from models.transactions import Transaction
from datetime import datetime
from decimal import Decimal
import csv
import io
import base64
from services.expense_sync_service import ExpenseSyncService
from flask import current_app
from utils.db_helpers import family_query, family_get, family_get_or_404, get_family_id


@expenses_bp.route('/expenses')
def index():
    """List expenses with simple filters"""
    expense_type = request.args.get('type')
    vehicle = request.args.get('vehicle')
    reimbursed = request.args.get('reimbursed')
    highlight_id = request.args.get('id', type=int)

    query = family_query(Expense)
    if expense_type:
        query = query.filter(Expense.expense_type == expense_type)
    if vehicle:
        query = query.filter(Expense.vehicle_registration == vehicle)
    if reimbursed:
        if reimbursed == 'true':
            query = query.filter(Expense.reimbursed == True)
        elif reimbursed == 'false':
            query = query.filter(Expense.reimbursed == False)

    expenses = query.order_by(Expense.date.desc()).all()
    credit_cards = family_query(CreditCard).order_by(CreditCard.card_name).all()
    vehicles = family_query(Vehicle).order_by(Vehicle.registration).all()
    accounts = family_query(Account).filter_by(is_active=True).order_by(Account.name).all()
    
    # Get linked trips for fuel expenses (trips created by the sync service are
    # identified by the sentinel "Expense #<id>: " in journey_description)
    trips_dict = {}
    for exp in expenses:
        if exp.expense_type == 'Fuel' and exp.vehicle_registration:
            vehicle_obj = family_query(Vehicle).filter_by(registration=exp.vehicle_registration).first()
            if vehicle_obj:
                sentinel = f"Expense #{exp.id}: "
                trip = family_query(Trip).filter(
                    Trip.vehicle_id == vehicle_obj.id,
                    Trip.journey_description.like(sentinel + '%')
                ).first()
                if trip:
                    trips_dict[exp.id] = trip
    
    # Get reimbursement transactions by month
    reimbursement_txns = family_query(Transaction).filter_by(payment_type='Expense Reimbursement').all()
    reimbursements_by_month = {txn.year_month: txn for txn in reimbursement_txns}
    
    # Get CC payment transactions by month (these are CreditCardTransaction, not Transaction)
    cc_payment_txns = family_query(CreditCardTransaction).filter(
        CreditCardTransaction.transaction_type == 'Payment',
        CreditCardTransaction.item.like('%Expense reimbursement payment%')
    ).all()
    cc_payments_by_month = {}
    for txn in cc_payment_txns:
        # Item format: "Expense reimbursement payment YYYY-MM"
        # Key by the expense period (last 7 chars of item), NOT txn.month,
        # because the payment date is 1 working day after end-of-period so
        # txn.month is typically one calendar month ahead of the expense period.
        if txn.item and len(txn.item) >= 7:
            period_key = txn.item[-7:]
        else:
            period_key = txn.month
        if period_key not in cc_payments_by_month:
            cc_payments_by_month[period_key] = []
        cc_payments_by_month[period_key].append(txn)

    return render_template(
        'expenses/index.html',
        expenses=expenses,
        credit_cards=credit_cards,
        vehicles=vehicles,
        accounts=accounts,
        selected_type=expense_type,
        selected_vehicle=vehicle,
        selected_reimbursed=reimbursed,
        trips_dict=trips_dict,
        highlight_expense_id=highlight_id,
        reimbursements_by_month=reimbursements_by_month,
        cc_payments_by_month=cc_payments_by_month
    )


@expenses_bp.route('/expenses/toggle/<int:expense_id>/<string:field>', methods=['POST'])
@limiter.exempt
def toggle_expense_flag(expense_id, field):
    """Toggle boolean flags: paid_for, submitted, reimbursed."""
    expense = family_get_or_404(Expense, expense_id)
    if field not in ('paid_for', 'submitted', 'reimbursed'):
        return jsonify({'error': 'invalid field'}), 400
    try:
        current = getattr(expense, field)
        new_value = not bool(current)
        setattr(expense, field, new_value)
        
        # Two-way sync: If toggling paid_for, sync with linked transactions
        if field == 'paid_for':
            if expense.bank_transaction_id:
                bank_txn = family_get(Transaction, expense.bank_transaction_id)
                if bank_txn:
                    bank_txn.is_paid = new_value
            
            if expense.credit_card_transaction_id:
                cc_txn = family_get(CreditCardTransaction, expense.credit_card_transaction_id)
                if cc_txn:
                    cc_txn.is_paid = new_value

        # When reimbursed is toggled, mark the CC payment transaction for this period as paid/unpaid
        if field == 'reimbursed' and expense.credit_card_id:
            from services.expense_sync_service import ExpenseSyncService as _ESS
            period_key = _ESS.get_period_key_for_expense(expense)
            if period_key:
                cc_payment_txn = family_query(CreditCardTransaction).filter(
                    CreditCardTransaction.credit_card_id == expense.credit_card_id,
                    CreditCardTransaction.transaction_type == 'Payment',
                    CreditCardTransaction.item.like(f'%{period_key}%')
                ).first()
                if cc_payment_txn:
                    cc_payment_txn.is_paid = new_value
        
        db.session.commit()
        # Reconcile after toggle (non-blocking)
        try:
            ExpenseSyncService.reconcile(expense.id)
        except Exception as sync_err:
            current_app.logger.exception(f'Sync failed after toggle for expense {expense.id}')
            flash('Warning: syncing linked transactions failed after toggle — check the server log.', 'warning')
        return jsonify({'id': expense.id, 'field': field, 'value': getattr(expense, field)})
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@expenses_bp.route('/expenses/add', methods=['POST'])
def add_expense():
    try:
        date_str = request.form.get('date')
        date_val = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else None
        description = request.form.get('description')
        expense_type = request.form.get('expense_type')
        credit_card_id = request.form.get('credit_card_id') or None
        account_id = request.form.get('account_id') or None
        covered_miles = request.form.get('covered_miles') or None
        rate_per_mile = request.form.get('rate_per_mile') or None
        days = request.form.get('days') or 1
        total_cost = request.form.get('total_cost') or 0
        vehicle_registration = request.form.get('vehicle_registration') or None

        expense = Expense(
            date=date_val,
            month=date_val.strftime('%Y-%m') if date_val else None,
            week=f"{date_val.isocalendar()[1]:02d}-{date_val.year}" if date_val else None,
            day_name=date_val.strftime('%A') if date_val else None,
            finance_year=(
                f"{date_val.year}-{date_val.year + 1}" if date_val and date_val.month >= 4
                else (f"{date_val.year - 1}-{date_val.year}" if date_val else None)
            ),
            description=description,
            expense_type=expense_type,
            credit_card_id=int(credit_card_id) if credit_card_id else None,
            account_id=int(account_id) if account_id else None,
            covered_miles=int(covered_miles) if covered_miles else None,
            rate_per_mile=Decimal(rate_per_mile) if rate_per_mile else None,
            days=int(days) if days else 1,
            cost=Decimal(total_cost) if total_cost else Decimal('0.00'),
            total_cost=Decimal(total_cost) if total_cost else Decimal('0.00'),
            vehicle_registration=vehicle_registration,
            paid_for=request.form.get('paid_for') == 'on',
            submitted=request.form.get('submitted') == 'on',
            reimbursed=request.form.get('reimbursed') == 'on'
        )
        db.session.add(expense)
        db.session.commit()
        # Reconcile linked transaction, then run full period sync for this month
        try:
            ExpenseSyncService.reconcile(expense.id)
            _month = expense.date.strftime('%Y-%m') if expense.date else None
            ExpenseSyncService.reconcile_monthly_reimbursements(year_month=_month)
            ExpenseSyncService.reconcile_credit_card_payments(year_month=_month)
        except Exception as sync_err:
            current_app.logger.exception(f'Sync failed after add for expense {expense.id}')
            flash('Expense saved but syncing linked transactions failed — check the server log.', 'warning')
        flash('Expense added', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error adding expense')
        flash('Error adding expense \u2014 check the server log for details.', 'danger')
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/expenses/update/<int:expense_id>', methods=['POST'])
def update_expense(expense_id):
    try:
        expense = family_get_or_404(Expense, expense_id)
        date_str = request.form.get('date')
        expense.date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else expense.date
        # Re-derive date-based fields whenever the date may have changed
        d = expense.date
        if d:
            expense.month        = d.strftime('%Y-%m')
            expense.week         = f"{d.isocalendar()[1]:02d}-{d.year}"
            expense.day_name     = d.strftime('%A')
            expense.finance_year = (
                f"{d.year}-{d.year + 1}" if d.month >= 4
                else f"{d.year - 1}-{d.year}"
            )
        expense.description = request.form.get('description', expense.description)
        expense.expense_type = request.form.get('expense_type', expense.expense_type)
        credit_card_id = request.form.get('credit_card_id') or None
        expense.credit_card_id = int(credit_card_id) if credit_card_id else None
        account_id = request.form.get('account_id') or None
        expense.account_id = int(account_id) if account_id else None
        cm = request.form.get('covered_miles')
        expense.covered_miles = int(cm) if cm else None
        rpm = request.form.get('rate_per_mile')
        expense.rate_per_mile = Decimal(rpm) if rpm else None
        expense.days = int(request.form.get('days') or expense.days or 1)
        tc = request.form.get('total_cost')
        expense.cost = Decimal(tc) if tc else expense.cost
        expense.total_cost = Decimal(tc) if tc else expense.total_cost
        expense.vehicle_registration = request.form.get('vehicle_registration') or expense.vehicle_registration
        expense.paid_for = request.form.get('paid_for') == 'on'
        expense.submitted = request.form.get('submitted') == 'on'
        expense.reimbursed = request.form.get('reimbursed') == 'on'

        db.session.commit()
        # Reconcile linked transaction, then run full period sync for this month
        try:
            ExpenseSyncService.reconcile(expense.id)
            _month = expense.date.strftime('%Y-%m') if expense.date else None
            ExpenseSyncService.reconcile_monthly_reimbursements(year_month=_month)
            ExpenseSyncService.reconcile_credit_card_payments(year_month=_month)
        except Exception as sync_err:
            current_app.logger.exception(f'Sync failed after update for expense {expense.id}')
            flash('Expense updated but syncing linked transactions failed — check the server log.', 'warning')
        flash('Expense updated', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error updating expense')
        flash('Error updating expense — check the server log for details.', 'danger')
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/expenses/delete/<int:expense_id>', methods=['POST'])
def delete_expense(expense_id):
    try:
        expense = family_get_or_404(Expense, expense_id)
        # Delete linked bank/CC transactions first
        try:
            ExpenseSyncService.bulk_delete_linked_transactions(expense_ids=[expense.id])
        except Exception:
            current_app.logger.exception(f'Error deleting linked transactions for expense {expense_id}')
        # Delete the auto-created trip row for fuel expenses
        if expense.expense_type == 'Fuel':
            ExpenseSyncService.delete_fuel_trip_for_expense(expense)
        db.session.delete(expense)
        db.session.commit()
        flash('Expense deleted', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting expense')
        flash('Error deleting expense — check the server log for details.', 'danger')
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/expenses/bulk-delete-linked', methods=['POST'])
def bulk_delete_linked():
    """Delete linked transactions for selected expenses via UI action."""
    try:
        expense_ids_str = request.form.get('expense_ids', '')
        current_app.logger.info(f"Bulk delete linked called with expense_ids: {expense_ids_str}")
        if not expense_ids_str:
            flash('No expenses selected', 'warning')
            return redirect(request.form.get('return_url') or url_for('expenses.index'))

        expense_ids = [int(x) for x in expense_ids_str.split(',') if x]
        summary = ExpenseSyncService.bulk_delete_linked_transactions(expense_ids=expense_ids)
        deleted = summary.get('deleted_bank_txns', 0) + summary.get('deleted_cc_txns', 0)
        flash(f'Removed linked transactions for {len(summary.get("expenses_found", []))} expense(s). Deleted {deleted} linked transaction(s).', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting linked transactions')
        flash('Error deleting linked transactions — check the server log for details.', 'danger')
    return redirect(request.form.get('return_url') or url_for('expenses.index'))


@expenses_bp.route('/expenses/bulk-delete-expenses', methods=['POST'])
def bulk_delete_expenses():
    """Delete selected Expense rows (and any linked transactions)."""
    try:
        expense_ids_str = request.form.get('expense_ids', '')
        current_app.logger.info(f"Bulk delete expenses called with expense_ids: {expense_ids_str}")
        if not expense_ids_str:
            flash('No expenses selected', 'warning')
            return redirect(request.form.get('return_url') or url_for('expenses.index'))

        expense_ids = [int(x) for x in expense_ids_str.split(',') if x]

        # First remove any linked transactions for these expenses
        try:
            ExpenseSyncService.bulk_delete_linked_transactions(expense_ids=expense_ids)
        except Exception as e:
            current_app.logger.exception('Error deleting linked transactions before expense delete')

        deleted_count = 0
        for eid in expense_ids:
            exp = family_get(Expense, eid)
            if exp:
                db.session.delete(exp)
                deleted_count += 1

        db.session.commit()
        flash(f'Deleted {deleted_count} expense(s).', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error deleting expenses')
        flash('Error deleting expenses — check the server log for details.', 'danger')
    return redirect(request.form.get('return_url') or url_for('expenses.index'))

@expenses_bp.route('/expenses/generate-reimbursements', methods=['POST'])
def generate_reimbursements():
    """Generate monthly reimbursement transactions for submitted expenses"""
    try:
        year_month = request.form.get('year_month')  # Optional: specific month or all
        
        results = ExpenseSyncService.reconcile_monthly_reimbursements(year_month=year_month)
        
        if results:
            count = len(results)
            months = ', '.join(results.keys())
            flash(f'Created {count} monthly reimbursement transaction(s) for: {months}', 'success')
        else:
            flash('No reimbursement transactions created (no submitted expenses found)', 'info')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error generating reimbursements')
        flash('Error generating reimbursements — check the server log for details.', 'danger')
    
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/expenses/generate-cc-payments', methods=['POST'])
def generate_cc_payments():
    """Generate automatic credit card payment transactions 1 working day after reimbursement"""
    try:
        year_month = request.form.get('year_month')  # Optional: specific month or all
        
        results = ExpenseSyncService.reconcile_credit_card_payments(year_month=year_month)
        
        if results:
            count = len(results)
            flash(f'Created {count} credit card payment transaction(s)', 'success')
        else:
            flash('No credit card payment transactions created', 'info')
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Error generating CC payments')
        flash('Error generating credit card payments — check the server log for details.', 'danger')
    
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/expenses/generate-all', methods=['POST'])
def generate_all():
    """Run full sync in correct order: reimbursements first, then CC payments."""
    try:
        year_month = request.form.get('year_month') or None

        reimb_results = ExpenseSyncService.reconcile_monthly_reimbursements(year_month=year_month)
        cc_results    = ExpenseSyncService.reconcile_credit_card_payments(year_month=year_month)

        reimb_count = len(reimb_results)
        cc_count    = len(cc_results)

        if reimb_count or cc_count:
            parts = []
            if reimb_count:
                parts.append(f'{reimb_count} reimbursement(s) created/updated for {" ".join(reimb_results.keys())}')
            if cc_count:
                parts.append(f'{cc_count} CC payment(s) created/updated')
            flash('Sync complete: ' + ', '.join(parts) + '.', 'success')
        else:
            flash('Sync complete — everything already up to date.', 'info')
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Error during generate-all sync')
        flash('Sync failed — check the server log for details.', 'danger')

    return redirect(url_for('expenses.index'))