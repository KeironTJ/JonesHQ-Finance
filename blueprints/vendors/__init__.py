"""
Vendors blueprint for managing vendors/merchants
"""
from flask import Blueprint
from flask_login import login_required

bp = Blueprint('vendors', __name__, url_prefix='/vendors')

# Require authentication for all routes in this blueprint
@bp.before_request
@login_required
def require_login():
    pass

from blueprints.vendors import routes
