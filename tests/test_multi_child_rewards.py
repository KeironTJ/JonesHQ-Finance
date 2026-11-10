import importlib.util
from datetime import timedelta
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask_login import login_user
from werkzeug.datastructures import MultiDict

from extensions import db
from models import Family, HouseholdTask, RewardJob, RewardPointEntry, User
from services.household.reward_service import RewardService
from tests.test_household_rewards import client_for, isolate_login_state, people
from tests.test_recurring_tasks import clock, refresh


def create_jobs(app, adult, children, mode='assigned', **changes):
    data = MultiDict([
        ('title', 'Clean your room'), ('reward_points', '15'),
        ('recurrence', 'weekly'), ('due_date', '2026-11-09'),
        ('assignment_mode', mode),
        *[('assigned_membership_ids', str(child.get_active_household_membership().id)) for child in children],
    ])
    for key, value in changes.items():
        data[key] = value
    return client_for(app, adult).post('/household/rewards/actions/create-job', data=data)


def test_four_children_have_independent_weekly_completion_and_missed_history(app, user, family, people, clock):
    children = list(people[1:])
    for name in ('Third', 'Fourth'):
        child = User(
            name=name, email=f'{name.lower()}@example.test', family_id=family.id,
            role='member', account_type='child', guardian_id=user.id,
            password_hash=user.password_hash,
        )
        db.session.add(child)
        db.session.flush()
        child.get_active_household_membership().allowed_modules = ['household']
        children.append(child)
    db.session.commit()
    assert create_jobs(app, user, children).status_code == 302
    tasks = HouseholdTask.query.order_by(HouseholdTask.id).all()
    assert len(tasks) == 4 and len({task.assigned_membership_id for task in tasks}) == 4
    assert all(not task.claim_required for task in tasks)
    for child in children[:3]:
        task = next(row for row in tasks if row.assigned_membership_id == child.get_active_household_membership().id)
        assert client_for(app, child).post('/household/rewards/actions/submit-job', data={'job_id': task.reward_job.id}).status_code == 302
        assert client_for(app, user).post('/household/rewards/actions/review-job', data={'job_id': task.reward_job.id, 'action': 'approve'}).status_code == 302
    assert RewardPointEntry.query.count() == 3
    clock[0] += timedelta(days=7)
    refresh(app, user)
    assert HouseholdTask.query.count() == 8
    missed = next(row for row in tasks if not row.completed)
    assert missed.expired and missed.reward_job.state == 'closed'
    assert sum(entry.points for entry in RewardPointEntry.query.all()) == 45
    assert HouseholdTask.query.filter(HouseholdTask.series_id.isnot(None)).filter_by(expired=False).count() == 4


def test_each_child_claims_own_turn_without_reserving_siblings_turn(app, user, people, clock):
    children = people[1:]
    assert create_jobs(app, user, children, mode='claim').status_code == 302
    tasks = HouseholdTask.query.order_by(HouseholdTask.id).all()
    child, sibling = children
    first, second = tasks
    html = client_for(app, user).get(f'/household/tasks/{first.id}').get_data(as_text=True)
    assert f'Waiting for {child.name} to claim this optional job.' in html
    client = client_for(app, child)
    html = client.get('/household/rewards?view=jobs').get_data(as_text=True)
    assert 'Claim this job' in html
    assert client.post('/household/rewards/actions/submit-job', data={'job_id': first.reward_job.id}).status_code == 200
    assert client.post(f'/household/tasks/{first.id}/completion', data={'action': 'complete'}).status_code == 302
    assert not first.completed and first.claimed_at is None
    for _ in range(2):
        assert client.post('/household/rewards/actions/claim-job', data={'job_id': first.reward_job.id}).status_code == 302
    claimed_at = first.claimed_at
    assert claimed_at is not None and second.claimed_at is None
    assert not first.completed and RewardPointEntry.query.count() == 0
    assert client.post('/household/rewards/actions/claim-job', data={'job_id': second.reward_job.id}).status_code == 404
    assert client_for(app, user).post('/household/rewards/actions/claim-job', data={'job_id': second.reward_job.id}).status_code == 403
    assert client_for(app, sibling).post('/household/rewards/actions/claim-job', data={'job_id': second.reward_job.id}).status_code == 302
    assert client_for(app, child).post('/household/rewards/actions/submit-job', data={'job_id': first.reward_job.id}).status_code == 302
    for _ in range(2):
        assert client_for(app, user).post('/household/rewards/actions/review-job', data={'job_id': first.reward_job.id, 'action': 'approve'}).status_code == 302
    assert RewardPointEntry.query.count() == 1
    clock[0] += timedelta(days=7)
    refresh(app, user)
    upcoming = HouseholdTask.query.filter(HouseholdTask.series_id.isnot(None)).all()
    assert len(upcoming) == 2 and all(task.claim_required and task.claimed_at is None for task in upcoming)
    assert first.claimed_at == claimed_at
    assert client_for(app, sibling).post('/household/rewards/actions/claim-job', data={'job_id': second.reward_job.id}).status_code == 200
    assert second.expired and second.reward_job.state == 'closed'


def test_future_claims_and_invalid_participants_cannot_create_or_award_work(app, user, people, clock):
    adult, child, sibling = people
    clock[0] -= timedelta(days=7)
    assert create_jobs(app, user, [child], mode='claim').status_code == 302
    task = HouseholdTask.query.one()
    html = client_for(app, child).get('/household/rewards?view=jobs').get_data(as_text=True)
    assert 'Available from Mon 09 Nov' in html and 'Claim this job' not in html
    assert client_for(app, child).post('/household/rewards/actions/claim-job', data={'job_id': task.reward_job.id}).status_code == 200
    assert task.claimed_at is None
    count = HouseholdTask.query.count()
    assert create_jobs(app, user, [child, adult]).status_code == 200
    assert HouseholdTask.query.count() == count
    assert create_jobs(app, child, [sibling]).status_code == 403
    other_family = Family(name='Other household')
    db.session.add(other_family)
    db.session.flush()
    outsider = User(name='Outsider', email='outsider@example.test', family_id=other_family.id, role='member',
                    account_type='child', guardian_id=None, password_hash=user.password_hash)
    db.session.add(outsider)
    db.session.commit()
    assert create_jobs(app, user, [child, outsider]).status_code == 200
    assert HouseholdTask.query.count() == count
    assert RewardPointEntry.query.count() == 0


def test_failed_form_keeps_children_claim_mode_and_schedule(app, user, people, clock):
    response = create_jobs(app, user, people[1:], mode='claim', reward_points='0')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    for child in people[1:]:
        member_id = child.get_active_household_membership().id
        assert f'id="job_member_{member_id}" value="{member_id}" checked' in html
    assert 'value="claim" selected' in html
    assert 'value="weekly" selected' in html
    assert HouseholdTask.query.count() == RewardJob.query.count() == 0


def test_duplicate_selected_children_get_only_one_turn_and_table_is_ranked(app, user, people, clock):
    child = people[1]
    assert create_jobs(app, user, [child, child]).status_code == 302
    assert HouseholdTask.query.count() == 1
    html = client_for(app, user).get('/household/rewards').get_data(as_text=True)
    assert 'table reward-leaderboard' in html and '<th scope="col">Place</th>' in html
    assert html.index('Weekly household leaderboard') < html.index('Little efforts. Proud moments.')


def test_root_schedule_page_has_no_edit_form_script_and_stops_only_its_child(app, user, people, clock):
    assert create_jobs(app, user, people[1:]).status_code == 302
    root, other = HouseholdTask.query.order_by(HouseholdTask.id).all()
    client = client_for(app, user)
    html = client.get(f'/household/tasks/{root.id}').get_data(as_text=True)
    assert 'Stop future repeats' in html
    assert 'function updateAssignees' not in html
    assert root.assignee.user.name in html
    assert client.post(f'/household/tasks/{root.id}', data={'repeat_active': 'no'}).status_code == 302
    assert not root.repeat_active and other.repeat_active
    clock[0] += timedelta(days=7)
    refresh(app, user)
    assert HouseholdTask.query.filter_by(series_id=root.id).count() == 0
    assert HouseholdTask.query.filter_by(series_id=other.id).count() == 1


def test_optional_claim_migration_preserves_existing_tasks(app):
    path = Path(app.root_path) / 'migrations' / 'versions' / 'c94f21e60838_add_optional_reward_job_claims.py'
    spec = importlib.util.spec_from_file_location('claims_migration', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(sa.text('CREATE TABLE household_tasks (id INTEGER PRIMARY KEY, title TEXT NOT NULL)'))
        connection.execute(sa.text("INSERT INTO household_tasks (id, title) VALUES (1, 'Existing chore')"))
        with Operations.context(MigrationContext.configure(connection)):
            module.upgrade()
            assert connection.execute(sa.text('SELECT claim_required, claimed_at FROM household_tasks')).one() == (0, None)
            connection.execute(sa.text("UPDATE household_tasks SET claim_required=1, claimed_at='2026-11-09 12:00:00'"))
            module.downgrade()
            assert connection.execute(sa.text('SELECT title FROM household_tasks')).scalar_one() == 'Existing chore'
            module.upgrade()
            assert connection.execute(sa.text('SELECT claim_required, claimed_at FROM household_tasks')).one() == (0, None)
    engine.dispose()
