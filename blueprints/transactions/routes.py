from flask import render_template, request, redirect, url_for
from . import transactions_bp
from models.transactions import Transaction
from extensions import db


@transactions_bp.route('/transactions')
def index():
    """List all transactions"""
    transactions = Transaction.query.order_by(Transaction.transaction_date.desc()).all()
    return render_template('transactions.html', transactions=transactions)


@transactions_bp.route('/transactions/create', methods=['POST'])
def create():
    """Create a new transaction"""
    # Implementation here
    return redirect(url_for('transactions.index'))


@transactions_bp.route('/transactions/<int:id>/edit', methods=['POST'])
def edit(id):
    """Edit a transaction"""
    # Implementation here
    return redirect(url_for('transactions.index'))


@transactions_bp.route('/transactions/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete a transaction"""
    # Implementation here
    return redirect(url_for('transactions.index'))
