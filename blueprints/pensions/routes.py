from flask import render_template, request, redirect, url_for
from . import pensions_bp
from models.pensions import Pension
from extensions import db


@pensions_bp.route('/pensions')
def index():
    """List all pensions"""
    pensions = Pension.query.all()
    return render_template('pensions/index.html', pensions=pensions)


@pensions_bp.route('/pensions/create', methods=['POST'])
def create():
    """Create a new pension"""
    # Implementation here
    return redirect(url_for('pensions.index'))
