from flask import render_template, request, redirect, url_for
from . import networth_bp
from models.networth import NetWorth
from extensions import db


@networth_bp.route('/networth')
def index():
    """View net worth history"""
    records = NetWorth.query.order_by(NetWorth.date.desc()).all()
    return render_template('networth/index.html', records=records)


@networth_bp.route('/networth/snapshot', methods=['POST'])
def create_snapshot():
    """Create a new net worth snapshot"""
    # Implementation here
    return redirect(url_for('networth.index'))
