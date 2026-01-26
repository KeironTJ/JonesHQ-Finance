"""
Vendors blueprint for managing vendors/merchants
"""
from flask import Blueprint

bp = Blueprint('vendors', __name__, url_prefix='/vendors')

from blueprints.vendors import routes
