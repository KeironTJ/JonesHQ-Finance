import importlib.util
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import g
from flask_login import login_user
from sqlalchemy.exc import OperationalError

from extensions import db, limiter
from models import CalendarEvent, Family, HouseholdMembership, HouseholdTask, TaskList, User
from services.household.calendar_service import CalendarService, LONDON
from services.household.task_service import TaskService
from tests.auth_helpers import login_client
from utils.db_helpers import family_query
from utils.tenancy_guard import CrossFamilyReferenceError


@pytest.fixture(autouse=True)
def isolate_login_state(app):
    g.pop('_login_user', None)
    limiter.reset()
    yield
    g.pop('_login_user', None)
    limiter.reset()


def client_for(app, actor):
    client = app.test_client()
    login_client(client, actor.id)
    return client


def create_list(app, actor, **changes):
    with app.test_request_context():
        login_user(actor)
        return TaskService.create_list({'title': 'House jobs', 'visibility': 'shared', **changes})


def create_task(app, actor, task_list, **changes):
    with app.test_request_context():
        login_user(actor)
        return TaskService.create_task({
            'list_id': str(task_list.id), 'title': 'Wash dishes', 'notes': 'After dinner', **changes,
        })


@pytest.fixture
def people(user, family):
    rows = []
    for name, account_type in [('Adult', 'adult'), ('Child', 'child'), ('Sibling', 'child')]:
        row = User(
            family_id=family.id, role='member', name=name, email=f'{name.lower()}@example.com',
            password_hash=user.password_hash, account_type=account_type,
            guardian_id=user.id if account_type == 'child' else None, allowed_sections='[]',
        )
        db.session.add(row)
        db.session.flush()
        rows.append(row)
    db.session.commit()
    for row in rows:
        row.get_active_household_membership().allowed_modules = ['household']
    db.session.commit()
    return rows


def test_empty_hub_does_not_create_records_on_get_and_adult_can_manage_without_finance(app, user, people):
    adult, _, _ = people
    client = client_for(app, adult)
    response = client.get('/household/tasks')
    assert response.status_code == 200 and b'A fresh checklist' in response.data
    assert TaskList.query.count() == 0
    response = client.post('/household/tasks/lists/new', data={
        'title': 'House jobs', 'visibility': 'shared', 'family_id': '99999',
        'creator_membership_id': user.get_active_household_membership().id,
    })
    task_list = TaskList.query.one()
    assert response.location.endswith(f'list_id={task_list.id}')
    assert task_list.family_id == adult.family_id
    assert task_list.creator_membership_id == adult.get_active_household_membership().id
    assert client.get('/dashboard').status_code == 403
    assert client.post(f'/household/tasks/lists/{task_list.id}/edit', data={
        'title': 'Weekly jobs', 'icon': 'house', 'colour': 'success',
    }).status_code == 302
    assert task_list.title == 'Weekly jobs' and task_list.icon == 'house'
    assert b'Tasks &amp; lists' in client.get('/household/tasks').data
    assert client.post(f'/household/tasks/lists/{task_list.id}/delete').status_code == 302
    assert TaskList.query.count() == 0


def test_child_shared_assignment_only_completion_and_spoofing_cannot_change_details(app, user, people):
    adult, child, sibling = people
    task_list = create_list(app, user)
    own_task = create_task(app, adult, task_list, assigned_membership_id=child.get_active_household_membership().id)
    sibling_task = create_task(app, user, task_list, title='Other job', assigned_membership_id=sibling.get_active_household_membership().id)
    unassigned = create_task(app, user, task_list, title='Unassigned')
    client = client_for(app, child)
    assert client.get(f'/household/tasks?list_id={task_list.id}').status_code == 200
    assert b'After dinner' in client.get(f'/household/tasks/{own_task.id}').data
    assert b'id="task_title"' not in client.get(f'/household/tasks/{own_task.id}').data
    response = client.post(f'/household/tasks/{own_task.id}/completion', data={
        'action': 'complete', 'title': 'Spoof', 'completed_by_membership_id': user.get_active_household_membership().id,
    })
    assert response.status_code == 302 and own_task.completed and own_task.title == 'Wash dishes'
    assert own_task.completed_by_membership_id == child.get_active_household_membership().id
    assert own_task.creator_membership_id == adult.get_active_household_membership().id
    stamp = own_task.completed_at
    client.post(f'/household/tasks/{own_task.id}/completion', data={'action': 'complete'})
    assert own_task.completed_at == stamp
    client.post(f'/household/tasks/{own_task.id}/completion', data={'action': 'reopen'})
    assert not own_task.completed and own_task.completed_at is None and own_task.completed_by_membership_id is None
    for row in (sibling_task, unassigned):
        assert client.post(f'/household/tasks/{row.id}/completion', data={'action': 'complete'}).status_code == 403
    for path in (
        '/household/tasks/new', f'/household/tasks/{own_task.id}', f'/household/tasks/{own_task.id}/delete',
        f'/household/tasks/lists/{task_list.id}/edit', f'/household/tasks/lists/{task_list.id}/delete',
    ):
        assert client.post(path, data={'title': 'Spoof', 'list_id': task_list.id}).status_code == 403
    assert client.post('/household/tasks/lists/new', data={'title': 'Bad', 'visibility': 'shared'}).status_code == 403
    assert not sibling_task.completed and not unassigned.completed


def test_corrupt_child_owner_role_never_grants_shared_task_management(app, user, people):
    _, child, _ = people
    child.role = 'admin'
    child.get_active_household_membership().role = 'admin'
    db.session.commit()
    task_list = create_list(app, user)
    task = create_task(app, user, task_list)
    client = client_for(app, child)
    assert client.post('/household/tasks/lists/new', data={'title': 'Bad', 'visibility': 'shared'}).status_code == 403
    assert client.post(f'/household/tasks/{task.id}/completion', data={'action': 'complete'}).status_code == 403
    assert client.post(f'/household/tasks/{task.id}', data={'title': 'Bad'}).status_code == 403


def test_adult_personal_lists_hidden_from_other_adults_owners_and_calendar(app, user, people):
    adult, _, _ = people
    task_list = create_list(app, adult, visibility='personal', title='Private list')
    task = create_task(app, adult, task_list, title='Private job', due_date='2026-11-18')
    client = client_for(app, user)
    assert b'Private list' not in client.get('/household/tasks').data
    assert b'Private job' not in client.get('/household/?month=2026-11').data
    for path in (
        f'/household/tasks?list_id={task_list.id}', f'/household/tasks/{task.id}',
        f'/household/tasks/lists/{task_list.id}/edit',
    ):
        assert client.get(path).status_code == 404
    assert client.post(f'/household/tasks/{task.id}/completion', data={'action': 'complete'}).status_code == 404
    with app.test_request_context():
        login_user(user)
        assert family_query(TaskList).count() == 0 and family_query(HouseholdTask).count() == 0
        assert TaskService.hub({})['stats']['total'] == 0
    assert b'Private job' in client_for(app, adult).get('/household/?month=2026-11').data


def test_child_personal_list_guardian_view_only_and_other_children_hidden(app, user, people):
    adult, child, sibling = people
    task_list = create_list(app, child, title='School jobs', visibility='personal')
    task = create_task(app, child, task_list, due_date='2026-11-18', assigned_membership_id=child.get_active_household_membership().id)
    guardian_client = client_for(app, user)
    assert b'School jobs' in guardian_client.get('/household/tasks').data
    assert b'Wash dishes' in guardian_client.get('/household/?month=2026-11&view=agenda').data
    assert b'After dinner' in guardian_client.get(f'/household/tasks/{task.id}').data
    assert guardian_client.post(f'/household/tasks/{task.id}/completion', data={'action': 'complete'}).status_code == 403
    assert guardian_client.post(f'/household/tasks/{task.id}', data={'title': 'Changed'}).status_code == 403
    assert guardian_client.post(f'/household/tasks/lists/{task_list.id}/delete').status_code == 403
    for actor in (adult, sibling):
        client = client_for(app, actor)
        assert client.get(f'/household/tasks/{task.id}').status_code == 404
        assert b'School jobs' not in client.get('/household/tasks').data
    child_client = client_for(app, child)
    assert child_client.post(f'/household/tasks/{task.id}', data={'title': 'Changed personal job'}).status_code == 302
    assert task.title == 'Changed personal job'
    assert child_client.post(f'/household/tasks/{task.id}/completion', data={'action': 'complete'}).status_code == 302
    assert child_client.post(f'/household/tasks/{task.id}/delete').status_code == 302
    assert HouseholdTask.query.count() == 0


def test_guardianship_change_immediately_updates_personal_list_visibility(app, user, people):
    adult, child, _ = people
    task_list = create_list(app, child, visibility='personal')
    task = create_task(app, child, task_list)
    child.guardian_id = adult.id
    db.session.commit()
    assert client_for(app, user).get(f'/household/tasks/{task.id}').status_code == 404
    assert client_for(app, adult).get(f'/household/tasks/{task.id}').status_code == 200


def test_calendar_source_feed_completion_reopen_move_and_undated_tasks(app, user):
    task_list = create_list(app, user)
    task = create_task(app, user, task_list, due_date='2026-11-18', due_time='09:30')
    create_task(app, user, task_list, title='No date')
    client = client_for(app, user)
    for view in ('month', 'agenda'):
        html = client.get(f'/household/?month=2026-11&view={view}').data
        assert b'Wash dishes' in html and b'09:30' in html and b'No date' not in html
        assert f'/household/tasks/{task.id}'.encode() in html
    client.post(f'/household/tasks/{task.id}/completion', data={'action': 'complete', 'filter': 'all'})
    assert b'Wash dishes' not in client.get('/household/?month=2026-11').data
    client.post(f'/household/tasks/{task.id}/completion', data={'action': 'reopen'})
    assert b'Wash dishes' in client.get('/household/?month=2026-11').data
    client.post(f'/household/tasks/{task.id}', data={'title': task.title, 'due_date': '2026-12-01'})
    assert b'Wash dishes' not in client.get('/household/?month=2026-11&view=agenda').data
    assert b'Wash dishes' in client.get('/household/?month=2026-12&view=agenda').data
    assert CalendarEvent.query.count() == 0


def test_filters_stats_order_and_assigned_to_me_only_use_visible_tasks(app, user, people):
    adult, _, _ = people
    today = datetime.now(LONDON).date()
    task_list = create_list(app, user)
    urgent = create_task(app, user, task_list, title='Urgent', priority='urgent', due_date=today.isoformat())
    create_task(app, user, task_list, title='Past', due_date=(today - timedelta(days=1)).isoformat())
    assigned = create_task(app, user, task_list, title='Assigned', due_date=(today + timedelta(days=7)).isoformat(), assigned_membership_id=user.get_active_household_membership().id)
    done = create_task(app, user, task_list, title='Finished', due_date=today.isoformat())
    client = client_for(app, user)
    client.post(f'/household/tasks/{done.id}/completion', data={'action': 'complete'})
    hidden_list = create_list(app, adult, visibility='personal')
    create_task(app, adult, hidden_list, title='Hidden')
    with app.test_request_context():
        login_user(user)
        def context(filt):
            return TaskService.hub({'list_id': str(task_list.id), 'filter': filt})
        assert context('active')['tasks'][0].id == urgent.id
        assert context('all')['stats'] == {'total': 4, 'done': 1, 'overdue': 1, 'today': 1, 'upcoming': 1}
        assert [row.title for row in context('overdue')['tasks']] == ['Past']
        assert [row.id for row in context('today')['tasks']] == [urgent.id]
        assert [row.id for row in context('completed')['tasks']] == [done.id]
        assert [row.id for row in context('mine')['tasks']] == [assigned.id]


@pytest.mark.parametrize('changes,message', [
    ({'title': ''}, 'list name'),
    ({'title': 'x' * 129}, 'list name'),
    ({'visibility': 'unknown'}, 'personal or shared'),
    ({'icon': 'bad'}, 'icon and colour'),
    ({'colour': 'red; bad'}, 'icon and colour'),
])
def test_invalid_list_does_not_write(app, user, changes, message):
    with pytest.raises(ValueError, match=message):
        create_list(app, user, **changes)
    assert TaskList.query.count() == 0


@pytest.mark.parametrize('changes,message', [
    ({'title': ''}, 'task title'),
    ({'title': 'x' * 257}, 'task title'),
    ({'notes': 'x' * 5001}, 'notes'),
    ({'priority': 'bad'}, 'priority'),
    ({'due_date': 'bad'}, 'valid task due date'),
    ({'due_date': '1899-12-31'}, 'between 1900'),
    ({'due_time': '09:30'}, 'due date before'),
    ({'due_date': '2026-11-10', 'due_time': 'bad'}, 'valid due'),
    ({'due_date': '2026-03-29', 'due_time': '01:30'}, 'does not exist'),
    ({'due_date': '2026-10-25', 'due_time': '01:30'}, 'occurs twice'),
    ({'assigned_membership_id': 'bad'}, 'active assignee'),
    ({'assigned_membership_id': '99999'}, 'active assignee'),
    ({'list_id': 'bad'}, 'visible task list'),
    ({'list_id': '99999'}, 'visible task list'),
])
def test_invalid_task_does_not_write(app, user, changes, message):
    task_list = create_list(app, user)
    with pytest.raises(ValueError, match=message):
        create_task(app, user, task_list, **changes)
    assert HouseholdTask.query.count() == 0


def test_private_assignment_restrictions_and_inactive_member(app, user, people):
    adult, _, _ = people
    task_list = create_list(app, user, visibility='personal')
    with pytest.raises(ValueError, match='list creator'):
        create_task(app, user, task_list, assigned_membership_id=adult.get_active_household_membership().id)
    shared = create_list(app, user)
    member_id = adult.get_active_household_membership().id
    adult.is_active = False
    db.session.commit()
    with pytest.raises(ValueError, match='active assignee'):
        create_task(app, user, shared, assigned_membership_id=member_id)


def test_active_household_not_default_and_cross_household_ids_rejected(app, user, family):
    task_list = create_list(app, user)
    original = create_task(app, user, task_list)
    original_membership_id = user.get_active_household_membership().id
    other = Family(name='Other household')
    db.session.add(other)
    db.session.flush()
    member = HouseholdMembership(user_id=user.id, family_id=other.id, role='member', allowed_modules=['household'])
    db.session.add(member)
    db.session.commit()
    client = client_for(app, user)
    response = client.post('/household/tasks/new', data={'title': 'Test', 'list_id': task_list.id, 'assigned_membership_id': member.id})
    assert b'active assignee' in response.data and HouseholdTask.query.count() == 1
    client.post('/family/select', data={'family_id': other.id})
    for path in (f'/household/tasks/{original.id}', f'/household/tasks?list_id={task_list.id}'):
        assert client.get(path).status_code == 404
    assert client.post(f'/household/tasks/{original.id}/completion', data={'action': 'complete'}).status_code == 404
    client.post('/household/tasks/lists/new', data={'title': 'Selected', 'visibility': 'personal', 'family_id': family.id})
    selected = TaskList.query.filter_by(family_id=other.id).one()
    client.post('/household/tasks/new', data={
        'title': 'Selected job', 'list_id': selected.id, 'assigned_membership_id': member.id, 'family_id': family.id,
    })
    task = HouseholdTask.query.filter_by(family_id=other.id).one()
    assert task.creator_membership_id == member.id
    with pytest.raises(CrossFamilyReferenceError):
        db.session.add(HouseholdTask(family_id=other.id, list_id=task_list.id, title='Bad'))
        db.session.flush()
    db.session.rollback()
    with pytest.raises(CrossFamilyReferenceError):
        task.assigned_membership_id = original_membership_id
        db.session.flush()
    db.session.rollback()


def test_validation_preserves_inputs_and_invalid_filters_are_reported(app, user):
    task_list = create_list(app, user)
    client = client_for(app, user)
    response = client.get(f'/household/tasks/new?list_id={task_list.id}&date=2026-11-18')
    assert response.status_code == 200 and b'value="2026-11-18"' in response.data
    response = client.post('/household/tasks/new', data={
        'list_id': task_list.id, 'title': 'Keep title', 'notes': 'Keep notes', 'due_date': '2026-11-18', 'due_time': 'invalid',
    })
    assert b'Keep title' in response.data and b'Keep notes' in response.data and b'value="2026-11-18"' in response.data
    assert HouseholdTask.query.count() == 0
    response = client.post('/household/tasks/lists/new', data={'title': 'Keep list', 'icon': 'bad'})
    assert b'Keep list' in response.data and b'icon and colour' in response.data
    response = client.get('/household/tasks?filter=bad', follow_redirects=True)
    assert response.status_code == 200 and b'alert-danger' in response.data
    assert client.get('/household/tasks?list_id=bad').status_code == 404
    assert b'alert-danger' in client.get('/household/tasks/new?date=bad', follow_redirects=True).data


def test_no_privacy_change_task_move_or_completion_spoofing(app, user):
    task_list = create_list(app, user)
    task = create_task(app, user, task_list)
    personal = create_list(app, user, visibility='personal')
    client = client_for(app, user)
    response = client.post(f'/household/tasks/lists/{task_list.id}/edit', data={'title': 'Changed', 'visibility': 'personal'})
    assert b'privacy cannot be changed' in response.data and task_list.visibility == 'shared'
    response = client.post(f'/household/tasks/{task.id}', data={'title': 'Move', 'list_id': personal.id})
    assert b'cannot be moved' in response.data and task.list_id == task_list.id and task.title == 'Wash dishes'
    for data in ({'action': 'toggle'}, {'action': 'complete', 'filter': 'bad'}):
        response = client.post(f'/household/tasks/{task.id}/completion', data=data, follow_redirects=True)
        assert b'alert-danger' in response.data and not task.completed
    client.post(f'/household/tasks/{task.id}', data={
        'title': 'New title', 'completed': 'true', 'completed_at': '2026-01-01', 'completed_by_membership_id': '999',
    })
    assert task.title == 'New title' and not task.completed and task.completed_at is None


@pytest.mark.parametrize('operation', ['create_list', 'edit_list', 'delete_list', 'create_task', 'edit_task', 'delete_task', 'completion'])
def test_write_failures_rollback_and_report(app, user, monkeypatch, operation):
    task_list = create_list(app, user)
    task = create_task(app, user, task_list)
    client = client_for(app, user)
    monkeypatch.setattr(db.session, 'commit', Mock(side_effect=OperationalError('write', {}, Exception('unavailable'))))
    path, data = {
        'create_list': ('/household/tasks/lists/new', {'title': 'New'}),
        'edit_list': (f'/household/tasks/lists/{task_list.id}/edit', {'title': 'Changed'}),
        'delete_list': (f'/household/tasks/lists/{task_list.id}/delete', {}),
        'create_task': ('/household/tasks/new', {'title': 'New', 'list_id': task_list.id}),
        'edit_task': (f'/household/tasks/{task.id}', {'title': 'Changed'}),
        'delete_task': (f'/household/tasks/{task.id}/delete', {}),
        'completion': (f'/household/tasks/{task.id}/completion', {'action': 'complete'}),
    }[operation]
    response = client.post(path, data=data, follow_redirects=True)
    assert response.status_code == 200 and b'No changes were saved.' in response.data
    db.session.expire_all()
    assert TaskList.query.count() == 1 and HouseholdTask.query.count() == 1
    assert task_list.title == 'House jobs' and task.title == 'Wash dishes' and not task.completed


def test_csrf_required_for_all_writes_and_get_cannot_mutate(app, user, monkeypatch):
    task_list = create_list(app, user)
    task = create_task(app, user, task_list)
    client = client_for(app, user)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    g.pop('csrf_token', None)
    for path in (
        '/household/tasks/lists/new', f'/household/tasks/lists/{task_list.id}/edit',
        f'/household/tasks/lists/{task_list.id}/delete', '/household/tasks/new',
        f'/household/tasks/{task.id}', f'/household/tasks/{task.id}/delete', f'/household/tasks/{task.id}/completion',
    ):
        assert client.post(path, data={'title': 'New', 'list_id': task_list.id}).status_code == 400
    for path in (f'/household/tasks/{task.id}/delete', f'/household/tasks/{task.id}/completion', f'/household/tasks/lists/{task_list.id}/delete'):
        assert client.get(path).status_code == 405
    assert TaskList.query.count() == 1 and HouseholdTask.query.count() == 1 and not task.completed


def test_module_gate_for_task_surfaces(app, user, people):
    adult, _, _ = people
    task_list = create_list(app, user)
    task = create_task(app, user, task_list)
    adult.get_active_household_membership().allowed_modules = []
    db.session.commit()
    client = client_for(app, adult)
    for path in ('/household/tasks', '/household/tasks/new', '/household/tasks/lists/new', f'/household/tasks/{task.id}'):
        assert client.get(path).status_code == 403
    for path in (
        '/household/tasks/new', '/household/tasks/lists/new', f'/household/tasks/{task.id}',
        f'/household/tasks/{task.id}/completion', f'/household/tasks/{task.id}/delete',
        f'/household/tasks/lists/{task_list.id}/edit', f'/household/tasks/lists/{task_list.id}/delete',
    ):
        assert client.post(path).status_code == 403


@pytest.mark.parametrize('departure', ['membership', 'account'])
def test_departure_removes_personal_lists_preserves_shared_tasks_and_detaches_links(app, user, family, people, departure):
    from services.household.family_service import FamilyService
    adult, _, _ = people
    member_id = adult.get_active_household_membership().id
    personal = create_list(app, adult, visibility='personal')
    create_task(app, adult, personal)
    shared = create_list(app, adult)
    task = create_task(app, adult, shared, assigned_membership_id=member_id, due_date='2026-11-18')
    client_for(app, adult).post(f'/household/tasks/{task.id}/completion', data={'action': 'complete'})
    stamp = task.completed_at
    if departure == 'account':
        response = client_for(app, adult).post('/account/security/delete', data={
            'password': 'TestPass1!', 'confirmation': 'DELETE MY ACCOUNT',
        })
        assert response.location.endswith('/login')
    else:
        with app.test_request_context():
            login_user(user)
            FamilyService.remove_member(adult.id, family.id, user.id)
    db.session.expire_all()
    assert TaskList.query.count() == 1 and HouseholdTask.query.count() == 1
    assert shared.creator_membership_id is None
    assert task.creator_membership_id is None and task.assigned_membership_id is None and task.completed_by_membership_id is None
    assert task.completed and task.completed_at == stamp
    assert client_for(app, user).get(f'/household/tasks/{task.id}').status_code == 200
    newcomer = User(name='New', email='new@example.com', password_hash=user.password_hash)
    db.session.add(newcomer)
    db.session.flush()
    db.session.add(HouseholdMembership(id=member_id, family_id=family.id, user_id=newcomer.id, role='member'))
    db.session.commit()
    db.session.expire_all()
    assert task.assigned_membership_id is None and task.completed_by_membership_id is None


def test_list_deletion_removes_tasks_without_calendar_duplicates(app, user):
    task_list = create_list(app, user)
    create_task(app, user, task_list, due_date='2026-11-18')
    response = client_for(app, user).post(f'/household/tasks/lists/{task_list.id}/delete')
    assert response.status_code == 302 and TaskList.query.count() == 0 and HouseholdTask.query.count() == 0
    assert CalendarEvent.query.count() == 0


def test_task_migration_round_trip_matches_model_constraints(app):
    path = Path(app.root_path) / 'migrations' / 'versions' / 'b16c2e8a345f_add_household_task_lists.py'
    spec = importlib.util.spec_from_file_location('task_schema', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('PRAGMA foreign_keys=ON'))
        connection.execute(sa.text('CREATE TABLE families (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE household_memberships (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('INSERT INTO families VALUES (1)'))
        connection.execute(sa.text('INSERT INTO household_memberships VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            for model in (TaskList, HouseholdTask):
                constraints = {row['name'] for row in sa.inspect(connection).get_check_constraints(model.__tablename__)}
                assert constraints == {row.name for row in model.__table__.constraints if isinstance(row, sa.CheckConstraint)}
            connection.execute(sa.text(
                "INSERT INTO task_lists (id,family_id,title,visibility,creator_membership_id) VALUES (1,1,'Jobs','shared',1)",
            ))
            connection.execute(sa.text(
                "INSERT INTO household_tasks (id,family_id,list_id,title,assigned_membership_id) VALUES (1,1,1,'Dishes',1)",
            ))
            assert connection.execute(sa.text('SELECT completed FROM household_tasks')).scalar_one() == 0
            connection.execute(sa.text('DELETE FROM household_memberships'))
            assert connection.execute(sa.text('SELECT assigned_membership_id FROM household_tasks')).scalar_one() is None
            assert connection.execute(sa.text('SELECT creator_membership_id FROM task_lists')).scalar_one() is None
            connection.execute(sa.text('DELETE FROM task_lists'))
            assert connection.execute(sa.text('SELECT COUNT(*) FROM household_tasks')).scalar_one() == 0
            assert connection.execute(sa.text('PRAGMA foreign_key_check')).all() == []
            migration.downgrade()
            assert not {'household_tasks', 'task_lists'} & set(sa.inspect(connection).get_table_names())
            migration.upgrade()
    engine.dispose()
