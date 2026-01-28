from flask import render_template, request, redirect, url_for
from . import budgets_bp
from models.budgets import Budget
from extensions import db


@budgets_bp.route('/budgets')
def index():
    """List all budgets"""
    budgets = Budget.query.all()
    return render_template('budgets/index.html', budgets=budgets)


@budgets_bp.route('/budgets/create', methods=['POST'])
def create():
    """Create a new budget"""
    # Implementation here
    return redirect(url_for('budgets.index'))
