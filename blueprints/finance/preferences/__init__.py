from flask import Blueprint
from flask_login import login_required

finance_preferences_bp = Blueprint('finance_preferences', __name__)


@finance_preferences_bp.before_request
@login_required
def require_login():
    pass


from . import routes
