"""Family blueprint – multi-user family management."""
from flask import Blueprint

family_bp = Blueprint('family', __name__, url_prefix='/family',
                      template_folder='../../templates/family')

# Note: no global @before_request login_required here because the
# /family/join/<token> route is public (access for new registrants).
# Per-route @login_required is applied in routes.py instead.

from . import routes  # noqa: E402,F401
