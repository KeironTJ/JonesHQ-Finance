from flask import render_template, request, redirect, url_for
from . import mortgage_bp
from models.mortgage import Mortgage
from extensions import db


@mortgage_bp.route('/mortgage')
def index():
    """List all mortgages"""
    mortgages = Mortgage.query.all()
    return render_template('mortgage/index.html', mortgages=mortgages)


@mortgage_bp.route('/mortgage/create', methods=['POST'])
def create():
    """Create a new mortgage"""
    # Implementation here
    return redirect(url_for('mortgage.index'))
