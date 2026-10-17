from flask import Blueprint

site_admin_bp = Blueprint('site_admin', __name__, url_prefix='/site-admin')

from . import routes  # noqa: E402,F401
