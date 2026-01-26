from flask import Blueprint

loans_bp = Blueprint('loans', __name__, template_folder='templates')

from . import routes
