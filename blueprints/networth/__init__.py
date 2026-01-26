from flask import Blueprint

networth_bp = Blueprint('networth', __name__, template_folder='templates')

from . import routes
