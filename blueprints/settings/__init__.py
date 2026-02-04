from flask import Blueprint
from flask_login import login_required

settings_bp = Blueprint('settings', __name__)

# Require authentication for all routes in this blueprint
@settings_bp.before_request
@login_required
def require_login():
    pass

from . import routes
