from flask import Blueprint

credit_cards_bp = Blueprint('credit_cards', __name__, template_folder='templates')

from . import routes
