from flask import Blueprint
from flask_login import login_required

networth_bp = Blueprint('networth', __name__, template_folder='templates')

# Require authentication for all routes in this blueprint
@networth_bp.before_request
@login_required
def require_login():
    pass

from . import routes
