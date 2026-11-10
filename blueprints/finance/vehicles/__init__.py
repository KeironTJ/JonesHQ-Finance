from flask import Blueprint
from flask_login import login_required

vehicles_bp = Blueprint('vehicles', __name__, template_folder='templates')

# Require authentication for all routes in this blueprint
@vehicles_bp.before_request
@login_required
def require_login():
    pass

from . import routes
