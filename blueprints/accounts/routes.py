from flask import render_template, request, redirect, url_for
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
    # Implementation here
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
