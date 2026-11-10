from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from flask import g
from flask_login import login_user

from extensions import db, limiter
from models import Family, HouseholdMembership, HouseholdTask, RewardGoal, RewardJob, RewardPointEntry, TaskList, User
from services.household.calendar_service import CalendarService, LONDON
from services.household.my_day_service import MyDayService
from tests.auth_helpers import detach_user_from_households, login_client
from tests.test_activity_planning import create as create_activity
from tests.test_household_rewards import job_for, reward_for
from tests.test_household_tasks import create_list, create_task, people
from tests.test_module_access import adult
from tests.test_passkeys import ORIGIN, RP_ID, register
from tests.test_two_factor import enable_two_factor, totp_code


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


def test_settings_connect_people_access_and_focused_child_creation(app, user):
    client = client_for(app, user)
    for path in ('/central/settings', '/central/family/', '/central/settings/access', '/central/account/children', '/central/setup'):
        response = client.get(path)
        assert response.status_code == 200
        assert b'href="/central/settings/children/new"' in response.data
    settings = client.get('/central/settings').get_data(as_text=True)
    assert all(heading in settings for heading in ('Your account', 'Household &amp; people', 'Module settings'))
    assert b'id="invite-adult"' in client.get('/central/family/').data
    access = client.get('/central/settings/access').data
    assert b'action="/central/settings/children/create"' not in access
    form = client.get('/central/settings/children/new').get_data(as_text=True)
    assert 'action="/central/settings/children/create"' in form
    assert f'Use at least {app.config["PASSWORD_MIN_LENGTH"]} characters' in form
    response = client.post('/central/settings/children/create', data={
        'name': 'New child', 'email': 'new-child@example.com',
        'password': 'TestPass1!', 'confirm_password': 'TestPass1!',
    })
    assert response.location == '/central/family/'
    assert b'Manage child account' in client.get(response.location).data


def test_child_form_escapes_retained_fields_and_never_echoes_password(app, user):
    client = client_for(app, user)
    response = client.post('/central/settings/children/create', data={
        'name': '"><script>alert(1)</script>', 'email': 'invalid',
        'password': 'NeverEchoThisPassword1!', 'confirm_password': 'Different2!',
    })
    assert response.status_code == 200
    assert b'&lt;script&gt;' in response.data
    assert b'<script>alert(1)</script>' not in response.data
    assert b'NeverEchoThisPassword1!' not in response.data
    assert b'Different2!' not in response.data


def test_owner_setup_is_read_only_scoped_and_honest_about_module_access(app, family, user, people):
    _, child, _ = people
    other = Family(name='Second household')
    db.session.add(other)
    db.session.flush()
    db.session.add(HouseholdMembership(
        family_id=other.id, user_id=user.id, role='admin', allowed_modules=[],
    ))
    db.session.commit()
    client = client_for(app, user)
    for _ in range(2):
        response = client.get('/central/setup')
        assert response.status_code == 200
        assert b'2 adult accounts, 2 child accounts' in response.data
    assert TaskList.query.count() == 0
    assert RewardJob.query.count() == 0
    shared = create_list(app, user)
    create_task(app, user, shared, title='First shared job')
    reward_for(app, user)
    client = client_for(app, user)
    response = client.get('/central/setup')
    assert b'already has a shared task' in response.data
    assert b'Your reward catalogue is started' in response.data
    client.post('/central/family/select', data={'family_id': other.id})
    response = client.get('/central/setup')
    assert b'Set up Second household' in response.data
    assert b'1 adult account, 0 child accounts' in response.data
    assert b'Enable Household Hub for your account' in response.data
    assert b'href="/household/rewards' not in response.data
    assert b'href="/household/tasks' not in response.data
    response = client.post('/central/settings/children/create', data={
        'name': 'Second child', 'email': 'second-child@example.com',
        'password': 'TestPass1!', 'confirm_password': 'TestPass1!',
    })
    assert response.location == '/central/family/'
    created = User.query.filter_by(email='second-child@example.com').one()
    assert created.family_id == other.id and created.guardian_id == user.id
    assert child.family_id == family.id


def test_owner_pages_reject_members_children_and_detached_accounts(app, user, people):
    member, child, _ = people
    for actor in (member, child):
        client = client_for(app, actor)
        for path in ('/central/setup', '/central/settings/children/new'):
            assert client.get(path).status_code == 403
    child.get_active_household_membership().role = 'admin'
    db.session.commit()
    client = client_for(app, child)
    assert client.get('/central/setup').status_code == 403
    assert client.get('/central/settings/children/new').status_code == 403
    detach_user_from_households(user)
    client = client_for(app, user)
    assert client.get('/central/setup').status_code == 403
    assert client.get('/central/settings/children/new').status_code == 403


def test_child_empty_day_has_simple_navigation_and_no_get_mutations(app, user, people):
    adult_member, child, _ = people
    client = client_for(app, child)
    assert client.get('/').location == '/household/my-day'
    for path in ('/household/my-day', '/central/'):
        response = client.get(path)
        assert response.status_code == 200
        assert b'<h1>My day</h1>' in response.data
        assert b'Nothing planned today' in response.data
        sidebar = response.get_data(as_text=True).split('id="workspaceNav"', 1)[1].split('</aside>', 1)[0]
        assert 'href="/household/my-day"' in sidebar
        assert 'href="/household/rewards"' in sidebar
        assert 'href="/finance/dashboard"' not in sidebar
        assert 'Switch workspace' not in sidebar
        assert 'Household setup' not in sidebar
    preferences = client.get('/central/preferences').data
    assert b'My day opens after sign-in' in preferences
    assert b'name="default_workspace"' not in preferences
    for model in (TaskList, HouseholdTask, RewardJob, RewardGoal, RewardPointEntry):
        assert model.query.count() == 0
    assert client_for(app, adult_member).get('/household/my-day').status_code == 403
    assert client_for(app, user).get('/').location == '/central/'


def test_my_day_only_shows_own_actionable_tasks_and_separates_dates(app, user, people):
    member, child, sibling = people
    today = datetime.now(LONDON).date()
    shared = create_list(app, user)
    membership_id = child.get_active_household_membership().id
    current = create_task(app, user, shared, title='My current job', assigned_membership_id=membership_id)
    earlier = create_task(app, member, shared, title='My earlier job', assigned_membership_id=membership_id, due_date=(today - timedelta(days=1)).isoformat())
    later = create_task(app, user, shared, title='My later job', assigned_membership_id=membership_id, due_date=(today + timedelta(days=1)).isoformat())
    create_task(app, user, shared, title='Sibling shared job', assigned_membership_id=sibling.get_active_household_membership().id)
    create_task(app, user, shared, title='Nobody assigned')
    personal = create_list(app, child, title='Mine', visibility='personal')
    personal_task = create_task(app, child, personal, title='My personal job')
    sibling_list = create_list(app, sibling, title='Sibling list', visibility='personal')
    create_task(app, sibling, sibling_list, title='Sibling secret')
    adult_list = create_list(app, member, title='Adult list', visibility='personal')
    create_task(app, member, adult_list, title='Adult secret')
    done = create_task(app, user, shared, title='Already done', assigned_membership_id=membership_id)
    client = client_for(app, child)
    client.post(f'/household/tasks/{done.id}/completion', data={'action': 'complete'})
    with app.test_request_context():
        login_user(child)
        data = MyDayService.page_data()
        assert {task.id for task in data['tasks']} == {current.id, personal_task.id}
        assert [task.id for task in data['earlier_tasks']] == [earlier.id]
        assert [task.id for task in data['later_tasks']] == [later.id]
    client = client_for(app, child)
    html = client.get('/household/my-day').get_data(as_text=True)
    for hidden in ('Sibling shared job', 'Nobody assigned', 'Sibling secret', 'Adult secret', 'Already done'):
        assert hidden not in html
    assert 'Earlier jobs &mdash; check with an adult (1)' in html
    response = client.post(f'/household/tasks/{current.id}/completion', data={
        'action': 'complete', 'return_to': 'my-day',
    })
    assert response.location == '/household/my-day' and current.completed
    assert b'My current job' not in client.get(response.location).data
    response = client.post(f'/household/tasks/{personal_task.id}/completion', data={
        'action': 'complete', 'return_to': 'https://example.com',
    })
    assert response.location.startswith('/household/tasks?')


def test_my_day_rewards_are_own_and_reuse_approval_and_reservation_rules(app, user, people):
    _, child, sibling = people
    today = datetime.now(LONDON).date()
    current = job_for(app, user, child)
    earlier = job_for(app, user, child, due_date=(today - timedelta(days=1)).isoformat())
    later = job_for(app, user, child, due_date=(today + timedelta(days=1)).isoformat())
    sibling_job = job_for(app, user, sibling)
    reward = reward_for(app, user, cost=10)
    client = client_for(app, child)
    client.post('/household/rewards/actions/goal', data={'reward_id': reward.id})
    response = client.post('/household/rewards/actions/submit-job', data={
        'job_id': current.id, 'return_to': 'my-day',
    })
    assert response.location == '/household/my-day' and current.state == 'submitted'
    assert b'1 job waiting for an adult' in client.get(response.location).data
    assert RewardPointEntry.query.count() == 0
    client_for(app, user).post('/household/rewards/actions/review-job', data={'job_id': current.id, 'action': 'approve'})
    client = client_for(app, child)
    response = client.get('/household/my-day')
    assert b'20 points ready to use' in response.data
    assert b'My goal: Movie night' in response.data
    request = client.post('/household/rewards/actions/request', data={'reward_id': reward.id, 'request_key': '9acec5c6-bf60-45fe-9d98-495b23e8e147'})
    assert request.status_code == 302
    response = client.get('/household/my-day')
    assert b'10 points ready to use' in response.data
    assert b'10 points are held for reward requests' in response.data
    with app.test_request_context():
        login_user(child)
        data = MyDayService.page_data()
        assert data['reward_jobs'] == []
        assert [job.id for job in data['earlier_jobs']] == [earlier.id]
        assert [job.id for job in data['later_jobs']] == [later.id]
        assert sibling_job.id not in {job.id for job in data['earlier_jobs'] + data['later_jobs']}
    client = client_for(app, child)
    assert client.post('/household/rewards/actions/submit-job', data={'job_id': sibling_job.id, 'return_to': 'my-day'}).status_code == 404


def test_my_day_includes_all_approved_occurrences_and_only_visible_events(app, user, people):
    member, child, sibling = people
    today = datetime.now(LONDON).date()
    create_activity(app, user, title='Other attendees welcome', starts_on=today.isoformat(), ends_on=today.isoformat(), attendee_ids=[sibling.get_active_household_membership().id])
    create_activity(app, user, title='Weekly household activity', starts_on=(today - timedelta(days=7)).isoformat(), ends_on=(today - timedelta(days=7)).isoformat(), recurrence='weekly', repeat_until=today.isoformat())
    create_activity(app, user, title='Multi day trip', starts_on=(today - timedelta(days=1)).isoformat(), ends_on=(today + timedelta(days=1)).isoformat())
    create_activity(app, child, title='Pending suggestion', starts_on=today.isoformat(), ends_on=today.isoformat())
    for actor, title, visibility in ((user, 'Shared event', 'shared'), (member, 'Adult private event', 'private'), (sibling, 'Sibling private event', 'private'), (child, 'My private event', 'private')):
        with app.test_request_context():
            login_user(actor)
            CalendarService.create({
                'title': title, 'all_day': 'on', 'starts_on': today.isoformat(),
                'ends_on': today.isoformat(), 'visibility': visibility,
            })
    html = client_for(app, child).get('/household/my-day').get_data(as_text=True)
    for visible in ('Other attendees welcome', 'Weekly household activity', 'Multi day trip', 'Shared event', 'My private event'):
        assert visible in html
    for hidden in ('Pending suggestion', 'Adult private event', 'Sibling private event'):
        assert hidden not in html


def test_my_day_uses_london_today_not_utc_and_converts_event_time(app, user, people):
    _, child, _ = people
    now = datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)
    with app.test_request_context():
        login_user(user)
        CalendarService.create({
            'title': 'Just after midnight', 'starts_at': '2026-07-02T00:15',
            'ends_at': '2026-07-02T01:00',
        })
    client = client_for(app, child)
    with patch('services.household.reward_service.datetime') as clock:
        clock.now.side_effect = lambda zone: now.astimezone(zone)
        response = client.get('/household/my-day')
    assert b'Thursday 02 July' in response.data
    assert b'Just after midnight' in response.data and b'00:15 London' in response.data


def test_child_home_handles_revocation_detachment_and_active_household(app, user, people):
    _, child, _ = people
    other = Family(name='Other family')
    db.session.add(other)
    db.session.flush()
    membership = HouseholdMembership(family_id=other.id, user_id=child.id, role='member', allowed_modules=['household'])
    db.session.add(membership)
    other_owner = adult(other, email='other-owner@example.com', role='admin')
    today = datetime.now(LONDON).date().isoformat()
    create_activity(app, user, title='Original household activity', starts_on=today, ends_on=today)
    create_activity(app, other_owner, title='Second household activity', starts_on=today, ends_on=today)
    client = client_for(app, child)
    client.post('/central/family/select', data={'family_id': other.id})
    response = client.get('/household/my-day')
    assert b'Second household activity' in response.data and b'Original household activity' not in response.data
    membership.allowed_modules = []
    db.session.commit()
    assert client.get('/household/my-day').status_code == 403
    assert client.get('/').location == '/central/'
    assert b'<h1>My day</h1>' not in client.get('/central/').data
    detach_user_from_households(child)
    client = client_for(app, child)
    assert client.get('/').location == '/central/account/security'
    assert client.get('/household/my-day').status_code == 403


@pytest.mark.parametrize('method', ['password', 'two_factor', 'passkey'])
@pytest.mark.parametrize('target, destination', [(None, '/household/my-day'), ('/household/activities', '/household/activities'), ('https://example.com', '/household/my-day')])
def test_child_login_methods_default_to_my_day_but_preserve_safe_links(app, user, people, monkeypatch, method, target, destination):
    _, child, _ = people
    child.preferences = {'default_workspace': 'finance'}
    db.session.commit()
    query = {'next': target} if target else {}
    client = app.test_client()
    if method == 'passkey':
        monkeypatch.setitem(app.config, 'PASSKEY_ORIGIN', ORIGIN)
        monkeypatch.setitem(app.config, 'PASSKEY_RP_ID', RP_ID)
        login_client(client, child.id)
        authenticator = register(client, child)
        client.post('/logout')
        g.pop('_login_user', None)
        options = client.post('/login/passkey/options', query_string=query, json={})
        response = client.post('/login/passkey/verify', json=authenticator.response(options.json))
        assert response.status_code == 200 and response.json['redirect'] == destination
    else:
        if method == 'two_factor':
            enable_two_factor(child)
        response = client.post('/login', query_string=query, data={'email': child.email, 'password': 'TestPass1!'})
        if method == 'two_factor':
            response = client.post('/login/two-factor', data={'code': totp_code(child, 1)})
        assert response.status_code == 302 and response.location == destination
