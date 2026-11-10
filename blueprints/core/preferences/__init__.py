from flask import Blueprint
from flask_login import login_required

preferences_bp = Blueprint('preferences', __name__, url_prefix='/preferences')


@preferences_bp.before_request
@login_required
def require_login():
    pass


from . import routes
