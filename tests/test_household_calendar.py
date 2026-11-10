import importlib.util
from datetime import date, datetime
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
from models import CalendarEvent, Family, HouseholdMembership, User
from services.household.calendar_service import CalendarService
from services.household.family_service import FamilyService
from tests.auth_helpers import login_client
from utils.db_helpers import family_query
from utils.tenancy_guard import CrossFamilyReferenceError


DATA = {
    'title': 'Family outing', 'description': 'Bring lunch', 'location': 'Park',
    'all_day': 'on', 'starts_on': '2026-11-10', 'ends_on': '2026-11-10',
    'visibility': 'shared', 'edit_policy': 'creator', 'delete_policy': 'creator',
}


def create_as(app, actor, **changes):
    with app.test_request_context():
        login_user(actor)
        return CalendarService.create({**DATA, **changes})


def client_for(app, actor):
    client = app.test_client()
    login_client(client, actor.id)
    return client


@pytest.fixture
def people(family, user):
    member = User(
        family_id=family.id, name='Member', email='member@example.com',
        role='member', password_hash=user.password_hash, allowed_sections='[]',
    )
    child = User(
        family_id=family.id, name='Child', email='child@example.com',
        role='member', account_type='child', guardian_id=user.id,
        password_hash=user.password_hash, allowed_sections='[]',
    )
    other_owner = User(
        family_id=family.id, name='Other owner', email='owner@example.com',
        role='admin', password_hash=user.password_hash,
    )
    db.session.add_all([member, child, other_owner])
    db.session.commit()
    child.get_active_household_membership().allowed_modules = ['household']
    db.session.commit()
    return member, child, other_owner


def test_month_caps_mixed_items_and_counts_only_visible_remainder(app, user, people):
    from services.household.meal_service import MealService
    from services.household.activity_service import ActivityService
    from models.household_tasks import TaskList, HouseholdTask

    member, _, _ = people
    for index in range(4):
        create_as(app, user, title=f'Visible event {index}')
    create_as(app, member, title='Hidden private event', visibility='private')
    with app.test_request_context():
        login_user(user)
        MealService.create_plan({'date': '2026-11-10', 'slot': 'dinner', 'title': 'Hidden by cap meal'})
        ActivityService.create({**DATA, 'title': 'Hidden by cap activity'})
        task_list = TaskList(family_id=user.family_id, title='Shared chores', visibility='shared')
        task_list.tasks.append(HouseholdTask(family_id=user.family_id, title='Hidden by cap task',
                                           due_date=date(2026, 11, 10)))
        db.session.add(task_list)
        db.session.commit()
    client = client_for(app, user)
    html = client.get('/household/?month=2026-11').get_data(as_text=True)
    assert html.count('class="calendar-event"') == 3
    assert '1 more event' in html and '1 more meal' in html
    assert '1 more activity' in html and '1 more task' in html
    assert 'Hidden private event' not in html
    assert 'Hidden by cap' not in html
    assert 'view=agenda&amp;day=2026-11-10#calendar-day-2026-11-10' in html
    agenda = client.get('/household/?month=2026-11&view=agenda&day=2026-11-10').get_data(as_text=True)
    for title in ['Visible event 3', 'Hidden by cap meal', 'Hidden by cap activity', 'Hidden by cap task']:
        assert title in agenda
    assert 'Hidden private event' not in agenda
    assert 'id="calendar-day-2026-11-10"' in agenda


@pytest.mark.parametrize('count', [0, 1, 3, 4, 6])
def test_month_item_cap_exact_threshold(app, user, count):
    for index in range(count):
        create_as(app, user, title=f'Event {index}')
    html = client_for(app, user).get('/household/?month=2026-11').get_data(as_text=True)
    assert html.count('class="calendar-event"') == min(count, 3)
    assert ('class="calendar-more"' in html) == (count > 3)
    if count > 3:
        assert f'{count - 3} more event' in html


def test_empty_day_and_adjacent_month_links_have_agenda_targets(app, user):
    client = client_for(app, user)
    html = client.get('/household/?month=2026-11').get_data(as_text=True)
    assert 'month=2026-10&amp;view=agenda&amp;day=2026-10-26#calendar-day-2026-10-26' in html
    html = client.get('/household/?month=2026-10&view=agenda&day=2026-10-26').get_data(as_text=True)
    assert 'id="calendar-day-2026-10-26"' in html
    assert 'No plans visible to you on this day.' in html


@pytest.mark.parametrize('day', ['bad', '2026-11-31', '2026-12-01'])
def test_invalid_agenda_day_reports_error(app, user, day):
    response = client_for(app, user).get('/household/?month=2026-11&view=agenda&day=' + day,
                                        follow_redirects=True)
    assert response.status_code == 200 and b'alert-danger' in response.data


def test_events_list_is_month_scoped_and_lists_spanning_events_once(app, user):
    spanning = create_as(app, user, title='Spanning event', starts_on='2026-10-31', ends_on='2026-11-02')
    timed = create_as(app, user, title='Timed appointment', all_day='',
                      starts_at='2026-11-10T09:00', ends_at='2026-11-10T10:30')
    create_as(app, user, title='Outside selected month', starts_on='2026-12-01', ends_on='2026-12-01')
    html = client_for(app, user).get('/household/events?month=2026-11').get_data(as_text=True)
    assert html.count('Spanning event') == 1
    assert 'Outside selected month' not in html
    assert html.index('Spanning event') < html.index('Timed appointment')
    assert '31 Oct 2026 &ndash; 02 Nov 2026' in html
    assert '10 Nov 2026, 09:00 GMT &ndash; 10 Nov 2026, 10:30 GMT' in html
    assert f'/household/events/{spanning.id}' in html
    assert f'/household/events/{timed.id}' in html
    assert 'id="eventsMonth"' in html
    assert 'class="planner-views"' not in html
    sidebar = html.split('<nav aria-label="Main navigation">', 1)[1].split('</nav>', 1)[0]
    assert '>New event<' not in sidebar
    assert 'class="workspace-nav-link active" href="/household/events"' in sidebar


def test_events_list_preserves_private_event_visibility(app, user, people):
    member, child, other_owner = people
    create_as(app, member, title='Member private appointment', visibility='private')
    create_as(app, child, title='Child private appointment', visibility='private')
    for actor, expected in (
        (member, ['Member private appointment']),
        (child, ['Child private appointment']),
        (user, ['Child private appointment']),
        (other_owner, []),
    ):
        g.pop('_login_user', None)
        html = client_for(app, actor).get('/household/events?month=2026-11').get_data(as_text=True)
        for title in ['Member private appointment', 'Child private appointment']:
            assert (title in html) == (title in expected)
        assert ('No events visible to you' in html) == (not expected)


def test_events_list_excludes_other_households(app, user):
    other_family = Family(name='Other household')
    db.session.add(other_family)
    db.session.flush()
    outsider = User(family_id=other_family.id, name='Outsider', email='outsider@example.com',
                    role='admin', password_hash=user.password_hash)
    db.session.add(outsider)
    db.session.commit()
    create_as(app, outsider, title='Other household event')
    html = client_for(app, user).get('/household/events?month=2026-11').get_data(as_text=True)
    assert 'Other household event' not in html
    assert 'No events visible to you in November 2026.' in html


@pytest.mark.parametrize('month', ['bad', '1899-12', '2101-01'])
def test_events_invalid_month_is_reported(app, user, month):
    response = client_for(app, user).get('/household/events?month=' + month, follow_redirects=True)
    assert response.status_code == 200 and b'alert-danger' in response.data


def test_events_list_requires_module_access(app, user, people):
    member, _, _ = people
    member.get_active_household_membership().allowed_modules = []
    db.session.commit()
    assert client_for(app, member).get('/household/events').status_code == 403
    g.pop('_login_user', None)
    assert app.test_client().get('/household/events').status_code == 302


def test_month_agenda_event_forms_and_default_workspace(app, user):
    event = create_as(app, user, starts_on='2026-10-31', ends_on='2026-11-02')
    client = client_for(app, user)
    for path in (
        '/household/?month=2026-11', '/household/?month=2026-11&view=agenda',
        '/household/events/new', f'/household/events/{event.id}',
        f'/household/events/{event.id}/edit', '/household/settings',
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.data)
        assert b'Household Hub' in response.data
        assert b'data-palette="blue"' in response.data
    with app.test_request_context():
        login_user(user)
        page = CalendarService.page_data({'month': '2026-11'})
        assert len(page['weeks']) in (4, 5, 6)
        assert all(len(week) == 7 for week in page['weeks'])
        assert event in page['days'][date(2026, 11, 1)]
        assert event not in page['days'][date(2026, 11, 3)]
    client.post('/central/preferences/workspace', data={'default_workspace': 'household'})
    assert client.get('/').location == '/household/'


@pytest.mark.parametrize('view', ['month', 'agenda'])
def test_calendar_month_jump_and_empty_state(app, user, view):
    from html.parser import HTMLParser

    class MonthControlParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.month = None
            self.in_jump_form = False
            self.preserved_view = None
            self.in_disclosure = False
            self.submit_in_disclosure = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'details' and attrs.get('class') == 'planner-date-menu':
                self.in_disclosure = True
            if tag == 'form' and attrs.get('method') == 'GET':
                self.in_jump_form = True
                assert attrs['action'] == '/household/'
            if self.in_jump_form and tag == 'input':
                if attrs.get('name') == 'month':
                    self.month = attrs
                elif attrs.get('name') == 'view':
                    self.preserved_view = attrs['value']
            if tag == 'button' and self.in_jump_form and attrs.get('type') == 'submit':
                self.submit_in_disclosure = self.in_disclosure

        def handle_endtag(self, tag):
            if tag == 'form':
                self.in_jump_form = False
            if tag == 'details':
                self.in_disclosure = False

    client = client_for(app, user)
    html = client.get(f'/household/?month=2026-11&view={view}').get_data(as_text=True)
    parser = MonthControlParser()
    parser.feed(html)
    assert parser.month['value'] == '2026-11'
    assert parser.month['min'] == '1900-01'
    assert parser.month['max'] == '2100-12'
    assert parser.preserved_view == view
    assert parser.submit_in_disclosure
    assert '<details class="planner-date-menu">' in html
    assert '<summary title="Choose another month">' in html
    assert 'class="planner-navigation"' in html
    assert '>Today</a>' in html
    assert 'aria-label="Previous month"' in html
    assert 'aria-label="Next month"' in html
    assert f'month=2026-10&amp;view={view}' in html
    assert f'month=2026-12&amp;view={view}' in html
    assert 'No plans visible to you in November 2026.' in html
    assert 'Only plans you can see are shown.' in html
    if view == 'month':
        assert 'role="region" tabindex="0"' in html
    else:
        assert 'calendar-scroll-help' not in html
    assert client.get(f'/household/?month=2027-03&view={view}').status_code == 200


@pytest.mark.parametrize('view', ['month', 'agenda'])
def test_calendar_empty_state_uses_visible_plans_only(app, user, people, view):
    member, _, _ = people
    create_as(app, member, title='Hidden appointment', visibility='private')
    client = client_for(app, user)
    path = f'/household/?month=2026-11&view={view}'
    html = client.get(path).get_data(as_text=True)
    assert 'Hidden appointment' not in html
    assert 'No plans visible to you in November 2026.' in html

    create_as(app, user, title='Visible appointment')
    html = client.get(path).get_data(as_text=True)
    assert 'Visible appointment' in html
    assert 'No plans visible to you in November 2026.' not in html
    assert 'All day' in html


def test_child_calendar_access_never_unlocks_finance(app, user, people):
    _, child, _ = people
    client = client_for(app, child)
    assert client.get('/household/').status_code == 200
    response = client.post('/household/events/new', data=DATA)
    assert response.status_code == 302
    assert response.location.startswith('/household/events/')
    assert client.get('/finance/dashboard').status_code == 403
    assert b'Open Finance' not in client.get('/household/').data
    child.get_active_household_membership().allowed_modules = []
    db.session.commit()
    for path in ('/household/', '/household/events/new', response.location, '/household/settings'):
        assert client.get(path).status_code == 403
    assert client.post('/household/events/new', data=DATA).status_code == 403


def test_private_events_hidden_from_owners_lists_direct_links_and_writes(app, user, people):
    member, _, other_owner = people
    event = create_as(app, member, title='PRIVATE SECRET', visibility='private')
    for actor in (user, other_owner):
        client = client_for(app, actor)
        for suffix in ('', '/edit'):
            assert client.get(f'/household/events/{event.id}{suffix}').status_code == 404
        assert client.post(f'/household/events/{event.id}/edit', data=DATA).status_code == 404
        assert client.post(f'/household/events/{event.id}/delete').status_code == 404
        for view in ('month', 'agenda'):
            html = client.get(f'/household/?month=2026-11&view={view}').data
            assert b'PRIVATE SECRET' not in html
        with app.test_request_context():
            login_user(actor)
            assert family_query(CalendarEvent).count() == 0


def test_child_private_visibility_and_guardian_transfer(app, user, people):
    member, child, other_owner = people
    event = create_as(app, child, visibility='private')
    client = client_for(app, user)
    assert b'Private: child and designated guardian' in client.get(f'/household/events/{event.id}').data
    assert client.get(f'/household/events/{event.id}/edit').status_code == 403
    assert client_for(app, other_owner).get(f'/household/events/{event.id}').status_code == 404
    client = client_for(app, child)
    assert client.post(f'/household/events/{event.id}/edit', data={
        **DATA, 'visibility': 'private', 'edit_policy': 'selected',
        'edit_members': [user.get_active_household_membership().id],
    }).status_code == 302
    assert client_for(app, user).get(f'/household/events/{event.id}/edit').status_code == 200
    client_for(app, user).post(f'/central/account/children/{child.id}', data={
        'action': 'transfer', 'guardian_id': other_owner.id,
    })
    assert client_for(app, user).get(f'/household/events/{event.id}').status_code == 404
    assert client_for(app, other_owner).get(f'/household/events/{event.id}').status_code == 200
    assert client_for(app, other_owner).get(f'/household/events/{event.id}/edit').status_code == 403


def test_edit_delete_are_independent_and_only_managers_change_permissions(app, user, people):
    member, child, other_owner = people
    event = create_as(
        app, child, edit_policy='selected',
        edit_members=[member.get_active_household_membership().id],
    )
    client = client_for(app, member)
    assert client.get(f'/household/events/{event.id}/edit').status_code == 200
    assert client.post(f'/household/events/{event.id}/delete').status_code == 403
    response = client.post(f'/household/events/{event.id}/edit', data={
        **DATA, 'edit_policy': 'household',
    })
    assert b'Only the creator or an owner' in response.data
    assert event.edit_policy == 'selected'
    content = {key: value for key, value in DATA.items() if key not in ('visibility', 'edit_policy', 'delete_policy')}
    client.post(f'/household/events/{event.id}/edit', data={**content, 'title': 'Changed'})
    assert event.title == 'Changed'
    # Owners manage shared items regardless of creator-only item policies.
    client = client_for(app, other_owner)
    assert client.get(f'/household/events/{event.id}/edit').status_code == 200
    assert client.post(f'/household/events/{event.id}/delete').status_code == 302
    assert db.session.get(CalendarEvent, event.id) is None


def test_household_policy_and_selected_delete_only(app, user, people):
    member, child, _ = people
    event = create_as(
        app, user, edit_policy='household', delete_policy='selected',
        delete_members=[child.get_active_household_membership().id],
    )
    client = client_for(app, member)
    assert client.get(f'/household/events/{event.id}/edit').status_code == 200
    assert client.post(f'/household/events/{event.id}/delete').status_code == 403
    assert client_for(app, child).post(f'/household/events/{event.id}/delete').status_code == 302


def test_foreign_household_ids_and_secondary_household_writes(app, family, user):
    other = Family(name='Second')
    db.session.add(other)
    db.session.flush()
    membership = HouseholdMembership(user_id=user.id, family_id=other.id, role='member', allowed_modules=['household'])
    db.session.add(membership)
    db.session.commit()
    original = create_as(app, user)
    client = client_for(app, user)
    client.post('/central/family/select', data={'family_id': other.id})
    for suffix in ('', '/edit'):
        assert client.get(f'/household/events/{original.id}{suffix}').status_code == 404
    assert client.post(f'/household/events/{original.id}/delete').status_code == 404
    response = client.post('/household/events/new', data={**DATA, 'family_id': family.id})
    second = db.session.get(CalendarEvent, int(response.location.rsplit('/', 1)[1]))
    assert second.family_id == other.id
    assert second.creator_membership_id == membership.id
    response = client.post(f'/household/events/{second.id}/edit', data={
        **DATA, 'edit_policy': 'selected', 'edit_members': [user.get_active_household_membership().id],
    })
    assert b'Select active household members' in response.data
    assert second.edit_policy == 'creator'
    # The write-time guard also rejects corrupt creator links across households.
    with pytest.raises(CrossFamilyReferenceError):
        db.session.add(CalendarEvent(
            family_id=family.id, creator_membership_id=membership.id,
            title='Bad link', starts_on=date(2026, 11, 1), ends_on=date(2026, 11, 1),
        ))
        db.session.flush()
    db.session.rollback()


@pytest.mark.parametrize('starts,ends,utc_start,utc_end', [
    ('2026-07-01T10:00', '2026-07-01T11:00', datetime(2026, 7, 1, 9), datetime(2026, 7, 1, 10)),
    ('2026-12-01T10:00', '2026-12-01T11:00', datetime(2026, 12, 1, 10), datetime(2026, 12, 1, 11)),
    ('2026-03-29T00:30', '2026-03-29T02:30', datetime(2026, 3, 29, 0, 30), datetime(2026, 3, 29, 1, 30)),
])
def test_london_times_store_utc_and_render_local(app, user, starts, ends, utc_start, utc_end):
    event = create_as(app, user, all_day='', starts_at=starts, ends_at=ends)
    assert event.starts_at == utc_start
    assert event.ends_at == utc_end
    html = client_for(app, user).get(f'/household/events/{event.id}/edit').data
    assert starts.encode() in html and ends.encode() in html


@pytest.mark.parametrize('changes,message', [
    ({'title': ''}, 'event title'),
    ({'ends_on': '2026-11-09'}, 'end date'),
    ({'starts_on': 'bad'}, 'valid start'),
    ({'starts_on': '1800-01-01'}, 'between 1900'),
    ({'edit_policy': 'bad'}, 'supported permission'),
    ({'visibility': 'private', 'edit_policy': 'household'}, 'Private events'),
    ({'edit_policy': 'selected', 'edit_members': []}, 'Select active'),
    ({'edit_policy': 'selected', 'edit_members': ['bad']}, 'Choose household members'),
    ({'all_day': '', 'starts_at': '2026-03-29T01:30', 'ends_at': '2026-03-29T03:00'}, 'does not exist'),
    ({'all_day': '', 'starts_at': '2026-10-25T01:30', 'ends_at': '2026-10-25T03:00'}, 'occurs twice'),
    ({'all_day': '', 'starts_at': '2026-11-10T12:00', 'ends_at': '2026-11-10T11:00'}, 'end time'),
])
def test_invalid_event_rejected_without_writes(app, user, changes, message):
    with pytest.raises(ValueError, match=message):
        create_as(app, user, **changes)
    assert CalendarEvent.query.count() == 0


def test_all_day_dates_and_timed_midnight_end_boundaries(app, user):
    all_day = create_as(app, user, starts_on='2026-03-28', ends_on='2026-03-30')
    assert all_day.starts_at is None and all_day.ends_at is None
    timed = create_as(
        app, user, all_day='', starts_at='2026-11-10T23:00', ends_at='2026-11-11T00:00',
    )
    assert timed.ends_on == date(2026, 11, 10)
    with app.test_request_context():
        login_user(user)
        page = CalendarService.page_data({'month': '2026-11'})
        assert timed in page['days'][date(2026, 11, 10)]
        assert timed not in page['days'][date(2026, 11, 11)]


@pytest.mark.parametrize('query', ['month=bad', 'month=1800-01', 'view=bad'])
def test_invalid_calendar_selection_is_reported(app, user, query):
    response = client_for(app, user).get('/household/?' + query, follow_redirects=True)
    assert response.status_code == 200
    assert b'alert-danger' in response.data


def test_creator_removal_removes_private_and_retains_shared_for_owners(app, family, user, people):
    member, _, _ = people
    shared = create_as(app, member)
    private = create_as(app, member, visibility='private')
    private_id = private.id
    client = client_for(app, user)
    with app.test_request_context():
        login_user(user)
        FamilyService.remove_member(member.id, family.id, user.id)
    db.session.expire_all()
    assert db.session.get(CalendarEvent, private_id) is None
    assert db.session.get(CalendarEvent, shared.id).creator_membership_id is None
    assert client.get(f'/household/events/{shared.id}/edit').status_code == 200
    assert b'household owners manage' in client.get(f'/household/events/{shared.id}').data


def test_account_deletion_retains_shared_calendar_but_removes_private(app, user, people):
    member, _, _ = people
    shared = create_as(app, member)
    private = create_as(app, member, visibility='private')
    private_id = private.id
    client = client_for(app, member)
    response = client.post('/central/account/security/delete', data={
        'password': 'TestPass1!', 'confirmation': 'DELETE MY ACCOUNT',
    })
    assert response.location.endswith('/login')
    db.session.expire_all()
    assert db.session.get(CalendarEvent, private_id) is None
    assert db.session.get(CalendarEvent, shared.id).creator_membership_id is None
    assert client_for(app, user).get(f'/household/events/{shared.id}/edit').status_code == 200


@pytest.mark.parametrize('departure', ['membership', 'account'])
def test_departure_revokes_selected_grants_even_when_membership_id_is_reused(app, family, user, departure):
    editor = User(
        family_id=family.id, name='Departing', email='departing@example.com',
        role='member', password_hash=user.password_hash,
    )
    db.session.add(editor)
    db.session.commit()
    membership_id = editor.get_active_household_membership().id
    event = create_as(
        app, user, edit_policy='selected', edit_members=[membership_id],
        delete_policy='selected', delete_members=[membership_id],
    )
    if departure == 'membership':
        with app.test_request_context():
            login_user(user)
            FamilyService.remove_member(editor.id, family.id, user.id)
    else:
        response = client_for(app, editor).post('/central/account/security/delete', data={
            'password': 'TestPass1!', 'confirmation': 'DELETE MY ACCOUNT',
        })
        assert response.location.endswith('/login')
    db.session.expire_all()
    assert event.edit_members == []
    assert event.delete_members == []
    db.session.expunge(editor)
    newcomer = User(
        family_id=family.id, name='New member', email='new@example.com',
        role='member', password_hash=user.password_hash,
    )
    db.session.add(newcomer)
    db.session.commit()
    if db.engine.dialect.name == 'sqlite':
        assert newcomer.get_active_household_membership().id == membership_id
    client = client_for(app, newcomer)
    assert client.get(f'/household/events/{event.id}').status_code == 200
    assert client.get(f'/household/events/{event.id}/edit').status_code == 403
    assert client.post(f'/household/events/{event.id}/delete').status_code == 403


def test_calendar_csrf_and_failed_commit_are_explicit(app, user, monkeypatch):
    event = create_as(app, user)
    client = client_for(app, user)
    monkeypatch.setattr(db.session, 'commit', Mock(side_effect=OperationalError('write', {}, Exception('unavailable'))))
    response = client.post(f'/household/events/{event.id}/edit', data={**DATA, 'title': 'Changed'})
    assert b'No changes were saved.' in response.data
    assert db.session.get(CalendarEvent, event.id).title == DATA['title']
    assert b'No changes were saved.' in client.post('/household/events/new', data=DATA).data
    assert CalendarEvent.query.count() == 1
    response = client.post(f'/household/events/{event.id}/delete', follow_redirects=True)
    assert b'No changes were saved.' in response.data
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    g.pop('csrf_token', None)
    for path in ('/household/events/new', f'/household/events/{event.id}/edit', f'/household/events/{event.id}/delete'):
        assert client.post(path, data=DATA).status_code == 400


def test_calendar_migration_round_trip_matches_model_constraints(app):
    path = Path(app.root_path) / 'migrations' / 'versions' / 'd72e8a4c901b_add_household_calendar.py'
    spec = importlib.util.spec_from_file_location('calendar_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE families (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE household_memberships (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('INSERT INTO families VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            constraints = {row['name'] for row in sa.inspect(connection).get_check_constraints('calendar_events')}
            expected = {constraint.name for constraint in CalendarEvent.__table__.constraints if isinstance(constraint, sa.CheckConstraint)}
            assert constraints == expected
            connection.execute(sa.text(
                "INSERT INTO calendar_events (family_id, title, starts_on, ends_on) "
                "VALUES (1, 'Event', '2026-11-10', '2026-11-10')"
            ))
            assert connection.execute(sa.text('SELECT visibility FROM calendar_events')).scalar_one() == 'shared'
            migration.downgrade()
            assert 'calendar_events' not in sa.inspect(connection).get_table_names()
            migration.upgrade()
            assert connection.execute(sa.text('SELECT id FROM families')).scalar_one() == 1
    engine.dispose()
