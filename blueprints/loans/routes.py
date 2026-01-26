from flask import render_template, request, redirect, url_for
from . import loans_bp
from models.loans import Loan
from extensions import db


@loans_bp.route('/loans')
def index():
    """List all loans"""
    loans = Loan.query.all()
    return render_template('loans.html', loans=loans)


@loans_bp.route('/loans/create', methods=['POST'])
def create():
    """Create a new loan"""
    # Implementation here
    return redirect(url_for('loans.index'))
