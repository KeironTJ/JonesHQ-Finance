"""
Categories blueprint for managing budget categories
"""
from flask import Blueprint

bp = Blueprint('categories', __name__, url_prefix='/categories')

from blueprints.categories import routes
