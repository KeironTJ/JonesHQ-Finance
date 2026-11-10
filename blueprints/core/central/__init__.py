from flask import Blueprint

central_bp = Blueprint('central', __name__)

from . import routes
