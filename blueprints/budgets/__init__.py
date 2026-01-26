from flask import Blueprint

budgets_bp = Blueprint('budgets', __name__, template_folder='templates')

from . import routes
