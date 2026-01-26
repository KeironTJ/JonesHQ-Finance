from flask import Blueprint

pensions_bp = Blueprint('pensions', __name__, template_folder='templates')

from . import routes
