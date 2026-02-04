"""
Categories blueprint for managing budget categories
"""
from flask import Blueprint
from flask_login import login_required

bp = Blueprint('categories', __name__, url_prefix='/categories')

# Require authentication for all routes in this blueprint
@bp.before_request
@login_required
def require_login():
    pass

from blueprints.categories import routes
