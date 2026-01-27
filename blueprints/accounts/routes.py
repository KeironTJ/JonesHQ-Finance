from flask import render_template, request, redirect, url_for, flash
from . import accounts_bp
from models.accounts import Account
from extensions import db


@accounts_bp.route('/accounts')
def index():
    """List all accounts"""
    accounts = Account.query.all()
    return render_template('accounts.html', accounts=accounts)


@accounts_bp.route('/accounts/create', methods=['POST'])
def create():
    """Create a new account"""
    try:
        name = request.form.get('name')
        account_type = request.form.get('account_type')
        balance = float(request.form.get('balance', 0))
        
        account = Account(
            name=name,
            account_type=account_type,
            balance=balance
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
    # Implementation here
    return redirect(url_for('accounts.index'))


@accounts_bp.route('/accounts/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete an account"""
    # Implementation here
    return redirect(url_for('accounts.index'))
