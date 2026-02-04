from flask import Blueprint
from flask_login import login_required

expenses_bp = Blueprint('expenses', __name__)

# Require authentication for all routes in this blueprint
@expenses_bp.before_request
@login_required
def require_login():
    pass

from . import routes
