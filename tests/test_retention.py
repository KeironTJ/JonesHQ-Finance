from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import g
from sqlalchemy.exc import OperationalError

from extensions import db
from models.accounts import Account
from models.family import Family
from models.users import SecurityEvent, User, UserSession
from services.platform.retention_service import RetentionService
from services.platform.security_event_service import SecurityEventService
from services.platform.user_session_service import PRUNE_AFTER, UserSessionService


@pytest.fixture(autouse=True)
def clear_login_cache(app):
    g.pop('_login_user', None)
    yield
    g.pop('_login_user', None)


@pytest.fixture
def retention_records(app, family, user):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    other_family = Family(name='Another household')
    db.session.add(other_family)
    db.session.flush()
    other_user = User(name='Inactive user', email='inactive@example.com', family_id=other_family.id,
                      password_hash='not-used-in-this-test', is_active=False)
    db.session.add(other_user)
    db.session.flush()
    old_events = []
    old_sessions = []
    kept_events = []
    kept_sessions = []
    for owner in (user, other_user):
        for days, target in ((366, old_events), (364, kept_events)):
            event = SecurityEvent(
                user_id=owner.id, family_id=owner.family_id, event_type='login_success',
                created_at=now - timedelta(days=days))
            db.session.add(event)
            target.append(event)
        for kind in ('expired_old', 'revoked_old', 'expired_recent', 'revoked_recent', 'active', 'idle'):
            session = UserSession(
                user_id=owner.id, token_hash=f'{owner.id}-{kind}',
                created_at=now - timedelta(days=100),
                last_seen_at=now - timedelta(hours=2) if kind == 'idle' else now,
                expires_at=now + timedelta(days=1),
                remember=kind == 'active')
            if kind.startswith('expired'):
                session.expires_at = now - timedelta(days=31 if kind.endswith('old') else 29)
            if kind.startswith('revoked'):
                session.revoked_at = now - timedelta(days=31 if kind.endswith('old') else 29)
            db.session.add(session)
            (old_sessions if kind.endswith('old') else kept_sessions).append(session)
    account = Account(family_id=family.id, name='Untouched finance', account_type='Current', balance=10)
    db.session.add(account)
    db.session.commit()
    return {
        'old_events': [row.id for row in old_events],
        'kept_events': [row.id for row in kept_events],
        'old_sessions': [row.id for row in old_sessions],
        'kept_sessions': [row.id for row in kept_sessions],
        'account_id': account.id,
    }


def assert_retained(records):
    assert {row.id for row in SecurityEvent.query.all()} == set(records['kept_events'])
    assert {row.id for row in UserSession.query.all()} == set(records['kept_sessions'])
    assert Account.query.filter_by(id=records['account_id']).one().name == 'Untouched finance'
    assert User.query.count() == 2
    assert Family.query.count() == 2


def test_cleanup_removes_only_eligible_rows_across_households(app, retention_records):
    assert RetentionService.cleanup() == {'security_events': 2, 'user_sessions': 4}
    assert_retained(retention_records)
    assert RetentionService.cleanup() == {'security_events': 0, 'user_sessions': 0}


def test_dry_run_counts_without_deleting_or_committing(app, retention_records, monkeypatch):
    commit = Mock(side_effect=AssertionError('Dry runs must not commit'))
    monkeypatch.setattr(db.session, 'commit', commit)
    assert RetentionService.cleanup(dry_run=True) == {'security_events': 2, 'user_sessions': 4}
    assert SecurityEvent.query.count() == 4
    assert UserSession.query.count() == 12
    commit.assert_not_called()


def test_cleanup_cutoffs_are_strict_and_respect_event_configuration(app, user, monkeypatch):
    now = datetime(2026, 10, 15, 12)
    monkeypatch.setitem(app.config, 'SECURITY_EVENT_RETENTION_DAYS', 90)
    event_cutoff = now - timedelta(days=90)
    session_cutoff = now - PRUNE_AFTER
    for delta in (-1, 0, 1):
        db.session.add(SecurityEvent(
            user_id=user.id, event_type='login_success',
            created_at=event_cutoff + timedelta(microseconds=delta)))
        for revoked in (False, True):
            db.session.add(UserSession(
                user_id=user.id, token_hash=f'{delta}-{revoked}',
                created_at=now - timedelta(days=100), last_seen_at=now,
                expires_at=(now + timedelta(days=1) if revoked
                            else session_cutoff + timedelta(microseconds=delta)),
                revoked_at=session_cutoff + timedelta(microseconds=delta) if revoked else None))
    db.session.commit()
    assert SecurityEventService._prune(now=now) == 1
    assert UserSessionService.prune(now=now) == 2
    db.session.commit()
    assert SecurityEvent.query.count() == 2
    assert UserSession.query.count() == 4


@pytest.mark.parametrize('days', [0, -1, True, '365', None])
def test_invalid_retention_fails_without_deleting(app, retention_records, monkeypatch, days):
    monkeypatch.setitem(app.config, 'SECURITY_EVENT_RETENTION_DAYS', days)
    result = app.test_cli_runner().invoke(args=['maintenance', 'cleanup'])
    assert result.exit_code != 0
    assert 'positive integer' in result.output
    assert SecurityEvent.query.count() == 4
    assert UserSession.query.count() == 12


def test_cleanup_rolls_back_both_tables_on_failure(app, retention_records, monkeypatch, caplog):
    monkeypatch.setattr(UserSessionService, 'prune', Mock(
        side_effect=OperationalError('delete', {}, Exception('sensitive-db-details'))))
    result = app.test_cli_runner().invoke(args=['maintenance', 'cleanup'])
    assert result.exit_code != 0
    assert 'no changes were committed' in result.output
    assert 'RETENTION_CLEANUP_FAILED error_type=OperationalError' in caplog.text
    assert 'sensitive-db-details' not in result.output
    assert 'sensitive-db-details' not in caplog.text
    assert SecurityEvent.query.count() == 4
    assert UserSession.query.count() == 12


def test_cleanup_commit_failure_is_not_reported_as_success(app, retention_records, monkeypatch):
    monkeypatch.setattr(db.session, 'commit', Mock(
        side_effect=OperationalError('commit', {}, Exception('unavailable'))))
    result = app.test_cli_runner().invoke(args=['maintenance', 'cleanup'])
    assert result.exit_code != 0
    assert 'cleanup completed' not in result.output
    assert SecurityEvent.query.count() == 4
    assert UserSession.query.count() == 12


def test_cleanup_cli_preview_and_execution(app, retention_records):
    runner = app.test_cli_runner()
    preview = runner.invoke(args=['maintenance', 'cleanup', '--dry-run'])
    assert preview.exit_code == 0
    assert 'Preview only' in preview.output
    assert 'security_events: 2' in preview.output
    assert 'user_sessions: 4' in preview.output
    assert SecurityEvent.query.count() == 4
    result = runner.invoke(args=['maintenance', 'cleanup'])
    assert result.exit_code == 0
    assert 'Retention cleanup completed' in result.output
    assert 'security_events: 2' in result.output
    assert_retained(retention_records)


def test_no_cleanup_http_endpoint(app):
    assert app.test_client().get('/maintenance/cleanup').status_code == 404


def test_systemd_files_use_production_env_and_persistent_daily_timer(app):
    root = Path(app.root_path, 'deployment')
    service = (root / 'joneshq-maintenance.service').read_text()
    timer = (root / 'joneshq-maintenance.timer').read_text()
    assert 'User=joneshq' in service
    assert 'EnvironmentFile=/home/joneshq/joneshq-finance/.env.production' in service
    assert 'Environment="FLASK_ENV=production"' in service
    assert 'venv/bin/flask --app app maintenance cleanup' in service
    assert 'Type=oneshot' in service
    assert 'Persistent=true' in timer
    assert 'OnCalendar=*-*-* 03:15:00 UTC' in timer
    assert 'Unit=joneshq-maintenance.service' in timer
