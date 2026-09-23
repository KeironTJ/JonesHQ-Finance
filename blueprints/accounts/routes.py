from flask import render_template, request, redirect, url_for, flash
from . import accounts_bp
from services.finance.account_service import AccountService
from extensions import db


@accounts_bp.route('/accounts')
def index():
    """List all accounts"""
    return render_template('accounts/index.html', **AccountService.get_overview())


@accounts_bp.route('/accounts/create', methods=['POST'])
def create():
    """Create a new account"""
    try:
        name = request.form.get('name')
        account_type = request.form.get('account_type')
        balance = float(request.form.get('balance', 0))
        is_active = request.form.get('is_active') == 'on'
        is_private = request.form.get('visibility') == 'private'

        AccountService.create_account(name, account_type, balance, is_active, is_private)
        flash(f'Account "{name}" created successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error creating account: {str(e)}', 'danger')
    
    return redirect(url_for('accounts.index'))


@accounts_bp.route('/accounts/<int:id>/edit', methods=['POST'])
def edit(id):
    """Edit an account"""
    try:
        account = AccountService.update_account(
            id,
            request.form.get('name'),
            request.form.get('account_type'),
            float(request.form.get('balance', 0)),
            request.form.get('is_active') == 'on',
            request.form.get('visibility') == 'private',
        )
        flash(f'Account "{account.name}" updated successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error updating account: {str(e)}', 'danger')
    
    return redirect(url_for('accounts.index'))


@accounts_bp.route('/accounts/<int:id>/delete', methods=['POST'])
def delete(id):
    """Delete an account"""
    try:
        name = AccountService.delete_account(id)
        flash(f'Account "{name}" deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting account: {str(e)}', 'danger')
    
    return redirect(url_for('accounts.index'))
