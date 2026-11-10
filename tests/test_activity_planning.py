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

from extensions import db, limiter
from models import Activity, ActivityAttendee, CalendarEvent, Family, HouseholdMembership, User
from services.household.activity_service import ActivityService
from services.household.calendar_service import CalendarService
from tests.auth_helpers import login_client
from utils.db_helpers import family_query
from utils.tenancy_guard import CrossFamilyReferenceError


CONTENT = {
    'title': 'Park visit', 'description': 'Bring a picnic', 'comments': 'Check the forecast',
    'location': 'Local park', 'all_day': 'on', 'starts_on': '2026-11-10', 'ends_on': '2026-11-10',
    'recurrence': 'none',
}


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


def create(app, actor, **changes):
    with app.test_request_context():
        login_user(actor)
        return ActivityService.create({**CONTENT, **changes})


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


def test_adult_without_finance_access_publishes_with_attendees_and_feed(app, user, people):
    adult, child, _ = people
    member = child.get_active_household_membership()
    client = client_for(app, adult)
    response = client.post('/household/activities/new', data={
        **CONTENT, 'attendee_ids': [str(member.id), str(member.id)], 'view': 'month',
        'family_id': '99999', 'creator_membership_id': user.get_active_household_membership().id,
    })
    assert response.status_code == 302 and response.location.endswith('view=month')
    activity = Activity.query.one()
    assert activity.status == 'approved' and activity.family_id == adult.family_id
    assert activity.creator_membership_id == adult.get_active_household_membership().id
    assert activity.reviewer_membership_id == activity.creator_membership_id
    assert activity.reviewed_at is not None
    assert len(activity.attendees) == 1 and activity.attendees[0].family_id == activity.family_id
    assert client.get('/finance/dashboard').status_code == 403
    for path in (
        '/household/activities?week=2026-11-10',
        '/household/activities?view=month&month=2026-11',
        '/household/?month=2026-11', '/household/?view=agenda&month=2026-11',
    ):
        response = client.get(path)
        assert response.status_code == 200 and b'Park visit' in response.data
        assert f'/household/activities/{activity.id}'.encode() in response.data
    assert b'Added by Adult' in client.get(f'/household/activities/{activity.id}').data
    assert CalendarEvent.query.count() == 0


def test_child_suggestions_private_until_adult_approval_then_read_only(app, user, people):
    adult, child, sibling = people
    child_client = client_for(app, child)
    response = child_client.post('/household/activities/new', data={
        **CONTENT, 'title': 'Child idea', 'status': 'approved',
        'reviewer_membership_id': user.get_active_household_membership().id,
        'attendee_ids': [child.get_active_household_membership().id],
    })
    activity = Activity.query.one()
    assert response.status_code == 302 and activity.status == 'pending'
    assert activity.reviewer_membership_id is None and activity.reviewed_at is None
    assert b'Child idea' in child_client.get('/household/activities').data
    assert b'Child idea' not in child_client.get('/household/?month=2026-11').data
    sibling_client = client_for(app, sibling)
    assert sibling_client.get(f'/household/activities/{activity.id}').status_code == 404
    assert b'Child idea' not in sibling_client.get('/household/activities').data
    with app.test_request_context():
        login_user(sibling)
        assert family_query(Activity).count() == 0
        assert family_query(ActivityAttendee).count() == 0
    for path in (f'/household/activities/{activity.id}/review',):
        g.pop('_login_user', None)
        assert child_client.post(path, data={'decision': 'approve'}).status_code == 403
    adult_client = client_for(app, adult)
    assert b'Child idea' in adult_client.get('/household/activities').data
    response = adult_client.post(f'/household/activities/{activity.id}/review', data={'decision': 'approve', 'view': 'month'})
    assert response.status_code == 302 and response.location.endswith('view=month')
    assert activity.status == 'approved' and activity.reviewer_membership_id == adult.get_active_household_membership().id
    g.pop('_login_user', None)
    assert b'Child idea' in sibling_client.get('/household/?month=2026-11').data
    g.pop('_login_user', None)
    assert b'Bring a picnic' in child_client.get(f'/household/activities/{activity.id}').data
    assert child_client.post(f'/household/activities/{activity.id}', data=CONTENT).status_code == 403
    assert child_client.post(f'/household/activities/{activity.id}/delete').status_code == 403
    assert Activity.query.count() == 1


def test_rejected_suggestion_can_be_revised_and_resubmitted_by_creator_only(app, user, people):
    adult, child, sibling = people
    activity = create(app, child)
    adult_client = client_for(app, adult)
    adult_client.post(f'/household/activities/{activity.id}/review', data={'decision': 'reject'})
    assert activity.status == 'rejected'
    assert client_for(app, sibling).post(f'/household/activities/{activity.id}', data=CONTENT).status_code == 404
    child_client = client_for(app, child)
    response = child_client.post(f'/household/activities/{activity.id}', data={**CONTENT, 'title': 'Revised idea'})
    assert response.status_code == 302 and activity.status == 'pending'
    assert activity.reviewed_at is None and activity.reviewer_membership_id is None
    assert activity.title == 'Revised idea'
    assert child_client.post(f'/household/activities/{activity.id}/delete').status_code == 302
    assert Activity.query.count() == 0


def test_adult_edit_of_pending_suggestion_does_not_publish_without_review(app, user, people):
    _, child, _ = people
    activity = create(app, child)
    response = client_for(app, user).post(f'/household/activities/{activity.id}', data={**CONTENT, 'title': 'Adult adjusted'})
    assert response.status_code == 302 and activity.status == 'pending'
    assert activity.creator_membership_id == child.get_active_household_membership().id
    assert b'Adult adjusted' not in client_for(app, user).get('/household/?month=2026-11').data


def test_child_owner_corruption_cannot_publish_or_manage_other_activity(app, user, people):
    _, child, _ = people
    child.role = 'admin'
    child.get_active_household_membership().role = 'admin'
    db.session.commit()
    activity = create(app, child, status='approved')
    assert activity.status == 'pending'
    published = create(app, user)
    client = client_for(app, child)
    assert client.post(f'/household/activities/{published.id}', data=CONTENT).status_code == 403
    assert client.post(f'/household/activities/{activity.id}/review', data={'decision': 'approve'}).status_code == 403


def test_weekly_recurrence_keeps_london_time_across_dst_and_ends_inclusively(app, user):
    activity = create(
        app, user, all_day='', starts_at='2026-03-22T09:00', ends_at='2026-03-22T10:00',
        recurrence='weekly', repeat_until='2026-04-05',
    )
    with app.test_request_context():
        login_user(user)
        rows = ActivityService.between(date(2026, 3, 1), date(2026, 4, 30))
    assert [row.starts_on for row in rows] == [date(2026, 3, 22), date(2026, 3, 29), date(2026, 4, 5)]
    assert [row.starts_at.hour for row in rows] == [9, 8, 8]
    assert all(CalendarService.local_time(row.starts_at).hour == 9 for row in rows)
    assert Activity.query.count() == 1 and CalendarEvent.query.count() == 0
    assert activity.repeat_until == date(2026, 4, 5)


def test_multiday_overlapping_repeats_and_midnight_end_boundaries(app, user):
    create(app, user, starts_on='2026-10-25', ends_on='2026-11-04', recurrence='weekly', repeat_until='2026-11-08')
    timed = create(app, user, title='Evening', all_day='', starts_at='2026-11-10T20:00', ends_at='2026-11-11T00:00')
    with app.test_request_context():
        login_user(user)
        context = CalendarService.page_data({'month': '2026-11'})
        assert len(context['activity_days'][date(2026, 11, 3)]) == 2
        assert any(row.activity.id == timed.id for row in context['activity_days'][date(2026, 11, 10)])
        assert not any(row.activity.id == timed.id for row in context['activity_days'][date(2026, 11, 11)])


@pytest.mark.parametrize('changes,message', [
    ({'title': ''}, 'title'),
    ({'title': 'x' * 201}, 'title'),
    ({'comments': 'x' * 5001}, 'comments'),
    ({'description': 'x' * 5001}, 'notes'),
    ({'location': 'x' * 201}, 'location'),
    ({'ends_on': '2026-11-09'}, 'end date'),
    ({'starts_on': 'bad'}, 'valid start'),
    ({'recurrence': 'daily'}, 'weekly'),
    ({'recurrence': 'weekly', 'repeat_until': ''}, 'valid activity date'),
    ({'recurrence': 'weekly', 'repeat_until': '2026-11-09'}, 'repeat end'),
    ({'recurrence': 'weekly', 'repeat_until': '2101-01-01'}, 'between 1900'),
    ({'all_day': '', 'starts_at': '2026-03-22T01:30', 'ends_at': '2026-03-22T02:30',
      'recurrence': 'weekly', 'repeat_until': '2026-03-29'}, 'does not exist'),
    ({'all_day': '', 'starts_at': '2026-10-18T01:30', 'ends_at': '2026-10-18T02:30',
      'recurrence': 'weekly', 'repeat_until': '2026-10-25'}, 'occurs twice'),
    ({'starts_on': '2100-12-24', 'ends_on': '2100-12-26',
      'recurrence': 'weekly', 'repeat_until': '2100-12-31'}, 'finish by'),
    ({'attendee_ids': ['bad']}, 'active attendees'),
    ({'attendee_ids': ['99999']}, 'active attendees'),
    ({'attendee_ids': '1'}, 'household member list'),
])
def test_invalid_activity_does_not_write(app, user, changes, message):
    with pytest.raises(ValueError, match=message):
        create(app, user, **changes)
    assert Activity.query.count() == 0 and ActivityAttendee.query.count() == 0


def test_active_household_and_foreign_attendee_ids_are_scoped(app, user, family):
    original = create(app, user)
    other = Family(name='Other household')
    db.session.add(other)
    db.session.flush()
    member = HouseholdMembership(user_id=user.id, family_id=other.id, role='member', allowed_modules=['household'])
    db.session.add(member)
    db.session.commit()
    client = client_for(app, user)
    response = client.post('/household/activities/new', data={**CONTENT, 'attendee_ids': [member.id]})
    assert b'Choose active attendees from this household' in response.data
    assert Activity.query.count() == 1
    client.post('/central/family/select', data={'family_id': other.id})
    for suffix in ('', '/delete', '/review'):
        path = f'/household/activities/{original.id}' + suffix
        response = client.post(path, data={'decision': 'approve'}) if suffix else client.get(path)
        assert response.status_code == 404
    response = client.post('/household/activities/new', data={
        **CONTENT, 'attendee_ids': [member.id], 'family_id': family.id,
    })
    assert response.status_code == 302
    activity = Activity.query.filter_by(family_id=other.id).one()
    assert activity.creator_membership_id == member.id
    with pytest.raises(CrossFamilyReferenceError):
        db.session.add(ActivityAttendee(family_id=other.id, activity_id=original.id, membership_id=member.id))
        db.session.flush()
    db.session.rollback()


def test_edit_and_delete_change_entire_series_and_preserve_month_view(app, user):
    activity = create(app, user, recurrence='weekly', repeat_until='2026-11-24')
    client = client_for(app, user)
    response = client.post(f'/household/activities/{activity.id}', data={
        **CONTENT, 'title': 'Swimming', 'recurrence': 'weekly', 'repeat_until': '2026-11-17', 'view': 'month',
    })
    assert response.location.endswith('view=month')
    with app.test_request_context():
        login_user(user)
        rows = ActivityService.between(date(2026, 11, 1), date(2026, 11, 30))
        assert len(rows) == 2 and all(row.activity.title == 'Swimming' for row in rows)
    response = client.post(f'/household/activities/{activity.id}/delete', data={'view': 'month'})
    assert response.location.endswith('view=month&month=2026-11')
    assert b'Swimming' not in client.get('/household/?month=2026-11').data
    assert Activity.query.count() == 0


def test_forms_preserve_values_on_validation_error_and_prefill_day(app, user):
    client = client_for(app, user)
    response = client.get('/household/activities/new?date=2026-11-18&view=month')
    assert response.status_code == 200 and response.data.count(b'value="2026-11-18"') == 2
    response = client.post('/household/activities/new', data={
        **CONTENT, 'title': 'Keep this title', 'ends_on': '2026-11-01',
        'comments': 'Keep these notes', 'view': 'month',
        'attendee_ids': [user.get_active_household_membership().id],
    })
    assert b'Keep this title' in response.data and b'Keep these notes' in response.data
    assert b'name="view" value="month"' in response.data
    assert b'name="attendee_ids"' in response.data and b' checked' in response.data
    assert Activity.query.count() == 0
    for query in ('view=bad', 'week=bad', 'view=month&month=2101-01'):
        response = client.get('/household/activities?' + query, follow_redirects=True)
        assert response.status_code == 200 and b'alert-danger' in response.data
    assert b'alert-danger' in client.get('/household/activities/new?date=bad', follow_redirects=True).data
    with app.test_request_context():
        login_user(user)
        context = ActivityService.planner({'view': 'month', 'month': '2026-11'})
        assert context['first'] == date(2026, 10, 26) and context['last'] == date(2026, 12, 6)
        assert ActivityService.planner({'week': '1900-01-01'})['previous'] is None
        assert ActivityService.planner({'view': 'month', 'month': '2100-12'})['following'] is None
        assert ActivityService.planner({'week': '2027-01-01'})['first'] == date(2026, 12, 28)


def test_attendees_can_be_changed_and_mixed_equivalent_ids_are_deduplicated(app, user, people):
    adult, child, _ = people
    member_id = child.get_active_household_membership().id
    activity = create(app, user, attendee_ids=[member_id, str(member_id), '0' + str(member_id)])
    assert len(activity.attendees) == 1
    adult_id = adult.get_active_household_membership().id
    response = client_for(app, user).post(f'/household/activities/{activity.id}', data={
        **CONTENT, 'attendee_ids': [adult_id],
    })
    assert response.status_code == 302
    db.session.expire_all()
    assert [row.membership_id for row in activity.attendees] == [adult_id]
    client_for(app, user).post(f'/household/activities/{activity.id}', data=CONTENT)
    assert ActivityAttendee.query.count() == 0
    child.is_active = False
    db.session.commit()
    with pytest.raises(ValueError, match='active attendees'):
        create(app, user, attendee_ids=[member_id])


def test_invalid_review_and_view_never_change_status_or_create_rows(app, user, people):
    _, child, _ = people
    activity = create(app, child)
    client = client_for(app, user)
    for data in ({'decision': 'publish'}, {'decision': 'approve', 'view': 'bad'}):
        response = client.post(f'/household/activities/{activity.id}/review', data=data, follow_redirects=True)
        assert response.status_code == 200 and b'alert-danger' in response.data
        assert activity.status == 'pending'
    response = client.post('/household/activities/new', data={**CONTENT, 'view': 'bad'})
    assert b'week or month' in response.data and Activity.query.count() == 1
    client.post(f'/household/activities/{activity.id}/review', data={'decision': 'approve'})
    response = client.post(f'/household/activities/{activity.id}/review', data={'decision': 'reject'}, follow_redirects=True)
    assert b'Only pending suggestions' in response.data and activity.status == 'approved'


def test_module_access_required_for_every_activity_surface(app, user, people):
    adult, _, _ = people
    activity = create(app, user)
    adult.get_active_household_membership().allowed_modules = []
    db.session.commit()
    client = client_for(app, adult)
    for path in ('/household/activities', '/household/activities/new', f'/household/activities/{activity.id}'):
        assert client.get(path).status_code == 403
    for path in (
        '/household/activities/new', f'/household/activities/{activity.id}',
        f'/household/activities/{activity.id}/review', f'/household/activities/{activity.id}/delete',
    ):
        assert client.post(path, data=CONTENT).status_code == 403


@pytest.mark.parametrize('operation', ['create', 'update', 'review', 'delete'])
def test_write_failures_rollback_and_report(app, user, people, monkeypatch, operation):
    _, child, _ = people
    activity = create(app, child)
    client = client_for(app, user)
    monkeypatch.setattr(db.session, 'commit', Mock(side_effect=OperationalError('write', {}, Exception('unavailable'))))
    path, data = {
        'create': ('/household/activities/new', CONTENT),
        'update': (f'/household/activities/{activity.id}', {**CONTENT, 'title': 'Changed'}),
        'review': (f'/household/activities/{activity.id}/review', {'decision': 'approve'}),
        'delete': (f'/household/activities/{activity.id}/delete', {}),
    }[operation]
    response = client.post(path, data=data, follow_redirects=True)
    assert response.status_code == 200 and b'No changes were saved.' in response.data
    db.session.expire_all()
    assert Activity.query.count() == 1 and activity.title == CONTENT['title'] and activity.status == 'pending'


def test_csrf_for_every_activity_write_and_get_cannot_delete(app, user, monkeypatch):
    activity = create(app, user)
    client = client_for(app, user)
    monkeypatch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
    g.pop('csrf_valid', None)
    g.pop('csrf_token', None)
    for path in (
        '/household/activities/new', f'/household/activities/{activity.id}',
        f'/household/activities/{activity.id}/review', f'/household/activities/{activity.id}/delete',
    ):
        assert client.post(path, data=CONTENT).status_code == 400
    assert client.get(f'/household/activities/{activity.id}/delete').status_code == 405
    assert Activity.query.count() == 1


def test_member_departure_clears_attribution_and_attendance_without_deleting_series(app, user, family, people):
    from services.household.family_service import FamilyService
    adult, _, _ = people
    member_id = adult.get_active_household_membership().id
    activity = create(app, adult, attendee_ids=[member_id], recurrence='weekly', repeat_until='2026-11-24')
    with app.test_request_context():
        login_user(user)
        FamilyService.remove_member(adult.id, family.id, user.id)
    db.session.expire_all()
    assert Activity.query.count() == 1 and activity.status == 'approved'
    assert activity.creator_membership_id is None and activity.reviewer_membership_id is None
    assert ActivityAttendee.query.count() == 0
    assert b'former member' in client_for(app, user).get(f'/household/activities/{activity.id}').data
    newcomer = User(
        name='New member', email='newcomer@example.com', password_hash=user.password_hash,
    )
    db.session.add(newcomer)
    db.session.flush()
    db.session.add(HouseholdMembership(id=member_id, user_id=newcomer.id, family_id=family.id, role='member'))
    db.session.commit()
    db.session.expire_all()
    assert activity.creator_membership_id is None and activity.reviewer_membership_id is None
    assert ActivityAttendee.query.count() == 0


def test_account_deletion_keeps_series_but_removes_attendance_and_attribution(app, user, people):
    adult, _, _ = people
    activity = create(app, adult, attendee_ids=[adult.get_active_household_membership().id])
    response = client_for(app, adult).post('/central/account/security/delete', data={
        'password': 'TestPass1!', 'confirmation': 'DELETE MY ACCOUNT',
    })
    assert response.location.endswith('/login')
    db.session.expire_all()
    assert Activity.query.count() == 1
    assert activity.creator_membership_id is None and activity.reviewer_membership_id is None
    assert ActivityAttendee.query.count() == 0


@pytest.mark.parametrize('view, query', [
    ('week', 'week=2026-11-10'),
    ('month', 'view=month&month=2026-11'),
])
def test_planner_readable_layout_and_date_navigation(app, user, view, query):
    create(app, user, all_day='', starts_at='2026-11-10T09:00', ends_at='2026-11-10T10:30')
    response = client_for(app, user).get(f'/household/activities?{query}')
    assert response.status_code == 200
    html = response.data.decode()
    assert '09:00 &ndash; 10:30 GMT' in html
    assert 'Local park' in html
    assert 'class="planner-navigation"' in html
    assert f'name="view" value="{view}"' in html
    assert f'Go<span class="visually-hidden"> to {view}</span>' in html
    if view == 'week':
        assert html.count('class="card activity-week-row') == 7
        assert 'aria-labelledby="activity-day-2026-11-10"' in html
        assert 'name="week" value="2026-11-10"' in html
        assert html.count('class="activity-day-action mt-1"') == 7
    else:
        assert 'aria-label="Monthly activity planner"' in html
        assert 'aria-describedby="activity-month-help"' in html
        assert 'name="month" value="2026-11"' in html
        assert 'Scroll sideways' in html


@pytest.mark.parametrize('query, heading', [
    ('week=2026-11-10', '9 &ndash; 15 Nov 2026'),
    ('week=2026-11-30', '30 Nov &ndash; 6 Dec 2026'),
    ('week=2026-12-31', '28 Dec 2026 &ndash; 3 Jan 2027'),
    ('view=month&month=2026-11', 'November 2026'),
])
def test_compact_activity_toolbar_keeps_dates_and_controls_clear(app, user, query, heading):
    from html.parser import HTMLParser

    class JumpParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_details = False
            self.in_form = False
            self.submit_in_disclosure = False

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'details' and attrs.get('class') == 'planner-date-menu':
                self.in_details = True
            if tag == 'form' and attrs.get('class') == 'planner-date-form':
                self.in_form = True
            if tag == 'button' and self.in_form and attrs.get('type') == 'submit':
                self.submit_in_disclosure = self.in_details

        def handle_endtag(self, tag):
            if tag == 'details':
                self.in_details = False
            if tag == 'form':
                self.in_form = False

    html = client_for(app, user).get('/household/activities?' + query).get_data(as_text=True)
    parser = JumpParser()
    parser.feed(html)
    assert parser.submit_in_disclosure
    view = 'month' if 'view=month' in query else 'week'
    assert heading in html
    assert f'aria-label="Previous {view}"' in html
    assert f'aria-label="Next {view}"' in html
    assert '<details class="planner-date-menu">' in html
    assert f'<summary title="Choose another {view}">' in html
    assert ('Choose a month' if view == 'month' else 'Choose any day in the week') in html
    assert 'Week containing' not in html


def test_planner_shows_full_dates_for_overnight_and_all_day_activities(app, user):
    create(app, user, all_day='', starts_at='2026-11-10T23:00', ends_at='2026-11-11T00:00')
    create(app, user, title='Weekend trip', ends_on='2026-11-12')
    html = client_for(app, user).get('/household/activities?week=2026-11-10').data.decode()
    assert '10 Nov 2026, 23:00 &ndash; 11 Nov 2026, 00:00 GMT' in html
    assert '10 Nov 2026 &ndash; 12 Nov 2026' in html


def test_planner_suggestion_guidance_and_child_actions(app, user, people):
    _, child, _ = people
    suggestion = create(app, child, title='Child outing idea')
    child_client = client_for(app, child)
    html = child_client.get('/household/activities?week=2026-11-10').data.decode()
    assert 'Your suggestions' in html and 'Awaiting review' in html
    assert html.count('class="activity-day-action mt-1"') == 7
    assert 'Suggest activity on 2026-11-10' in html
    assert 'until an adult household member approves it' in html
    assert html.count('Child outing idea') == 1
    adult_client = client_for(app, user)
    html = adult_client.get('/household/activities?week=2026-11-10').data.decode()
    assert 'Open a pending suggestion to approve or decline it.' in html
    adult_client.post(f'/household/activities/{suggestion.id}/review', data={'decision': 'reject'})
    html = adult_client.get('/household/activities?week=2026-11-10').data.decode()
    assert 'Not approved' in html and 'Awaiting review' not in html


def test_activity_migration_round_trip_with_foreign_keys(app):
    path = Path(app.root_path) / 'migrations' / 'versions' / 'a05b1d7f234e_add_household_activities.py'
    spec = importlib.util.spec_from_file_location('activity_schema', path)
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
            constraints = {row['name'] for row in sa.inspect(connection).get_check_constraints('activities')}
            assert constraints == {
                row.name for row in Activity.__table__.constraints if isinstance(row, sa.CheckConstraint)
            }
            connection.execute(sa.text(
                "INSERT INTO activities (id,family_id,title,starts_on,ends_on,creator_membership_id) "
                "VALUES (1,1,'Outing','2026-11-10','2026-11-10',1)",
            ))
            connection.execute(sa.text(
                'INSERT INTO activity_attendees (family_id,activity_id,membership_id) VALUES (1,1,1)',
            ))
            assert connection.execute(sa.text('SELECT status FROM activities')).scalar_one() == 'pending'
            connection.execute(sa.text('DELETE FROM household_memberships'))
            assert connection.execute(sa.text('SELECT creator_membership_id FROM activities')).scalar_one() is None
            assert connection.execute(sa.text('SELECT COUNT(*) FROM activity_attendees')).scalar_one() == 0
            assert connection.execute(sa.text('PRAGMA foreign_key_check')).all() == []
            migration.downgrade()
            assert 'activities' not in sa.inspect(connection).get_table_names()
            migration.upgrade()
            assert {'activities', 'activity_attendees'} <= set(sa.inspect(connection).get_table_names())
    engine.dispose()
