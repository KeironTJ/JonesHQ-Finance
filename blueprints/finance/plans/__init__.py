from flask import Blueprint
from flask_login import login_required


plans_bp = Blueprint('plans', __name__)


@plans_bp.before_request
@login_required
def require_login():
    pass


from . import routes
