from flask import Blueprint
from flask_login import login_required

dashboard_bp = Blueprint('dashboard', __name__, template_folder='templates')

# Require authentication for all routes in this blueprint
@dashboard_bp.before_request
@login_required
def require_login():
    pass

from . import routes
