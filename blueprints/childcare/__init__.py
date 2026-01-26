from flask import Blueprint

childcare_bp = Blueprint('childcare', __name__, template_folder='templates')

from . import routes
