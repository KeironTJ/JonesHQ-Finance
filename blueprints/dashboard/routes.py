from flask import render_template
from . import dashboard_bp


@dashboard_bp.route('/')
@dashboard_bp.route('/dashboard')
def index():
    """Main dashboard view"""
    return render_template('dashboard/index.html')
