import importlib.util
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import g
from flask_login import login_user
from sqlalchemy.exc import OperationalError

from extensions import db
from models import CalendarEvent, Family, HouseholdMembership, Meal, PlannedMeal, User
from services.household.calendar_service import CalendarService
from services.household.meal_service import MealService
from tests.auth_helpers import login_client
from utils.tenancy_guard import CrossFamilyReferenceError


RECIPE = {'name': 'Pasta', 'ingredients': 'Pasta\nTomatoes', 'instructions': 'Cook and serve.'}
PLAN_DATE = '2026-11-10'


def client_for(app, actor):
    client = app.test_client()
    login_client(client, actor.id)
    return client


def create_meal(app, actor, **changes):
    with app.test_request_context():
        login_user(actor)
        return MealService.create_meal({**RECIPE, **changes})


def create_plan(app, actor, meal, **changes):
    with app.test_request_context():
        login_user(actor)
        return MealService.create_plan({
            'meal_id': str(meal.id), 'date': PLAN_DATE, 'slot': 'dinner', **changes,
        })


@pytest.fixture
def people(user, family):
    adult = User(
        family_id=family.id, role='member', name='Adult',
        email='adult@example.com', password_hash=user.password_hash, allowed_sections='[]',
    )
    child = User(
        family_id=family.id, role='member', name='Child',
        email='child@example.com', password_hash=user.password_hash, account_type='child',
        guardian_id=user.id, allowed_sections='[]',
    )
    db.session.add_all([adult, child])
    db.session.commit()
    for member in (adult, child):
        member.get_active_household_membership().allowed_modules = ['household']
    db.session.commit()
    return adult, child


def test_adult_member_can_manage_library_without_finance_or_owner_role(app, people):
    adult, _ = people
    client = client_for(app, adult)
    response = client.post('/household/meals/new', data={**RECIPE, 'family_id': '999'})
    assert response.status_code == 302
    meal = Meal.query.one()
    assert meal.family_id == adult.family_id
    assert meal.ingredients == RECIPE['ingredients']
    assert client.get('/finance/dashboard').status_code == 403
    assert client.get(response.location).status_code == 200
    response = client.post(f'/household/meals/{meal.id}/edit', data={**RECIPE, 'name': 'Updated pasta'})
    assert response.status_code == 302
    assert meal.name == 'Updated pasta'
    assert client.post(f'/household/meals/{meal.id}/archive', data={'action': 'archive'}).status_code == 302
    assert meal.is_archived
    assert b'Updated pasta' not in client.get('/household/meals').data
    assert b'Updated pasta' in client.get('/household/meals?status=archived').data
    client.post(f'/household/meals/{meal.id}/archive', data={'action': 'restore'})
    assert not meal.is_archived


def test_multiple_meals_same_slot_weekly_views_and_source_calendar(app, user):
    first = create_meal(app, user)
    second = create_meal(app, user, name='Salad')
    plans = [create_plan(app, user, first), create_plan(app, user, second)]
    create_plan(app, user, first, slot='breakfast')
    create_plan(app, user, second, slot='lunch')
    client = client_for(app, user)
    html = client.get('/household/meal-planner?week=2026-11-10').data
    assert b'09 Nov 2026' in html and b'15 Nov 2026' in html
    assert b'Pasta' in html and b'Salad' in html
    assert b'<span class="workspace-location">Meal planner</span>' in html
    assert b'<span class="workspace-location">Meal library</span>' in client.get('/household/meals').data
    for plan in plans:
        assert f'/household/meal-planner/{plan.id}'.encode() in html
    for view in ('month', 'agenda'):
        html = client.get(f'/household/?month=2026-11&view={view}').data
        assert b'Dinner: Pasta' in html and b'Dinner: Salad' in html
        assert b'Breakfast: Pasta' in html and b'Lunch: Salad' in html
        assert f'/household/meal-planner/{plans[0].id}'.encode() in html
        assert b'A little space in the calendar' not in html
    with app.test_request_context():
        login_user(user)
        context = CalendarService.page_data({'month': '2026-11'})
        assert len(context['meal_days'][date(2026, 11, 10)]) == 4
        assert len(MealService.planner({'week': PLAN_DATE})['plans_by_slot'][(date(2026, 11, 10), 'dinner')]) == 2
    assert CalendarEvent.query.count() == 0


def test_plan_move_recipe_change_and_removal_immediately_update_feed(app, user):
    meal = create_meal(app, user)
    plan = create_plan(app, user, meal, notes='For everyone')
    client = client_for(app, user)
    assert b'For everyone' in client.get(f'/household/meal-planner/{plan.id}').data
    client.post(f'/household/meals/{meal.id}/edit', data={**RECIPE, 'name': 'New recipe name'})
    assert plan.title == 'Pasta'
    assert b'Dinner: Pasta' in client.get('/household/?month=2026-11&view=agenda').data
    response = client.post(f'/household/meal-planner/{plan.id}', data={
        'meal_id': meal.id, 'title': 'This date only', 'date': '2026-12-01', 'slot': 'lunch', 'notes': 'Moved',
    })
    assert response.location.endswith('week=2026-12-01')
    assert plan.date == date(2026, 12, 1)
    # Month grids can include adjoining days; agenda excludes those adjoining dates.
    assert b'New recipe name' not in client.get('/household/?month=2026-11&view=agenda').data
    assert b'Lunch: This date only' in client.get('/household/?month=2026-12&view=agenda').data
    client.post(f'/household/meal-planner/{plan.id}/remove')
    assert PlannedMeal.query.count() == 0
    assert Meal.query.count() == 1
    assert b'Lunch: This date only' not in client.get('/household/?month=2026-12').data
    assert CalendarEvent.query.count() == 0


def test_archived_meals_preserve_existing_plans_and_cannot_be_newly_selected(app, user):
    meal = create_meal(app, user)
    plan = create_plan(app, user, meal)
    client = client_for(app, user)
    client.post(f'/household/meals/{meal.id}/archive', data={'action': 'archive'})
    assert b'Dinner: Pasta' in client.get('/household/?month=2026-11').data
    assert b'Archived meal' in client.get('/household/meal-planner?week=2026-11-10').data
    assert b'(archived)' in client.get(f'/household/meal-planner/{plan.id}').data
    response = client.post('/household/meal-planner/add', data={'date': PLAN_DATE, 'slot': 'dinner', 'meal_id': meal.id})
    assert PlannedMeal.query.count() == 1
    assert b'Restore this archived meal' in response.data
    # Keeping an already-planned archived meal is allowed.
    response = client.post(f'/household/meal-planner/{plan.id}', data={
        'meal_id': meal.id, 'date': PLAN_DATE, 'slot': 'breakfast',
    })
    assert response.status_code == 302 and plan.slot == 'breakfast'
    client.post(f'/household/meals/{meal.id}/archive', data={'action': 'restore'})
    client.post('/household/meal-planner/add', data={'date': PLAN_DATE, 'slot': 'dinner', 'meal_id': meal.id})
    assert PlannedMeal.query.count() == 2


def test_managed_child_views_all_meal_pages_but_no_write_or_edit_form(app, user, people):
    _, child = people
    meal = create_meal(app, user)
    plan = create_plan(app, user, meal)
    # A corrupt owner role must not change the child baseline.
    child.get_active_household_membership().role = 'admin'
    db.session.commit()
    client = client_for(app, child)
    for path in (
        '/household/meals', f'/household/meals/{meal.id}', '/household/meal-planner?week=2026-11-10',
        f'/household/meal-planner/{plan.id}', '/household/?month=2026-11&view=agenda',
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert b'>Save meal<' not in response.data
        assert b'>Add planned meal<' not in response.data
        assert b'>Remove from plan<' not in response.data
    for path in ('/household/meals/new', f'/household/meals/{meal.id}/edit'):
        assert client.get(path).status_code == 403
    for path, data in (
        ('/household/meals/new', RECIPE),
        (f'/household/meals/{meal.id}/edit', {**RECIPE, 'name': 'Spoof'}),
        (f'/household/meals/{meal.id}/archive', {'action': 'archive'}),
        ('/household/meal-planner/add', {'meal_id': meal.id, 'date': PLAN_DATE, 'slot': 'lunch'}),
        (f'/household/meal-planner/{plan.id}', {'meal_id': meal.id, 'date': PLAN_DATE, 'slot': 'lunch'}),
        (f'/household/meal-planner/{plan.id}/remove', {}),
    ):
        assert client.post(path, data=data).status_code == 403, path
    assert meal.name == RECIPE['name'] and not meal.is_archived
    assert PlannedMeal.query.count() == 1 and plan.slot == 'dinner'
    with app.test_request_context():
        login_user(child)
        from werkzeug.exceptions import Forbidden
        with pytest.raises(Forbidden):
            MealService.create_meal(RECIPE)
        with pytest.raises(Forbidden):
            MealService.remove_plan(plan.id)


def test_module_revocation_blocks_all_meal_surfaces_immediately(app, user):
    meal = create_meal(app, user)
    plan = create_plan(app, user, meal)
    client = client_for(app, user)
    user.get_active_household_membership().allowed_modules = ['finance']
    db.session.commit()
    for path in (
        '/household/meals', '/household/meals/new', f'/household/meals/{meal.id}',
        f'/household/meals/{meal.id}/edit', '/household/meal-planner', f'/household/meal-planner/{plan.id}',
    ):
        assert client.get(path).status_code == 403
    assert client.post('/household/meal-planner/add', data={}).status_code == 403
    assert b'Meal library' not in client.get('/central/').data


def test_scoping_foreign_ids_and_active_household_not_legacy_default(app, user, family):
    foreign = Family(name='Other')
    db.session.add(foreign)
    db.session.flush()
    db.session.add(HouseholdMembership(
        user_id=user.id, family_id=foreign.id, role='member', allowed_modules=['household'],
    ))
    db.session.commit()
    original = create_meal(app, user)
    original_plan = create_plan(app, user, original)
    client = client_for(app, user)
    client.post('/central/family/select', data={'family_id': foreign.id})
    for path in (
        f'/household/meals/{original.id}', f'/household/meals/{original.id}/edit',
        f'/household/meal-planner/{original_plan.id}',
    ):
        assert client.get(path).status_code == 404
    assert client.post(f'/household/meals/{original.id}/archive', data={'action': 'archive'}).status_code == 404
    assert client.post(f'/household/meal-planner/{original_plan.id}/remove').status_code == 404
    response = client.post('/household/meals/new', data={**RECIPE, 'name': 'Second household', 'family_id': family.id})
    second = Meal.query.filter_by(family_id=foreign.id).one()
    assert response.location.endswith(f'/meals/{second.id}')
    response = client.post('/household/meal-planner/add', data={
        'meal_id': original.id, 'date': PLAN_DATE, 'slot': 'dinner',
    })
    assert PlannedMeal.query.count() == 1
    assert b'Choose a meal from your household library' in response.data
    response = client.post('/household/meal-planner/add', data={
        'meal_id': second.id, 'date': PLAN_DATE, 'slot': 'dinner', 'family_id': family.id,
    })
    assert response.status_code == 302
    assert PlannedMeal.query.filter_by(family_id=foreign.id).count() == 1
    html = client.get('/household/?month=2026-11&view=agenda').data
    assert b'Dinner: Second household' in html and b'Dinner: Pasta' not in html
    with pytest.raises(CrossFamilyReferenceError):
        db.session.add(PlannedMeal(family_id=foreign.id, meal_id=original.id, date=date(2026, 11, 10), slot='dinner'))
        db.session.flush()
    db.session.rollback()


@pytest.mark.parametrize('changes,message', [
    ({'name': ''}, 'meal name'),
    ({'name': 'x' * 201}, 'meal name'),
    ({'ingredients': 'x' * 10001}, '10,000'),
    ({'instructions': 'x' * 10001}, '10,000'),
])
def test_invalid_meal_does_not_write(app, user, changes, message):
    with pytest.raises(ValueError, match=message):
        create_meal(app, user, **changes)
    assert Meal.query.count() == 0


@pytest.mark.parametrize('changes,message', [
    ({'date': 'bad'}, 'valid meal date'),
    ({'date': '1800-01-01'}, 'between 1900'),
    ({'date': '2101-01-01'}, 'between 1900'),
    ({'slot': 'snack'}, 'breakfast, lunch or dinner'),
    ({'meal_id': 'bad'}, 'household library'),
    ({'meal_id': '99999'}, 'household library'),
    ({'notes': 'x' * 2001}, '2,000'),
])
def test_invalid_plan_does_not_write(app, user, changes, message):
    meal = create_meal(app, user)
    with pytest.raises(ValueError, match=message):
        create_plan(app, user, meal, **changes)
    assert PlannedMeal.query.count() == 0


@pytest.mark.parametrize('query', ['week=bad', 'week=1899-12-31', 'week=2101-01-01'])
def test_invalid_week_is_explicit_and_redirects_safely(app, user, query):
    response = client_for(app, user).get('/household/meal-planner?' + query, follow_redirects=True)
    assert response.status_code == 200 and b'alert-danger' in response.data


def test_week_crosses_year_and_supported_date_boundaries(app, user):
    meal = create_meal(app, user)
    plan = create_plan(app, user, meal, date='2027-01-01')
    with app.test_request_context():
        login_user(user)
        context = MealService.planner({'week': '2027-01-01'})
        assert context['first'] == date(2026, 12, 28)
        assert context['last'] == date(2027, 1, 3)
        assert context['plans_by_slot'][(date(2027, 1, 1), 'dinner')] == [plan]
        assert MealService.planner({'week': '1900-01-01'})['previous'] is None
        assert MealService.planner({'week': '2100-12-31'})['following'] is None


@pytest.mark.parametrize('operation', ['create', 'edit', 'archive', 'plan', 'move', 'remove'])
def test_write_failures_rollback_and_report_no_changes(app, user, monkeypatch, operation):
    meal = create_meal(app, user)
    plan = create_plan(app, user, meal)
    paths = {
        'create': ('/household/meals/new', {**RECIPE, 'name': 'New'}),
        'edit': (f'/household/meals/{meal.id}/edit', {**RECIPE, 'name': 'Changed'}),
        'archive': (f'/household/meals/{meal.id}/archive', {'action': 'archive'}),
        'plan': ('/household/meal-planner/add', {'meal_id': meal.id, 'date': PLAN_DATE, 'slot': 'lunch'}),
        'move': (f'/household/meal-planner/{plan.id}', {'meal_id': meal.id, 'date': '2026-11-11', 'slot': 'lunch'}),
        'remove': (f'/household/meal-planner/{plan.id}/remove', {}),
    }
    client = client_for(app, user)
    monkeypatch.setattr(db.session, 'commit', Mock(side_effect=OperationalError('write', {}, Exception('unavailable'))))
    path, data = paths[operation]
    response = client.post(path, data=data, follow_redirects=True)
    assert response.status_code == 200 and b'No changes were saved.' in response.data
    db.session.expire_all()
    assert Meal.query.count() == 1 and meal.name == RECIPE['name'] and not meal.is_archived
    assert PlannedMeal.query.count() == 1 and plan.date == date(2026, 11, 10) and plan.slot == 'dinner'


def test_csrf_required_for_every_meal_write(app, user, monkeypatch):
    meal = create_meal(app, user)
    plan = create_plan(app, user, meal)
    client = client_for(app, user)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    g.pop('csrf_token', None)
    for path in (
        '/household/meals/new', f'/household/meals/{meal.id}/edit', f'/household/meals/{meal.id}/archive',
        '/household/meal-planner/add', f'/household/meal-planner/{plan.id}', f'/household/meal-planner/{plan.id}/remove',
    ):
        assert client.post(path, data=RECIPE).status_code == 400
    assert Meal.query.count() == 1 and PlannedMeal.query.count() == 1


def test_shared_meals_survive_individual_account_deletion(app, user, people):
    adult, _ = people
    meal = create_meal(app, adult)
    plan = create_plan(app, adult, meal)
    response = client_for(app, adult).post('/central/account/security/delete', data={
        'password': 'TestPass1!', 'confirmation': 'DELETE MY ACCOUNT',
    })
    assert response.location.endswith('/login')
    assert Meal.query.count() == 1 and PlannedMeal.query.count() == 1
    assert client_for(app, user).get(f'/household/meal-planner/{plan.id}').status_code == 200
    db.session.expire_all()
    assert plan.creator_membership_id is None


def test_date_first_add_needs_no_library_and_records_actual_creator(app, user, people):
    adult, child = people
    client = client_for(app, adult)
    html = client.get('/household/meal-planner/add?date=2026-11-18&view=month').data
    assert b'value="2026-11-18"' in html
    assert b'No library meal' in html
    response = client.post('/household/meal-planner/add', data={
        'date': '2026-11-18', 'slot': 'dinner', 'title': 'Takeaway',
        'description': 'Pizza for everyone', 'source': 'Local menu, page 2',
        'creator_membership_id': user.get_active_household_membership().id,
        'family_id': '99999', 'view': 'month',
    })
    assert response.location.endswith('view=month&month=2026-11')
    plan = PlannedMeal.query.one()
    assert plan.meal_id is None and Meal.query.count() == 0
    assert plan.title == 'Takeaway' and plan.description == 'Pizza for everyone'
    assert plan.source == 'Local menu, page 2'
    assert plan.creator_membership_id == adult.get_active_household_membership().id
    assert plan.family_id == adult.family_id
    assert b'Added by Adult' in client.get(f'/household/meal-planner/{plan.id}').data
    for path in (
        '/household/meal-planner?week=2026-11-18',
        '/household/meal-planner?view=month&month=2026-11',
        '/household/?month=2026-11', '/household/?month=2026-11&view=agenda',
    ):
        assert b'Takeaway' in client.get(path).data
    child_client = client_for(app, child)
    detail = child_client.get(f'/household/meal-planner/{plan.id}').data
    assert b'Pizza for everyone' in detail and b'Local menu, page 2' in detail
    assert b'Added by Adult' in detail
    assert child_client.get('/household/meal-planner/add').status_code == 403
    assert b'data-bs-target="#addMealModal"' not in child_client.get(
        '/household/meal-planner?view=month&month=2026-11',
    ).data
    assert CalendarEvent.query.count() == 0


def test_library_is_optional_snapshot_and_planned_meals_edit_independently(app, user):
    meal = create_meal(app, user, source='Recipe book p.12')
    first = create_plan(app, user, meal)
    second = create_plan(app, user, meal, date='2026-11-11')
    assert first.title == meal.name
    assert first.description == meal.instructions
    assert first.source == meal.source
    client = client_for(app, user)
    client.post(f'/household/meals/{meal.id}/edit', data={
        **RECIPE, 'name': 'Different library title', 'instructions': 'New instructions', 'source': 'New source',
    })
    assert first.title == 'Pasta' and second.title == 'Pasta'
    assert first.description == RECIPE['instructions'] and second.source == 'Recipe book p.12'
    response = client.post(f'/household/meal-planner/{first.id}', data={
        'title': 'Pasta for two', 'description': 'Half quantities', 'source': 'Handwritten note',
        'date': PLAN_DATE, 'slot': 'lunch', 'view': 'month',
    })
    assert response.location.endswith('view=month&month=2026-11')
    assert first.title == 'Pasta for two' and second.title == 'Pasta'
    assert first.source == 'Handwritten note' and second.source == 'Recipe book p.12'
    assert meal.name == 'Different library title' and meal.source == 'New source'
    # Explicitly detaching the optional library keeps this date's details.
    client.post(f'/household/meal-planner/{first.id}', data={
        'meal_id': '', 'date': PLAN_DATE, 'slot': 'dinner',
    })
    assert first.meal_id is None and first.title == 'Pasta for two'
    assert first.description == 'Half quantities'
    response = client.post(f'/household/meal-planner/{first.id}/remove', data={'view': 'month'})
    assert response.location.endswith('view=month&month=2026-11')
    assert PlannedMeal.query.count() == 1 and Meal.query.count() == 1


@pytest.mark.parametrize('data,message', [
    ({'title': ''}, 'meal title'),
    ({'title': 'x' * 201}, 'meal title'),
    ({'title': 'Dinner', 'description': 'x' * 10001}, 'description'),
    ({'title': 'Dinner', 'source': 'x' * 501}, 'recipe source'),
    ({'title': 'Dinner', 'date': 'bad'}, 'valid meal date'),
    ({'title': 'Dinner', 'view': 'other'}, 'week or month'),
])
def test_quick_add_validation_preserves_input_without_creating_rows(app, user, data, message):
    client = client_for(app, user)
    response = client.post('/household/meal-planner/add', data={
        'date': PLAN_DATE, 'slot': 'dinner', 'source': 'My book', **data,
    })
    assert response.status_code == 200 and message.encode() in response.data
    assert b'value="2026-11-10"' in response.data or data.get('date') == 'bad'
    assert Meal.query.count() == 0 and PlannedMeal.query.count() == 0


@pytest.mark.parametrize('query', ['view=wrong', 'view=month&month=bad', 'view=month&month=2101-01'])
def test_invalid_month_or_view_is_reported(app, user, query):
    response = client_for(app, user).get('/household/meal-planner?' + query, follow_redirects=True)
    assert response.status_code == 200 and b'alert-danger' in response.data


def test_month_view_day_add_links_and_navigation_stay_in_view(app, user):
    meal = create_meal(app, user)
    create_plan(app, user, meal)
    client = client_for(app, user)
    html = client.get('/household/meal-planner?view=month&month=2026-11').data
    assert b'November 2026' in html and b'Dinner: Pasta' in html
    assert b'data-meal-date="2026-11-10"' in html
    assert b'data-bs-target="#addMealModal"' in html
    assert b'view=month&amp;month=2026-10' in html
    assert b'view=month&amp;month=2026-12' in html
    assert b'>Week</a>' in html and b'>Month</a>' in html
    with app.test_request_context():
        login_user(user)
        context = MealService.planner({'view': 'month', 'month': '2026-11'})
        assert len(context['days']) == 42
        assert context['first'] == date(2026, 10, 26) and context['last'] == date(2026, 12, 6)
        assert MealService.planner({'view': 'month', 'month': '1900-01'})['previous'] is None
        assert MealService.planner({'view': 'month', 'month': '2100-12'})['following'] is None


def test_departing_creator_attribution_detaches_but_plan_remains(app, user, family, people):
    from services.household.family_service import FamilyService
    adult, _ = people
    meal = create_meal(app, adult)
    plan = create_plan(app, adult, meal)
    plan_id = plan.id
    with app.test_request_context():
        login_user(user)
        FamilyService.remove_member(adult.id, family.id, user.id)
    db.session.expire_all()
    assert db.session.get(PlannedMeal, plan_id).creator_membership_id is None
    assert b'former member' in client_for(app, user).get(f'/household/meal-planner/{plan_id}').data


def test_independent_plan_migration_backfills_and_preserves_data(app):
    directory = Path(app.root_path) / 'migrations' / 'versions'
    migrations = []
    for index, name in enumerate((
        'e83f9b5d012c_add_household_meal_planning.py', 'f94a0c6e123d_make_planned_meals_date_first.py',
    )):
        spec = importlib.util.spec_from_file_location(f'meals_schema_{index}', directory / name)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migrations.append(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('PRAGMA foreign_keys=ON'))
        connection.execute(sa.text('CREATE TABLE families (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text(
            'CREATE TABLE household_memberships (id INTEGER PRIMARY KEY, family_id INTEGER REFERENCES families(id))',
        ))
        connection.execute(sa.text('INSERT INTO families VALUES (1)'))
        connection.execute(sa.text('INSERT INTO household_memberships VALUES (1, 1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migrations[0].upgrade()
            connection.execute(sa.text(
                "INSERT INTO meals (id, family_id, name, instructions) VALUES (1, 1, 'Pasta', 'Original recipe')",
            ))
            connection.execute(sa.text(
                "INSERT INTO planned_meals (id, family_id, meal_id, date, notes) "
                "VALUES (1, 1, 1, '2026-11-10', 'Keep notes')",
            ))
            migrations[1].upgrade()
            plan = connection.execute(sa.text('SELECT * FROM planned_meals')).mappings().one()
            assert plan['title'] == 'Pasta' and plan['description'] == 'Original recipe'
            assert plan['notes'] == 'Keep notes' and plan['creator_membership_id'] is None
            assert sa.inspect(connection).get_columns('planned_meals')[2]['nullable']
            connection.execute(sa.text(
                "INSERT INTO planned_meals (id, family_id, title, description, source, date, creator_membership_id) "
                "VALUES (2, 1, 'Takeaway', 'Pizza', 'Local menu', '2026-11-11', 1)",
            ))
            connection.execute(sa.text('DELETE FROM household_memberships WHERE id=1'))
            assert connection.execute(sa.text('SELECT creator_membership_id FROM planned_meals WHERE id=2')).scalar_one() is None
            migrations[1].downgrade()
            assert connection.execute(sa.text('SELECT COUNT(*) FROM planned_meals')).scalar_one() == 2
            assert connection.execute(sa.text(
                'SELECT meals.name FROM planned_meals JOIN meals ON meals.id=planned_meals.meal_id WHERE planned_meals.id=2',
            )).scalar_one() == 'Takeaway'
            migrations[1].upgrade()
            assert connection.execute(sa.text('SELECT title FROM planned_meals WHERE id=2')).scalar_one() == 'Takeaway'
            assert connection.execute(sa.text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()


def test_meal_migration_round_trip_preserves_household(app):
    path = Path(app.root_path) / 'migrations' / 'versions' / 'e83f9b5d012c_add_household_meal_planning.py'
    spec = importlib.util.spec_from_file_location('meal_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('PRAGMA foreign_keys=ON'))
        connection.execute(sa.text('CREATE TABLE families (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('INSERT INTO families VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            connection.execute(sa.text("INSERT INTO meals (id, family_id, name) VALUES (1, 1, 'Pasta')"))
            for _ in range(2):
                connection.execute(sa.text(
                    "INSERT INTO planned_meals (family_id, meal_id, date) VALUES (1, 1, '2026-11-10')"
                ))
            assert connection.execute(sa.text('SELECT COUNT(*) FROM planned_meals')).scalar_one() == 2
            assert connection.execute(sa.text('SELECT is_archived FROM meals')).scalar_one() == 0
            assert {row['name'] for row in sa.inspect(connection).get_check_constraints('planned_meals')} == {'ck_planned_meal_slot'}
            assert connection.execute(sa.text('PRAGMA foreign_key_check')).all() == []
            migration.downgrade()
            assert not {'meals', 'planned_meals'} & set(sa.inspect(connection).get_table_names())
            migration.upgrade()
            assert connection.execute(sa.text('SELECT id FROM families')).scalar_one() == 1
    engine.dispose()
