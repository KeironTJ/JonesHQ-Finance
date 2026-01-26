from flask import Blueprint

mortgage_bp = Blueprint('mortgage', __name__, template_folder='templates')

from . import routes
