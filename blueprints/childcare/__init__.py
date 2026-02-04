from flask import Blueprint
from flask_login import login_required

childcare_bp = Blueprint('childcare', __name__, template_folder='templates')

# Require authentication for all routes in this blueprint
@childcare_bp.before_request
@login_required
def require_login():
    pass

from . import routes
