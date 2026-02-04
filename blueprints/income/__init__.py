from flask import Blueprint
from flask_login import login_required

income_bp = Blueprint('income', __name__)

# Require authentication for all routes in this blueprint
@income_bp.before_request
@login_required
def require_login():
    pass

from . import routes
