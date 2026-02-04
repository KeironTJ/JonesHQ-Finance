from flask import Blueprint
from flask_login import login_required

credit_cards_bp = Blueprint('credit_cards', __name__, template_folder='templates')

# Require authentication for all routes in this blueprint
@credit_cards_bp.before_request
@login_required
def require_login():
    pass

from . import routes
