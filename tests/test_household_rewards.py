import importlib.util
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import g
from flask_login import login_user
from sqlalchemy.exc import OperationalError

from extensions import db, limiter
from models import Family, HouseholdMembership, HouseholdTask, Reward, RewardGoal, RewardJob, RewardPointEntry, RewardRequest, TaskList, User
from services.household.calendar_service import LONDON
from services.household.reward_service import RewardService
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
    g.pop('_login_user', None)
    client = app.test_client()
    login_client(client, actor.id)
    return client


def act(app, actor, operation, **data):
    return client_for(app, actor).post(f'/household/rewards/actions/{operation}', data=data)


@pytest.fixture
def people(user, family):
    rows = []
    for name, kind in [('Adult', 'adult'), ('Child', 'child'), ('Sibling', 'child')]:
        member = User(
            family_id=family.id, role='member', name=name, email=f'{name.lower()}@example.com',
            password_hash=user.password_hash, account_type=kind,
            guardian_id=user.id if kind == 'child' else None, allowed_sections='[]',
        )
        db.session.add(member)
        db.session.flush()
        rows.append(member)
    db.session.commit()
    for member in rows:
        member.get_active_household_membership().allowed_modules = ['household']
    db.session.commit()
    return rows


def job_for(app, adult, child, **changes):
    response = act(
        app, adult, 'create-job', title='Feed the cat', reward_points='20',
        assigned_membership_id=child.get_active_household_membership().id, **changes,
    )
    assert response.status_code == 302, response.data
    return RewardJob.query.order_by(RewardJob.id.desc()).first()


def reward_for(app, adult, cost=10):
    response = act(app, adult, 'save-reward', title='Movie night', description='Pick a film together', points_cost=str(cost))
    assert response.status_code == 302, response.data
    return Reward.query.order_by(Reward.id.desc()).first()


def earn(app, adult, child):
    job = job_for(app, adult, child)
    assert act(app, child, 'submit-job', job_id=job.id).status_code == 302
    assert act(app, adult, 'review-job', job_id=job.id, action='approve').status_code == 302
    return job


def test_reward_overview_is_default_and_reward_focused(app, user, people):
    adult, child, _ = people
    reward = reward_for(app, adult)
    act(app, child, 'goal', reward_id=reward.id)
    html = client_for(app, child).get('/household/rewards').get_data(as_text=True)
    assert 'Your reward journey' in html and 'Saving for Movie night' in html
    assert "Look how far you've come" in html
    assert 'Something to aim for' in html
    assert 'Weekly household leaderboard' not in html
    assert 'Adult setup' not in html
    html = client_for(app, adult).get('/household/rewards').get_data(as_text=True)
    assert 'Little efforts. Proud moments.' in html
    assert "This week's helping hands" in html
    assert 'Sharing with children is off.' in html
    assert 'id="job_title"' not in html


def test_board_is_opt_in_and_revocable_without_exposing_private_details(app, user, family, people):
    adult, child, sibling = people
    earn(app, adult, sibling)
    reward = reward_for(app, adult)
    act(app, sibling, 'goal', reward_id=reward.id)
    act(app, sibling, 'request', reward_id=reward.id, request_key=str(uuid4()))
    assert not family.rewards_board_enabled
    with app.test_request_context():
        login_user(child)
        context = RewardService.page_data('home')
        assert [card['name'] for card in context['celebration']] == ['Child']
    assert act(app, adult, 'set-board', enabled='yes', family_id='999').status_code == 302
    assert family.rewards_board_enabled
    with app.test_request_context():
        login_user(child)
        context = RewardService.page_data('home')
        sibling_card = next(card for card in context['celebration'] if card['name'] == 'Sibling')
        assert sibling_card['earned'] == 20 and sibling_card['jobs'] == 1
        assert set(sibling_card) == {
            'name', 'is_you', 'earned', 'jobs', 'milestones', 'week_points', 'week_jobs', 'rank',
        }
        assert context['balance'] == 0 and context['goal'] is None
        assert context['entries'] == [] and context['requests'] == []
        assert family_query(RewardJob).count() == 0
    html = client_for(app, child).get('/household/rewards').get_data(as_text=True)
    assert 'Weekly household leaderboard' in html and 'Sibling' in html
    assert 'Feed the cat' not in html
    assert act(app, adult, 'set-board', enabled='no').status_code == 302
    with app.test_request_context():
        login_user(child)
        assert [card['name'] for card in RewardService.page_data('home')['celebration']] == ['Child']


def test_milestones_use_all_earned_points_not_spendable_balance_or_history_limit(app, user, people):
    _, child, _ = people
    job = earn(app, user, child)
    member = child.get_active_household_membership()
    # Multiple historical awards exercise the aggregate independently of the 100-row UI history.
    for index in range(100):
        db.session.add(RewardPointEntry(
            family_id=member.family_id, membership_id=member.id, kind='earned',
            points=1, description=f'Historical approved job {index}', created_at=datetime.now(),
        ))
    db.session.commit()
    reward = reward_for(app, user, cost=100)
    act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4()))
    with app.test_request_context():
        login_user(child)
        context = RewardService.page_data('home')
        assert context['balance'] == 20
        assert context['personal']['earned'] == 120
        assert context['personal']['jobs'] == 101
        assert all(milestone[2] for milestone in context['personal']['milestones'])
        assert len(context['entries']) == 100
    assert act(app, user, 'review-job', job_id=job.id, action='approve').status_code == 302
    assert RewardPointEntry.query.filter_by(job_id=job.id).count() == 1


def test_board_only_shows_active_children_of_selected_household(app, user, family, people):
    adult, child, sibling = people
    earn(app, adult, sibling)
    sibling.is_active = False
    other_family = Family(name='Other household', rewards_board_enabled=True)
    db.session.add(other_family)
    db.session.flush()
    outsider = User(family_id=other_family.id, role='member', name='Never on this board',
                    email='other-child@example.com', password_hash=user.password_hash,
                    account_type='child', guardian_id=user.id)
    db.session.add(outsider)
    db.session.commit()
    act(app, adult, 'set-board', enabled='yes')
    with app.test_request_context():
        login_user(child)
        cards = RewardService.page_data('home')['celebration']
        assert [card['name'] for card in cards] == ['Child']


def test_board_setting_validation_permissions_csrf_and_rollback(app, user, family, people, monkeypatch):
    adult, child, _ = people
    assert act(app, child, 'set-board', enabled='yes').status_code == 403
    child.role = 'admin'
    child.get_active_household_membership().role = 'admin'
    db.session.commit()
    assert act(app, child, 'set-board', enabled='yes').status_code == 403
    response = act(app, adult, 'set-board', enabled='maybe')
    assert response.status_code == 200 and b'alert-danger' in response.data
    assert not family.rewards_board_enabled
    with monkeypatch.context() as patch:
        patch.setitem(app.config, 'WTF_CSRF_ENABLED', True)
        g.pop('csrf_valid', None)
        assert act(app, adult, 'set-board', enabled='yes').status_code == 400
    client = client_for(app, adult)
    with monkeypatch.context() as patch:
        patch.setattr(db.session, 'commit', Mock(side_effect=OperationalError('test', {}, RuntimeError('failed'))))
        response = client.post('/household/rewards/actions/set-board', data={'enabled': 'yes'})
        assert response.status_code == 200 and b'No changes were saved' in response.data
    db.session.expire_all()
    assert not family.rewards_board_enabled
    adult.get_active_household_membership().allowed_modules = []
    db.session.commit()
    assert act(app, adult, 'set-board', enabled='yes').status_code == 403


@pytest.mark.parametrize('now, start, end', [
    (datetime(2026, 3, 29, 12, tzinfo=timezone.utc), datetime(2026, 3, 23), datetime(2026, 3, 29, 23)),
    (datetime(2026, 10, 25, 12, tzinfo=timezone.utc), datetime(2026, 10, 18, 23), datetime(2026, 10, 26)),
    (datetime(2026, 11, 9, 0, tzinfo=timezone.utc), datetime(2026, 11, 9), datetime(2026, 11, 16)),
])
def test_weekly_leaderboard_london_boundaries_ties_and_spending(app, user, family, people, monkeypatch, now, start, end):
    adult, child, sibling = people
    member = child.get_active_household_membership()
    sibling_member = sibling.get_active_household_membership()
    family.rewards_board_enabled = True
    for who, points, timestamp in [
        (member, 500, start - timedelta(seconds=1)),
        (member, 10, start),
        (member, 10, end - timedelta(seconds=1)),
        (member, 500, end),
        (sibling_member, 20, start),
    ]:
        db.session.add(RewardPointEntry(
            family_id=family.id, membership_id=who.id, kind='earned', points=points,
            description='Approved job', created_at=timestamp,
        ))
    db.session.add(RewardPointEntry(
        family_id=family.id, membership_id=member.id, kind='reserved', points=-5,
        description='Reward reservation', created_at=start,
    ))
    db.session.commit()
    clock = Mock(wraps=datetime)
    clock.now.return_value = now.astimezone(LONDON)
    monkeypatch.setattr('services.household.reward_service.datetime', clock)
    with app.test_request_context():
        login_user(child)
        context = RewardService.page_data('home')
        cards = context['celebration']
        assert [card['week_points'] for card in cards] == [20, 20]
        assert [card['rank'] for card in cards] == [1, 1]
        assert [card['week_jobs'] for card in cards] == [2, 1]
        assert context['board_week_start'].weekday() == 0
        assert context['board_week_end'].weekday() == 6
        assert cards[0]['earned'] == 1020


def test_leaderboard_rank_order_uses_earned_weekly_points_not_jobs(app, user, family, people):
    adult, child, sibling = people
    earn(app, adult, child)
    earn(app, adult, sibling)
    earn(app, adult, sibling)
    family.rewards_board_enabled = True
    db.session.commit()
    with app.test_request_context():
        login_user(child)
        cards = RewardService.page_data('home')['celebration']
        assert [card['name'] for card in cards] == ['Sibling', 'Child']
        assert [card['rank'] for card in cards] == [1, 2]
        assert [card['week_points'] for card in cards] == [40, 20]


def test_board_migration_defaults_off_and_round_trips(app):
    path = Path(app.root_path) / 'migrations' / 'versions' / 'a72d09c4e816_add_rewards_celebration_board.py'
    spec = importlib.util.spec_from_file_location('reward_board_schema', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE families (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('INSERT INTO families VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(sa.text('SELECT rewards_board_enabled FROM families')).scalar_one() == 0
            connection.execute(sa.text('INSERT INTO families (id) VALUES (2)'))
            assert connection.execute(sa.text('SELECT SUM(rewards_board_enabled) FROM families')).scalar_one() == 0
            migration.downgrade()
            assert 'rewards_board_enabled' not in {col['name'] for col in sa.inspect(connection).get_columns('families')}
            migration.upgrade()
    engine.dispose()


def test_empty_pages_do_not_mutate_and_child_has_simple_journey(app, user, people):
    adult, child, _ = people
    for actor in (adult, child):
        client = client_for(app, actor)
        for view in ('jobs', 'shop', 'progress'):
            response = client.get('/household/rewards', query_string={'view': view})
            assert response.status_code == 200
        assert RewardJob.query.count() == 0 and TaskList.query.count() == 0
    response = client_for(app, child).get('/household/rewards')
    assert b'My jobs' in response.data and b'My rewards' in response.data and b'My progress' in response.data
    assert b'Adult setup' not in response.data and b'Add a reward job' not in response.data
    assert client_for(app, child).get('/household/rewards?view=manage').status_code == 403
    assert client_for(app, adult).get('/household/rewards').status_code == 200
    assert client_for(app, adult).get('/finance/dashboard').status_code == 403
    assert client_for(app, adult).get('/household/rewards?view=nonsense').status_code == 302


def test_job_uses_shared_task_and_child_submission_needs_adult_approval(app, user, family, people):
    adult, child, sibling = people
    job = job_for(app, adult, child)
    assert job.task.task_list.visibility == 'shared'
    assert f'<option value="{job.task.list_id}" selected>'.encode() in client_for(app, adult).get('/household/rewards?view=manage').data
    assert job.family_id == family.id and job.task.family_id == family.id
    assert job.task.creator_membership_id == adult.get_active_household_membership().id
    assert act(app, sibling, 'submit-job', job_id=job.id).status_code == 404
    assert act(app, adult, 'submit-job', job_id=job.id).status_code == 403
    assert act(app, child, 'submit-job', job_id=job.id).status_code == 302
    assert job.state == 'submitted' and job.task.completed
    assert RewardPointEntry.query.count() == 0
    assert b'Waiting for an adult' in client_for(app, child).get('/household/rewards').data
    assert act(app, child, 'review-job', job_id=job.id, action='approve').status_code == 403
    assert act(app, user, 'review-job', job_id=job.id, action='approve').status_code == 302
    entry = RewardPointEntry.query.one()
    assert job.state == 'approved' and entry.points == 20
    assert entry.membership_id == child.get_active_household_membership().id
    assert entry.actor_membership_id == user.get_active_household_membership().id
    assert b'Feed the cat' not in client_for(app, child).get('/household/rewards?view=jobs').data
    assert b'Feed the cat' in client_for(app, child).get('/household/rewards?view=progress').data


def test_duplicate_actions_reopening_and_resubmission_never_double_award(app, user, people):
    _, child, _ = people
    job = earn(app, user, child)
    timestamp = RewardPointEntry.query.one().created_at
    for _ in range(2):
        act(app, user, 'review-job', job_id=job.id, action='approve')
        act(app, child, 'submit-job', job_id=job.id)
    client = client_for(app, child)
    client.post(f'/household/tasks/{job.task_id}/completion', data={'action': 'reopen'})
    assert not job.task.completed and job.state == 'approved'
    client.post(f'/household/tasks/{job.task_id}/completion', data={'action': 'complete'})
    assert job.state == 'approved'
    assert RewardPointEntry.query.count() == 1 and RewardPointEntry.query.one().created_at == timestamp


def test_send_back_requires_note_then_child_can_try_again_and_close_clears_old_work(app, user, people):
    _, child, _ = people
    yesterday = (datetime.now(LONDON).date() - timedelta(days=1)).isoformat()
    job = job_for(app, user, child, due_date=yesterday)
    response = client_for(app, child).get('/household/rewards?view=jobs')
    assert b'Earlier jobs (1)' in response.data and b'Overdue' not in response.data
    act(app, child, 'submit-job', job_id=job.id)
    response = act(app, user, 'review-job', job_id=job.id, action='return')
    assert response.status_code == 200 and b'helpful note' in response.data
    assert job.state == 'submitted'
    act(app, user, 'review-job', job_id=job.id, action='return', note='Please fill the water bowl too')
    assert job.state == 'open' and not job.task.completed
    assert b'Please fill the water bowl too' in client_for(app, child).get('/household/rewards?view=jobs').data
    act(app, user, 'review-job', job_id=job.id, action='close')
    assert job.state == 'closed' and job.task.completed
    assert b'Feed the cat' not in client_for(app, child).get('/household/rewards').data
    assert RewardPointEntry.query.count() == 0


def test_attach_existing_shared_task_ordinary_and_private_tasks_stay_separate(app, user, people):
    _, child, sibling = people
    with app.test_request_context():
        login_user(user)
        shared = TaskService.create_list({'title': 'General', 'visibility': 'shared'})
        task = TaskService.create_task({
            'list_id': shared.id, 'title': 'Tidy books', 'assigned_membership_id': child.get_active_household_membership().id,
        })
    client = client_for(app, user)
    response = client.post(f'/household/tasks/{task.id}', data={
        'title': task.title, 'assigned_membership_id': task.assigned_membership_id, 'reward_points': '15',
    })
    assert response.status_code == 302 and task.reward_job.points == 15
    job = task.reward_job
    client.post(f'/household/tasks/{task.id}', data={
        'title': task.title, 'assigned_membership_id': sibling.get_active_household_membership().id,
    })
    assert task.assigned_membership_id == child.get_active_household_membership().id
    assert b'Close the reward job' in client.post(f'/household/tasks/{task.id}', data={
        'title': task.title, 'assigned_membership_id': sibling.get_active_household_membership().id,
    }).data
    assert client_for(app, child).post(f'/household/tasks/{task.id}/completion', data={'action': 'complete'}).status_code == 302
    assert job.state == 'submitted'
    assert b'Points cannot change' in client_for(app, user).post(f'/household/tasks/{task.id}', data={
        'title': task.title, 'assigned_membership_id': task.assigned_membership_id, 'reward_points': '30',
    }).data
    with app.test_request_context():
        login_user(child)
        private = TaskService.create_list({'title': 'Private', 'visibility': 'personal'})
    assert act(app, user, 'create-job', title='Private job', list_id=private.id, reward_points='10',
               assigned_membership_id=child.get_active_household_membership().id).status_code in (200, 404)
    assert RewardJob.query.count() == 1


def test_redemption_reserves_points_and_snapshots_cost_refunds_exactly_once(app, user, people):
    adult, child, _ = people
    earn(app, user, child)
    reward = reward_for(app, user)
    key = str(uuid4())
    response = act(app, child, 'request', reward_id=reward.id, request_key=key)
    assert response.status_code == 302
    request = RewardRequest.query.one()
    assert request.state == 'pending' and request.points_cost == 10
    for _ in range(2):
        assert act(app, child, 'request', reward_id=reward.id, request_key=key).status_code == 302
    assert RewardRequest.query.count() == 1 and RewardPointEntry.query.filter_by(kind='reserved').count() == 1
    assert b'already have a request' in act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4())).data
    act(app, user, 'save-reward', reward_id=reward.id, title='Changed reward', points_cost='30', available='no')
    assert request.title == 'Movie night' and request.points_cost == 10
    assert act(app, adult, 'review-request', request_id=request.id, action='decline').status_code == 200
    act(app, adult, 'review-request', request_id=request.id, action='decline', note='We can do this next weekend')
    act(app, user, 'review-request', request_id=request.id, action='decline', note='Retry')
    assert request.state == 'declined'
    assert RewardPointEntry.query.filter_by(kind='returned').count() == 1
    with app.test_request_context():
        login_user(child)
        assert RewardService.balance(child.get_active_household_membership().id) == 20
    assert act(app, user, 'review-request', request_id=request.id, action='approve').status_code == 200
    assert request.state == 'declined'


def test_insufficient_points_pause_and_approved_request_cannot_be_refunded(app, user, people):
    _, child, _ = people
    reward = reward_for(app, user, cost=15)
    assert b'need more points' in act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4())).data
    earn(app, user, child)
    assert b'Refresh' in act(app, child, 'request', reward_id=reward.id, request_key='bad').data
    act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4()))
    request = RewardRequest.query.one()
    act(app, user, 'review-request', request_id=request.id, action='approve')
    act(app, user, 'review-request', request_id=request.id, action='approve')
    act(app, user, 'review-request', request_id=request.id, action='decline', note='Try to refund twice')
    assert request.state == 'approved' and RewardPointEntry.query.count() == 2
    act(app, user, 'save-reward', reward_id=reward.id, title=reward.title, points_cost=15, available='no')
    assert b'taking a break' in act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4())).data


def test_invalid_reward_edit_keeps_details_expanded_and_input(app, user, people):
    reward = reward_for(app, user)
    response = act(app, user, 'save-reward', reward_id=reward.id, title='Keep my edit', points_cost='0')
    assert response.status_code == 200 and b'Keep my edit' in response.data
    assert b'<details class="card mb-3" open><summary class="card-header">Manage existing rewards' in response.data
    assert reward.title == 'Movie night' and reward.points_cost == 10


def test_child_only_own_progress_goal_and_no_sibling_or_guardian_bypass(app, user, people):
    adult, child, sibling = people
    job = earn(app, user, child)
    reward = reward_for(app, user)
    act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4()))
    request = RewardRequest.query.one()
    act(app, child, 'goal', reward_id=reward.id)
    assert RewardGoal.query.one().reward_id == reward.id
    response = client_for(app, child).get('/household/rewards?view=progress')
    assert b'My goal: Movie night' in response.data
    response = client_for(app, sibling).get('/household/rewards?view=progress')
    assert b'Feed the cat' not in response.data and b'Waiting for an adult' not in response.data
    assert act(app, sibling, 'review-request', request_id=request.id, action='approve').status_code == 403
    with app.test_request_context():
        login_user(sibling)
        for model in (RewardPointEntry, RewardRequest, RewardJob, RewardGoal):
            assert family_query(model).count() == 0
    act(app, child, 'goal')
    assert RewardGoal.query.one().reward_id is None
    assert act(app, adult, 'goal', reward_id=reward.id).status_code == 403
    assert job.state == 'approved'


@pytest.mark.parametrize('action,data', [
    ('create-job', {'title': 'Try', 'reward_points': '10'}),
    ('save-reward', {'title': 'Try', 'points_cost': '10'}),
    ('review-job', {'job_id': '1', 'action': 'approve'}),
    ('review-request', {'request_id': '1', 'action': 'approve'}),
])
def test_child_even_with_corrupt_owner_role_cannot_manage(app, user, people, action, data):
    _, child, _ = people
    child.role = 'admin'
    child.get_active_household_membership().role = 'admin'
    db.session.commit()
    assert act(app, child, action, **data).status_code == 403


@pytest.mark.parametrize('points', ['0', '-1', '1001', '2.5', 'bad', ''])
def test_invalid_job_points_preserve_form_and_do_not_create_list_or_task(app, user, people, points):
    _, child, _ = people
    response = act(app, user, 'create-job', title='Kept title', reward_points=points,
                   assigned_membership_id=child.get_active_household_membership().id)
    assert response.status_code == 200 and b'Kept title' in response.data
    assert TaskList.query.count() == 0 and HouseholdTask.query.count() == 0 and RewardJob.query.count() == 0


def test_active_household_scoping_foreign_ids_and_write_guard(app, user, family, people):
    adult, child, _ = people
    job = job_for(app, user, child)
    reward = reward_for(app, user)
    foreign = Family(name='Other')
    db.session.add(foreign)
    db.session.flush()
    outsider = User(name='Outsider', email='outsider@example.com', family_id=foreign.id, password_hash=user.password_hash)
    db.session.add(outsider)
    db.session.commit()
    foreign_reward = Reward(family_id=foreign.id, title='SECRET', points_cost=1)
    foreign_job = RewardJob(family_id=foreign.id, title='SECRET JOB', points=1)
    foreign_request = RewardRequest(family_id=foreign.id, title='SECRET', points_cost=1,
                                    request_key=str(uuid4()), created_at=datetime.now())
    db.session.add_all([foreign_reward, foreign_job, foreign_request])
    db.session.commit()
    for action, data in [
        ('review-job', {'job_id': foreign_job.id, 'action': 'approve'}),
        ('review-request', {'request_id': foreign_request.id, 'action': 'approve'}),
        ('save-reward', {'reward_id': foreign_reward.id, 'title': 'Try', 'points_cost': 1}),
    ]:
        assert act(app, adult, action, **data).status_code == 404
    assert act(app, child, 'request', reward_id=foreign_reward.id, request_key=str(uuid4())).status_code == 404
    assert act(app, child, 'goal', reward_id=foreign_reward.id).status_code == 404
    assert b'SECRET' not in client_for(app, user).get('/household/rewards?view=progress').data
    assert b'active child' in act(app, adult, 'create-job', title='Try', reward_points='10',
                                assigned_membership_id=outsider.get_active_household_membership().id).data
    with app.test_request_context():
        login_user(user)
        db.session.add(RewardGoal(family_id=family.id, reward_id=foreign_reward.id))
        with pytest.raises(CrossFamilyReferenceError):
            db.session.commit()
        db.session.rollback()
    assert reward.title == 'Movie night' and job.state == 'open'


@pytest.mark.parametrize('kind', ['task', 'list'])
def test_deleting_task_or_list_preserves_reward_audit_and_closes_unfinished(app, user, people, kind):
    _, child, _ = people
    job = earn(app, user, child)
    unfinished = job_for(app, user, child, list_id=job.task.list_id)
    client = client_for(app, user)
    if kind == 'task':
        client.post(f'/household/tasks/{job.task_id}/delete')
        client.post(f'/household/tasks/{unfinished.task_id}/delete')
    else:
        client.post(f'/household/tasks/lists/{job.task.list_id}/delete')
    db.session.expire_all()
    assert job.task_id is None and unfinished.task_id is None
    assert job.state == 'approved' and unfinished.state == 'closed'
    assert RewardPointEntry.query.one().points == 20


def test_member_departure_clears_private_progress_and_pending_requests(app, user, family, people):
    from services.household.family_service import FamilyService
    _, child, sibling = people
    earn(app, user, child)
    pending_job = job_for(app, user, child)
    reward = reward_for(app, user)
    act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4()))
    act(app, child, 'goal', reward_id=reward.id)
    member_id = child.get_active_household_membership().id
    with app.test_request_context():
        login_user(user)
        FamilyService.remove_member(child.id, family.id, user.id)
    db.session.expire_all()
    assert pending_job.state == 'closed' and pending_job.membership_id is None
    assert RewardRequest.query.one().state == 'declined'
    assert all(row.membership_id is None for row in RewardPointEntry.query.all())
    assert RewardGoal.query.one().membership_id is None
    db.session.add(HouseholdMembership(id=member_id, family_id=family.id, user_id=child.id, role='member', allowed_modules=['household']))
    db.session.commit()
    with app.test_request_context():
        login_user(child)
        assert RewardService.balance(member_id) == 0
        assert family_query(RewardJob).count() == 0


def test_selected_household_not_legacy_default_controls_new_rewards(app, user, family, people):
    _, child, _ = people
    old_job = job_for(app, user, child)
    other = Family(name='Second household')
    db.session.add(other)
    db.session.flush()
    adult_membership = HouseholdMembership(user_id=user.id, family_id=other.id, role='member', allowed_modules=['household'])
    child_membership = HouseholdMembership(user_id=child.id, family_id=other.id, role='member', allowed_modules=['household'])
    db.session.add_all([adult_membership, child_membership])
    db.session.commit()
    client = client_for(app, user)
    assert client.post('/central/family/select', data={'family_id': other.id}).status_code == 302
    response = client.post('/household/rewards/actions/create-job', data={
        'title': 'Second home job', 'assigned_membership_id': child_membership.id,
        'reward_points': '5', 'family_id': family.id, 'creator_membership_id': 999999,
    })
    assert response.status_code == 302
    new_job = RewardJob.query.filter_by(family_id=other.id).one()
    assert new_job.task.creator_membership_id == adult_membership.id
    assert user.family_id == family.id
    assert client.post('/household/rewards/actions/review-job', data={
        'job_id': old_job.id, 'action': 'close',
    }).status_code == 404
    assert old_job.state == 'open'


def test_account_deletion_closes_departed_jobs_preserves_anonymous_audit(app, user, people):
    _, child, _ = people
    earn(app, user, child)
    open_job = job_for(app, user, child)
    reward = reward_for(app, user)
    act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4()))
    # Released child accounts can later choose account deletion.
    child.account_type = 'adult'
    child.guardian_id = None
    db.session.commit()
    response = client_for(app, child).post('/central/account/security/delete', data={
        'password': 'TestPass1!', 'confirmation': 'DELETE MY ACCOUNT',
    })
    assert response.location.endswith('/login')
    db.session.expire_all()
    assert open_job.state == 'closed' and open_job.membership_id is None
    assert RewardRequest.query.one().state == 'declined'
    assert all(row.membership_id is None for row in RewardPointEntry.query.all())
    assert RewardPointEntry.query.filter_by(kind='returned').count() == 1


@pytest.mark.parametrize('action', ['create-job', 'save-reward', 'submit-job', 'review-job', 'request', 'review-request', 'goal'])
def test_commit_failure_rolls_back_explicitly(app, user, people, monkeypatch, action):
    _, child, _ = people
    job = job_for(app, user, child)
    reward = reward_for(app, user)
    if action in ('review-job', 'request', 'review-request'):
        act(app, child, 'submit-job', job_id=job.id)
    if action in ('request', 'review-request'):
        act(app, user, 'review-job', job_id=job.id, action='approve')
    if action == 'review-request':
        act(app, child, 'request', reward_id=reward.id, request_key=str(uuid4()))
    request = RewardRequest.query.first()
    before = {model: model.query.count() for model in (HouseholdTask, TaskList, RewardJob, RewardPointEntry, RewardRequest, Reward, RewardGoal)}
    data = {
        'title': 'Changed', 'assigned_membership_id': child.get_active_household_membership().id,
        'reward_points': '10', 'points_cost': '5', 'job_id': job.id,
        'reward_id': reward.id, 'request_id': request.id if request else '',
        'request_key': str(uuid4()), 'action': 'approve',
    }
    actor = child if action in ('submit-job', 'request', 'goal') else user
    client = client_for(app, actor)
    monkeypatch.setattr(db.session, 'commit', Mock(side_effect=OperationalError('test', {}, RuntimeError('failed'))))
    response = client.post(f'/household/rewards/actions/{action}', data=data)
    assert response.status_code == 200 and b'No changes were saved' in response.data
    assert before == {model: model.query.count() for model in before}
    assert db.session.get(RewardJob, job.id).state != 'approved' or action in ('request', 'review-request')


def test_module_gate_and_post_csrf(app, user, people):
    _, child, _ = people
    membership = child.get_active_household_membership()
    membership.allowed_modules = []
    db.session.commit()
    client = client_for(app, child)
    assert client.get('/household/rewards').status_code == 403
    assert client.post('/household/rewards/actions/goal').status_code == 403
    app.config['WTF_CSRF_ENABLED'] = True
    try:
        assert client_for(app, user).post('/household/rewards/actions/save-reward').status_code == 400
    finally:
        app.config['WTF_CSRF_ENABLED'] = False
    assert client_for(app, user).get('/household/rewards/actions/save-reward').status_code == 405


def test_reward_migration_round_trip_matches_models(app):
    path = Path(app.root_path) / 'migrations' / 'versions' / 'c27d3f9b456a_add_household_rewards.py'
    spec = importlib.util.spec_from_file_location('reward_schema', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('PRAGMA foreign_keys=ON'))
        for table in ('families', 'household_memberships', 'household_tasks'):
            connection.execute(sa.text(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            for model in (Reward, RewardJob, RewardPointEntry, RewardRequest, RewardGoal):
                inspector = sa.inspect(connection)
                assert {row['name'] for row in inspector.get_check_constraints(model.__tablename__)} == {
                    row.name for row in model.__table__.constraints if isinstance(row, sa.CheckConstraint)
                }
                assert {row['name'] for row in inspector.get_unique_constraints(model.__tablename__)} == {
                    row.name for row in model.__table__.constraints if isinstance(row, sa.UniqueConstraint)
                }
            assert connection.execute(sa.text('PRAGMA foreign_key_check')).all() == []
            migration.downgrade()
            assert 'reward_jobs' not in sa.inspect(connection).get_table_names()
            migration.upgrade()
    engine.dispose()


@pytest.mark.parametrize('operation', ['approve', 'request'])
def test_concurrent_reviews_award_once_and_requests_cannot_overspend(app, user, tmp_path, monkeypatch, operation):
    from app import create_app
    from config import TestingConfig
    monkeypatch.setattr(TestingConfig, 'SQLALCHEMY_DATABASE_URI', f'sqlite:///{tmp_path / "rewards.db"}')
    password_hash = user.password_hash
    isolated = create_app('testing')
    with isolated.app_context():
        db.create_all()
        family = Family(name='Concurrent rewards')
        db.session.add(family)
        db.session.flush()
        adult = User(name='Adult', email='concurrent-adult@example.com', family_id=family.id,
                     role='admin', password_hash=password_hash)
        db.session.add(adult)
        db.session.flush()
        child = User(name='Child', email='concurrent-child@example.com', family_id=family.id,
                     account_type='child', guardian_id=adult.id, password_hash=password_hash)
        db.session.add(child)
        db.session.commit()
        adult_id, child_id = adult.id, child.id
        member_id = child.get_active_household_membership().id
        with isolated.test_request_context():
            login_user(adult)
            task = RewardService.create_job({'title': 'Job', 'assigned_membership_id': member_id, 'reward_points': '20'})
            job_id = task.reward_job.id
        with isolated.test_request_context():
            login_user(child)
            RewardService.submit_job(job_id, {})
        reward_ids = []
        with isolated.test_request_context():
            login_user(adult)
            if operation == 'request':
                RewardService.review_job(job_id, {'action': 'approve'})
                for title in ('First reward', 'Second reward'):
                    reward_ids.append(RewardService.save_reward({'title': title, 'points_cost': '15'}).id)
        db.session.remove()
    barrier = Barrier(2)

    def worker(index):
        with isolated.test_request_context():
            login_user(db.session.get(User, adult_id if operation == 'approve' else child_id))
            barrier.wait(timeout=10)
            try:
                if operation == 'approve':
                    RewardService.review_job(job_id, {'action': 'approve'})
                else:
                    RewardService.request_reward(reward_ids[index], {'request_key': str(uuid4())})
                db.session.commit()
                return 'saved'
            except ValueError as error:
                db.session.rollback()
                return str(error)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, range(2)))
        with isolated.app_context(), isolated.test_request_context():
            login_user(db.session.get(User, adult_id))
            assert RewardPointEntry.query.filter_by(kind='earned').count() == 1
            if operation == 'approve':
                assert results == ['saved', 'saved']
            else:
                assert results.count('saved') == 1
                assert RewardRequest.query.count() == 1
                assert RewardService.balance(member_id) == 5
    finally:
        with isolated.app_context():
            db.session.remove()
            db.engine.dispose()
