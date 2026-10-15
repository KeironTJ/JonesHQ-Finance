import logging
import smtplib
from unittest.mock import Mock

import pytest
from flask import g
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import OperationalError

from extensions import db, limiter
from services.platform.email_service import EmailService
from services.platform.health_service import HealthService
from tests.auth_helpers import login_client


@pytest.fixture(autouse=True)
def clear_login_cache(app):
    g.pop('_login_user', None)
    yield
    g.pop('_login_user', None)


def test_health_checks_real_database_and_storage(app):
    assert HealthService.check() == {'database': True, 'rate_limit_storage': True}


@pytest.mark.parametrize('backend', ['database', 'rate_limit_storage'])
def test_health_returns_generic_503_and_cli_failure(app, monkeypatch, caplog, backend):
    if backend == 'database':
        monkeypatch.setattr(db.engine, 'connect', Mock(
            side_effect=OperationalError('SELECT 1', {}, Exception('secret-db-host'))))
    else:
        monkeypatch.setattr(limiter.storage, 'check', Mock(
            side_effect=RedisConnectionError('secret-redis-host')))
    with caplog.at_level(logging.ERROR):
        response = app.test_client().get('/healthz')
        result = app.test_cli_runner().invoke(args=['health'])
    assert response.status_code == 503
    assert response.get_json() == {'status': 'unavailable'}
    assert response.headers['Cache-Control'] == 'no-store'
    assert result.exit_code == 1
    assert f'{backend}: FAILED' in result.output
    assert 'secret-' not in response.get_data(as_text=True)
    assert 'secret-' not in result.output
    assert 'secret-' not in caplog.text


def test_health_detects_false_storage_check(app, monkeypatch):
    monkeypatch.setattr(limiter.storage, 'check', lambda: False)
    assert app.test_client().get('/healthz').status_code == 503


def test_health_is_public_uncached_and_does_not_set_session(app):
    response = app.test_client().get('/healthz')
    assert response.status_code == 200
    assert response.get_json() == {'status': 'ok'}
    assert response.headers['Cache-Control'] == 'no-store'
    assert 'Set-Cookie' not in response.headers


def test_health_skips_login_loading_even_with_signed_in_cookie(app, user, monkeypatch):
    user.is_site_admin = True
    db.session.commit()
    client = app.test_client()
    login_client(client, user.id)
    loader = Mock(side_effect=AssertionError('Health must not load login state'))
    monkeypatch.setattr('services.platform.user_session_service.UserSessionService.load_user', loader)
    assert client.get('/healthz').status_code == 200
    loader.assert_not_called()


def test_health_cli_success(app):
    result = app.test_cli_runner().invoke(args=['health'])
    assert result.exit_code == 0
    assert 'database: OK' in result.output
    assert 'rate_limit_storage: OK' in result.output
    assert 'Email delivery is not checked' in result.output


@pytest.mark.parametrize('background', [False, True])
def test_email_failure_logged_without_message_data(app, monkeypatch, caplog, background):
    error = smtplib.SMTPAuthenticationError(535, b'sensitive-provider-detail')
    monkeypatch.setattr(EmailService, '_deliver', Mock(side_effect=error))
    message = Mock()
    with caplog.at_level(logging.INFO):
        if background:
            EmailService._deliver_in_background(app, message)
        else:
            with pytest.raises(smtplib.SMTPAuthenticationError):
                EmailService._deliver_logged(app, message)
    assert 'MAIL_DELIVERY_FAILED error_type=SMTPAuthenticationError' in caplog.text
    assert 'sensitive-provider-detail' not in caplog.text
    assert 'MAIL_SMTP_ACCEPTED' not in caplog.text


def test_email_acceptance_log_is_not_an_inbox_delivery_claim(app, monkeypatch, caplog):
    monkeypatch.setattr(EmailService, '_deliver', Mock())
    with caplog.at_level(logging.INFO):
        EmailService._deliver_logged(app, Mock())
    assert 'MAIL_SMTP_ACCEPTED' in caplog.text
    assert 'MAIL_DELIVERY_FAILED' not in caplog.text


def test_waiting_send_uses_logged_delivery_boundary(app, monkeypatch):
    monkeypatch.setattr(app, 'testing', False)
    delivery = Mock()
    monkeypatch.setattr(EmailService, '_deliver_logged', delivery)
    assert EmailService.send('test@example.com', 'Test', 'test', wait=True, base_url='https://example.com')
    delivery.assert_called_once()
