from flask import Blueprint

central_bp = Blueprint('central', __name__, url_prefix='/central')

from . import routes
