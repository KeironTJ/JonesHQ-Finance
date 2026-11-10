from flask import Blueprint
from flask_login import login_required

accounts_bp = Blueprint('accounts', __name__, template_folder='templates')

# Require authentication for all routes in this blueprint
@accounts_bp.before_request
@login_required
def require_login():
    pass

from . import routes
