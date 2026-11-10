import importlib.util
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask_login import login_user

from extensions import db
from models import Family, HouseholdTask, RewardJob, RewardPointEntry, TaskList
from services.household.task_service import TaskService
from services.household.reward_service import RewardService
from services.household.calendar_service import LONDON
from tests.test_household_rewards import people, client_for


@pytest.fixture
def clock(monkeypatch):
    state = [datetime(2026, 11, 9, 12, tzinfo=timezone.utc)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return state[0].astimezone(tz) if tz else state[0].replace(tzinfo=None)

    monkeypatch.setattr('services.household.task_service.datetime', Clock)
    monkeypatch.setattr('services.household.reward_service.datetime', Clock)
    return state


def create_repeat(app, adult, child, recurrence='daily', policy='skip'):
    with app.test_request_context():
        login_user(adult)
        return RewardService.create_job({
            'title': 'Feed the cat', 'notes': 'Fresh food and water',
            'assigned_membership_id': str(child.get_active_household_membership().id),
            'reward_points': '10', 'due_date': '2026-11-09',
            'recurrence': recurrence, 'missed_policy': policy,
        })


def refresh(app, actor):
    with app.test_request_context():
        login_user(actor)
        TaskService.refresh_recurring()


def test_daily_independent_approvals_and_exactly_once_awards(app, user, people, clock):
    _, child, _ = people
    root = create_repeat(app, user, child)
    client = client_for(app, child)
    assert client.post(f'/household/rewards/actions/submit-job', data={'job_id': root.reward_job.id}).status_code == 302
    clock[0] += timedelta(days=1)
    refresh(app, child)
    next_task = HouseholdTask.query.filter_by(series_id=root.id).one()
    assert root.completed and root.reward_job.state == 'submitted'
    assert next_task.period_start == date(2026, 11, 10)
    assert not next_task.completed and next_task.reward_job.state == 'open'
    client = client_for(app, child)
    assert client.post('/household/rewards/actions/submit-job', data={'job_id': next_task.reward_job.id}).status_code == 302
    adult = client_for(app, user)
    for task in (root, next_task):
        for _ in range(2):
            assert adult.post('/household/rewards/actions/review-job',
                              data={'job_id': task.reward_job.id, 'action': 'approve'}).status_code == 302
    assert RewardPointEntry.query.count() == 2
    assert sum(entry.points for entry in RewardPointEntry.query.all()) == 20
    refresh(app, child)
    assert HouseholdTask.query.count() == 2
    assert RewardJob.query.count() == 2


@pytest.mark.parametrize('policy', ['skip', 'backlog'])
def test_missed_intervals_are_captured_per_task_and_current_is_fresh(app, user, people, clock, policy):
    _, child, _ = people
    root = create_repeat(app, user, child, policy=policy)
    clock[0] += timedelta(days=3)
    refresh(app, child)
    tasks = HouseholdTask.query.order_by(HouseholdTask.due_date).all()
    assert len(tasks) == 4
    assert [task.due_date for task in tasks] == [date(2026, 11, day) for day in range(9, 13)]
    assert [task.expired for task in tasks] == ([True, True, True, False] if policy == 'skip' else [False] * 4)
    assert not any(task.completed for task in tasks)
    assert RewardPointEntry.query.count() == 0
    client = client_for(app, child)
    response = client.post('/household/rewards/actions/submit-job', data={'job_id': root.reward_job.id})
    assert response.status_code == (200 if policy == 'skip' else 302)
    assert root.reward_job.state == ('closed' if policy == 'skip' else 'submitted')
    with app.test_request_context():
        login_user(child)
        hub = TaskService.hub({'list_id': str(root.list_id)})
        assert [task.id for task in hub['tasks']] == ([tasks[-1].id] if policy == 'skip' else [task.id for task in tasks[1:]])
        all_rows = TaskService.hub({'list_id': str(root.list_id), 'filter': 'all'})['tasks']
        assert len(all_rows) == 4


def test_weekly_resets_on_monday_not_seven_days_after_completion(app, user, people, clock):
    _, child, _ = people
    clock[0] = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)
    with app.test_request_context():
        login_user(user)
        root = RewardService.create_job({
            'title': 'Tidy room', 'reward_points': '20',
            'assigned_membership_id': child.get_active_household_membership().id,
            'due_date': '2026-11-11', 'recurrence': 'weekly', 'missed_policy': 'backlog',
        })
    assert root.period_start == date(2026, 11, 9) and root.due_date == date(2026, 11, 15)
    clock[0] = datetime(2026, 11, 15, 23, 59, tzinfo=timezone.utc)
    refresh(app, child)
    assert HouseholdTask.query.count() == 1
    clock[0] = datetime(2026, 11, 16, tzinfo=timezone.utc)
    refresh(app, child)
    occurrence = HouseholdTask.query.filter_by(series_id=root.id).one()
    assert occurrence.period_start == date(2026, 11, 16)
    assert occurrence.due_date == date(2026, 11, 22)


@pytest.mark.parametrize('before, after, start', [
    (datetime(2026, 3, 29, 22, 59, tzinfo=timezone.utc), datetime(2026, 3, 29, 23, tzinfo=timezone.utc), '2026-03-29'),
    (datetime(2026, 10, 25, 23, 59, tzinfo=timezone.utc), datetime(2026, 10, 26, tzinfo=timezone.utc), '2026-10-25'),
])
def test_daily_london_midnight_across_dst(app, user, people, clock, before, after, start):
    _, child, _ = people
    clock[0] = before
    with app.test_request_context():
        login_user(user)
        root = RewardService.create_job({
            'title': 'Daily chore', 'reward_points': '10',
            'assigned_membership_id': child.get_active_household_membership().id,
            'due_date': start, 'recurrence': 'daily',
        })
    refresh(app, child)
    assert HouseholdTask.query.count() == 1
    clock[0] = after
    refresh(app, child)
    assert HouseholdTask.query.count() == 2
    assert HouseholdTask.query.filter_by(series_id=root.id).one().period_start == after.astimezone(LONDON).date()


def test_ordinary_recurring_personal_task_uses_same_privacy_and_history(app, user, people, clock):
    _, child, sibling = people
    with app.test_request_context():
        login_user(child)
        task_list = TaskService.create_list({'title': 'My habits'})
        root = TaskService.create_task({
            'list_id': task_list.id, 'title': 'Read a chapter', 'due_date': '2026-11-09',
            'recurrence': 'daily', 'missed_policy': 'backlog',
        })
    clock[0] += timedelta(days=1)
    refresh(app, sibling)
    assert HouseholdTask.query.count() == 1
    refresh(app, child)
    assert HouseholdTask.query.count() == 2
    assert client_for(app, sibling).get(f'/household/tasks/{root.id}').status_code == 404
    with app.test_request_context():
        login_user(child)
        TaskService.set_completion(root.id, {'action': 'complete'})
    assert root.completed and RewardJob.query.count() == 0


def test_stop_series_keeps_history_and_no_new_occurrences(app, user, people, clock):
    _, child, _ = people
    root = create_repeat(app, user, child)
    clock[0] += timedelta(days=1)
    refresh(app, child)
    with app.test_request_context():
        login_user(user)
        TaskService.update_task(root.id, {
            'recurrence': 'daily', 'missed_policy': 'skip', 'repeat_active': 'no',
        })
    clock[0] += timedelta(days=7)
    refresh(app, child)
    assert HouseholdTask.query.count() == 2
    with app.test_request_context():
        login_user(user)
        with pytest.raises(ValueError, match='Stop this repeating task'):
            TaskService.delete_task(root.id)
        db.session.rollback()
        TaskService.delete_list(root.list_id)
    assert HouseholdTask.query.count() == 0
    assert all(job.task_id is None for job in RewardJob.query.all())


def test_future_interval_cannot_be_submitted_early_and_invalid_recurrence_reports(app, user, people, clock):
    _, child, _ = people
    client = client_for(app, user)
    data = {
        'title': 'Future chore', 'assigned_membership_id': child.get_active_household_membership().id,
        'reward_points': '10', 'due_date': '2026-11-10', 'recurrence': 'daily',
    }
    assert client.post('/household/rewards/actions/create-job', data={**data, 'recurrence': 'hourly'}).status_code == 200
    assert HouseholdTask.query.count() == 0
    assert client.post('/household/rewards/actions/create-job', data=data).status_code == 302
    job = RewardJob.query.one()
    response = client_for(app, child).post('/household/rewards/actions/submit-job', data={'job_id': job.id})
    assert response.status_code == 200 and b'has not started' in response.data
    assert not job.task.completed and RewardPointEntry.query.count() == 0


def test_recurring_occurrence_cannot_be_deleted_to_reearn(app, user, people, clock):
    _, child, _ = people
    root = create_repeat(app, user, child)
    clock[0] += timedelta(days=1)
    refresh(app, child)
    occurrence = HouseholdTask.query.filter_by(series_id=root.id).one()
    with app.test_request_context():
        login_user(user)
        with pytest.raises(ValueError, match='occurrence history'):
            TaskService.delete_task(occurrence.id)
        db.session.rollback()
    refresh(app, child)
    assert HouseholdTask.query.count() == 2 and RewardJob.query.count() == 2


def test_late_pending_approval_is_kept_but_no_late_retry_for_skip_policy(app, user, people, clock):
    _, child, _ = people
    root = create_repeat(app, user, child)
    with app.test_request_context():
        login_user(child)
        RewardService.submit_job(root.reward_job.id, {})
    clock[0] += timedelta(days=2)
    refresh(app, child)
    assert root.reward_job.state == 'submitted' and not root.expired
    with app.test_request_context():
        login_user(user)
        with pytest.raises(ValueError, match='interval has ended'):
            RewardService.review_job(root.reward_job.id, {'action': 'return', 'note': 'Try again'})
        db.session.rollback()
        RewardService.review_job(root.reward_job.id, {'action': 'approve'})
    assert root.reward_job.state == 'approved'
    assert RewardPointEntry.query.count() == 1


def test_weekly_job_is_available_in_my_day_and_today_filter_all_week(app, user, people, clock):
    from services.household.my_day_service import MyDayService
    _, child, _ = people
    root = create_repeat(app, user, child, recurrence='weekly')
    with app.test_request_context():
        login_user(child)
        assert root in TaskService.hub({'list_id': root.list_id, 'filter': 'today'})['tasks']
        assert MyDayService.page_data()['reward_jobs'] == [root.reward_job]


def test_series_details_and_points_are_fixed_to_preserve_history(app, user, people, clock):
    _, child, _ = people
    root = create_repeat(app, user, child, policy='backlog')
    clock[0] += timedelta(days=1)
    refresh(app, child)
    old = HouseholdTask.query.filter_by(series_id=root.id).one()
    with app.test_request_context():
        login_user(user)
        with pytest.raises(ValueError, match='original details'):
            TaskService.update_task(root.id, {
                'title': 'Updated future chore', 'due_date': root.due_date.isoformat(),
                'assigned_membership_id': root.assigned_membership_id,
                'recurrence': 'daily', 'missed_policy': 'backlog', 'reward_points': '15',
            })
        db.session.rollback()
    clock[0] += timedelta(days=1)
    refresh(app, child)
    current = HouseholdTask.query.filter_by(series_id=root.id, period_start=date(2026, 11, 11)).one()
    assert old.title == 'Feed the cat' and old.reward_job.points == 10
    assert current.title == 'Feed the cat' and current.reward_job.points == 10


def test_recurring_migration_round_trip_matches_model(app):
    folder = Path(app.root_path) / 'migrations' / 'versions'
    modules = []
    for filename in ['b16c2e8a345f_add_household_task_lists.py', 'b83e10d5f927_add_recurring_task_intervals.py']:
        spec = importlib.util.spec_from_file_location(filename, folder / filename)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('PRAGMA foreign_keys=ON'))
        connection.execute(sa.text('CREATE TABLE families (id INTEGER PRIMARY KEY)'))
        connection.execute(sa.text('CREATE TABLE household_memberships (id INTEGER PRIMARY KEY)'))
        with Operations.context(MigrationContext.configure(connection)):
            modules[0].upgrade()
            modules[1].upgrade()
            assert {row['name'] for row in sa.inspect(connection).get_check_constraints('household_tasks')} == {
                row.name for row in HouseholdTask.__table__.constraints if isinstance(row, sa.CheckConstraint)
            }
            modules[1].downgrade()
            modules[1].upgrade()
            assert connection.execute(sa.text('PRAGMA foreign_key_check')).all() == []
    engine.dispose()
