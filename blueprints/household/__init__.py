from flask import Blueprint


household_bp = Blueprint('household', __name__, url_prefix='/household')


def register_blueprints(app):
    from . import routes
    app.register_blueprint(household_bp)


def settings_group(user):
    return {
        'label': 'Household Hub', 'endpoint': 'household.settings',
        'pages': [{
            'label': 'Calendar & privacy', 'endpoint': 'household.settings',
            'values': {}, 'scope': 'household',
            'description': 'London calendar time and shared/private event permissions.',
        }],
    }


MODULE = {
    'key': 'household',
    'title': 'Household Hub',
    'description': 'Organise household life with shared meals, activities and tasks.',
    'icon': 'bi-house-heart',
    'home_endpoint': 'household.calendar',
    'overview_label': 'Calendar',
    'navigation_template': 'household/_navigation.html',
    'page_labels': {'household': 'Calendar'},
    'status': 'available',
    'requires_household': True,
    'default_destination': True,
    'register_blueprints': register_blueprints,
    'settings_group': settings_group,
}
