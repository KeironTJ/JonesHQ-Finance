from flask import Blueprint

vehicles_bp = Blueprint('vehicles', __name__, template_folder='templates')

from . import routes
