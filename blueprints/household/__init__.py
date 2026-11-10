from flask import Blueprint


household_bp = Blueprint('household', __name__, url_prefix='/household')


def register_blueprints(app):
    from . import routes, meal_routes, activity_routes, task_routes, reward_routes
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
    'page_parents': {
        f'household.{endpoint}': ('household.meal_planner', 'Meal planner')
        for endpoint in ('meals', 'meal', 'create_meal', 'edit_meal', 'archive_meal')
    },
    'page_labels': {
        'household.my_day': 'My day',
        'household': 'Calendar',
        **{f'household.{endpoint}': 'Events' for endpoint in (
            'events', 'event', 'create_event', 'edit_event', 'delete_event',
        )},
        **{f'household.{endpoint}': 'Meal library' for endpoint in (
            'meals', 'meal', 'create_meal', 'edit_meal', 'archive_meal',
        )},
        **{f'household.{endpoint}': 'Meal planner' for endpoint in (
            'meal_planner', 'add_planned_meal', 'planned_meal', 'remove_planned_meal',
        )},
        **{f'household.{endpoint}': 'Activity planner' for endpoint in (
            'activity_planner', 'activity', 'create_activity', 'review_activity', 'delete_activity',
        )},
        **{f'household.{endpoint}': 'Tasks & lists' for endpoint in (
            'tasks', 'create_task_list', 'edit_task_list', 'delete_task_list',
            'create_task', 'task', 'complete_task', 'delete_task',
        )},
        'household.rewards': 'Rewards',
        'household.reward_action': 'Rewards',
    },
    'status': 'available',
    'requires_household': True,
    'default_destination': True,
    'register_blueprints': register_blueprints,
    'settings_group': settings_group,
}
