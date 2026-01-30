from flask import render_template, request, redirect, url_for, flash, jsonify
from . import expenses_bp
from extensions import db
from models.expenses import Expense
from models.credit_cards import CreditCard
from models.vehicles import Vehicle
from datetime import datetime
from decimal import Decimal
import csv
import io
import base64
from services.expense_sync_service import ExpenseSyncService
from flask import current_app


@expenses_bp.route('/expenses')
def index():
    """List expenses with simple filters"""
    expense_type = request.args.get('type')
    vehicle = request.args.get('vehicle')
    reimbursed = request.args.get('reimbursed')

    query = Expense.query
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
    credit_cards = CreditCard.query.order_by(CreditCard.card_name).all()
    vehicles = Vehicle.query.order_by(Vehicle.registration).all()

    return render_template(
        'expenses/index.html',
        expenses=expenses,
        credit_cards=credit_cards,
        vehicles=vehicles,
        selected_type=expense_type,
        selected_vehicle=vehicle,
        selected_reimbursed=reimbursed
    )


@expenses_bp.route('/expenses/toggle/<int:expense_id>/<string:field>', methods=['POST'])
def toggle_expense_flag(expense_id, field):
    """Toggle boolean flags: paid_for, submitted, reimbursed."""
    expense = Expense.query.get_or_404(expense_id)
    if field not in ('paid_for', 'submitted', 'reimbursed'):
        return jsonify({'error': 'invalid field'}), 400
    try:
        current = getattr(expense, field)
        setattr(expense, field, not bool(current))
        db.session.commit()
        # Reconcile after toggle (non-blocking)
        try:
            ExpenseSyncService.reconcile(expense.id)
        except Exception:
            flash('Warning: syncing linked transactions failed after toggle', 'warning')
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
        covered_miles = request.form.get('covered_miles') or None
        rate_per_mile = request.form.get('rate_per_mile') or None
        days = request.form.get('days') or 1
        total_cost = request.form.get('total_cost') or 0
        vehicle_registration = request.form.get('vehicle_registration') or None

        expense = Expense(
            date=date_val,
            description=description,
            expense_type=expense_type,
            credit_card_id=int(credit_card_id) if credit_card_id else None,
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
        # Reconcile linked transactions (non-blocking)
        try:
            ExpenseSyncService.reconcile(expense.id)
        except Exception:
            flash('Expense saved but syncing linked transactions failed', 'warning')
        flash('Expense added', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error adding expense: {str(e)}', 'danger')
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/expenses/update/<int:expense_id>', methods=['POST'])
def update_expense(expense_id):
    try:
        expense = Expense.query.get_or_404(expense_id)
        date_str = request.form.get('date')
        expense.date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else expense.date
        expense.description = request.form.get('description', expense.description)
        expense.expense_type = request.form.get('expense_type', expense.expense_type)
        credit_card_id = request.form.get('credit_card_id') or None
        expense.credit_card_id = int(credit_card_id) if credit_card_id else None
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
        # Reconcile linked transactions after update
        try:
            ExpenseSyncService.reconcile(expense.id)
        except Exception:
            flash('Expense updated but syncing linked transactions failed', 'warning')
        flash('Expense updated', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating expense: {str(e)}', 'danger')
    return redirect(url_for('expenses.index'))


@expenses_bp.route('/expenses/delete/<int:expense_id>', methods=['POST'])
def delete_expense(expense_id):
    try:
        expense = Expense.query.get_or_404(expense_id)
        db.session.delete(expense)
        db.session.commit()
        flash('Expense deleted', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting expense: {str(e)}', 'danger')
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
        flash(f'Error deleting linked transactions: {str(e)}', 'danger')
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
            exp = Expense.query.get(eid)
            if exp:
                db.session.delete(exp)
                deleted_count += 1

        db.session.commit()
        flash(f'Deleted {deleted_count} expense(s).', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting expenses: {str(e)}', 'danger')
    return redirect(request.form.get('return_url') or url_for('expenses.index'))
