from flask import render_template, request, redirect, url_for, flash
from . import accounts_bp
from models.accounts import Account
from models.transactions import Transaction
from extensions import db
from decimal import Decimal


@accounts_bp.route('/accounts')
def index():
    """List all accounts"""
    accounts = Account.query.all()
    
    # Calculate actual balances from PAID transactions for each account
    for account in accounts:
        paid_transactions = Transaction.query.filter_by(
            account_id=account.id,
            is_paid=True
        ).all()
        
        # Calculate balance: positive = income (adds), negative = expense (subtracts)
        balance = Decimal('0.00')
        for txn in paid_transactions:
            # Simply add the amount (positive adds, negative subtracts)
            balance += Decimal(str(txn.amount))
        
        account.calculated_balance = float(balance)
    
    # Calculate totals by type
    active_accounts = [a for a in accounts if a.is_active]
    inactive_accounts = [a for a in accounts if not a.is_active]
    
    # Use calculated balances for total
    total_balance = sum([a.calculated_balance for a in active_accounts])
    
    # Group by type
    accounts_by_type = {}
    for account in active_accounts:
        if account.account_type not in accounts_by_type:
            accounts_by_type[account.account_type] = []
        accounts_by_type[account.account_type].append(account)
    
    # Calculate type totals using calculated balances
    type_totals = {
        acc_type: sum([a.calculated_balance for a in accs])
        for acc_type, accs in accounts_by_type.items()
    }
    
    return render_template('accounts/index.html', 
                         accounts=accounts,
                         active_accounts=active_accounts,
                         inactive_accounts=inactive_accounts,
                         accounts_by_type=accounts_by_type,
                         type_totals=type_totals,
                         total_balance=total_balance)


@accounts_bp.route('/accounts/create', methods=['POST'])
def create():
    """Create a new account"""
    try:
        name = request.form.get('name')
        account_type = request.form.get('account_type')
        balance = float(request.form.get('balance', 0))
        is_active = request.form.get('is_active') == 'on'
        
        account = Account(
            name=name,
            account_type=account_type,
            balance=balance,
            is_active=is_active
        )
        
        db.session.add(account)
        db.session.commit()
        
        flash(f'Account "{name}" created successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating account: {str(e)}', 'danger')
    
    return redirect(url_for('accounts.index'))


@accounts_bp.route('/accounts/<int:id>/edit', methods=['POST'])
def edit(id):
    """Edit an account"""
    try:
        account = Account.query.get_or_404(id)
        
        account.name = request.form.get('name')
        account.account_type = request.form.get('account_type')
        account.balance = float(request.form.get('balance', 0))
        account.is_active = request.form.get('is_active') == 'on'
        
        db.session.commit()
        
        flash(f'Account "{account.name}" updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating account: {str(e)}', 'danger')
    
    return redirect(url_for('accounts.index'))


@accounts_bp.route('/accounts/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete an account"""
    try:
        account = Account.query.get_or_404(id)
        name = account.name
        
        db.session.delete(account)
        db.session.commit()
        
        flash(f'Account "{name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting account: {str(e)}', 'danger')
    
    return redirect(url_for('accounts.index'))
