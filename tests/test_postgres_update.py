from contextlib import nullcontext
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from deployment import postgres_update_backup as backup
from deployment import migrate_production as migration


def test_postgres_connection_settings_do_not_leak_into_arguments(monkeypatch):
    monkeypatch.setenv('PGSERVICE', 'wrong-service')
    monkeypatch.setenv('PGHOST', 'wrong-host')
    monkeypatch.setenv('PGOPTIONS', 'unsafe-override')
    env = backup.connection_environment(
        make_url('postgresql+psycopg://app:p%40ss@localhost:5433/finance'))
    assert env['PGPASSWORD'] == 'p@ss'
    assert env['PGHOST'] == 'localhost'
    assert env['PGPORT'] == '5433'
    assert env['PGUSER'] == 'app'
    assert env['PGDATABASE'] == 'finance'
    assert env['PGCLIENTENCODING'] == 'UTF8'
    assert 'PGSERVICE' not in env
    assert 'PGOPTIONS' not in env


@pytest.mark.parametrize('url', [
    'sqlite:///finance.db',
    'postgresql://localhost/finance',
    'postgresql+psycopg://localhost/',
    'postgresql+psycopg:///finance?host=other',
])
def test_backup_rejects_unsupported_connection_settings(url):
    with pytest.raises(ValueError):
        backup.connection_environment(make_url(url))


@pytest.mark.parametrize('url,expected', [
    ('postgresql+psycopg:///finance', 0),
    ('sqlite:////home/joneshq/snapshot.db', 1),
    ('postgresql+psycopg:///finance?host=other', 1),
    ('postgresql+psycopg://localhost', 1),
    ('not-a-url', 1),
])
def test_preflight_only_allows_supported_postgres(monkeypatch, capsys, url, expected):
    monkeypatch.setattr(backup, 'load_env_file', lambda path: {'DATABASE_URL': url})
    monkeypatch.setattr(backup, 'check_tools', lambda: None)
    assert backup.main(['--check']) == expected
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('failure', [None, 'pg_dump', 'pg_restore'])
def test_dump_is_exclusive_and_failures_remove_partial_output(tmp_path, monkeypatch, failure):
    monkeypatch.setattr(backup, 'check_tools', lambda: None)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        assert all('private-password' not in part for part in command)
        if command[0] == 'pg_dump':
            kwargs['stdout'].write(b'archive')
        if command[0] == failure:
            raise subprocess.CalledProcessError(1, command, stderr=b'sensitive details')

    monkeypatch.setattr(backup.subprocess, 'run', run)
    path = tmp_path / 'database.dump'
    url = make_url('postgresql+psycopg://app:private-password@localhost/finance')
    if failure:
        with pytest.raises(subprocess.CalledProcessError):
            backup.create_backup(url, path)
        assert not path.exists()
    else:
        backup.create_backup(url, path)
        assert path.read_bytes() == b'archive'
        assert [command[0] for command in calls] == ['pg_dump', 'pg_restore']
        with pytest.raises(FileExistsError):
            backup.create_backup(url, path)
        assert path.read_bytes() == b'archive'


def test_backup_cli_redacts_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(backup, 'production_url', lambda path: make_url(
        'postgresql+psycopg:///finance'))
    monkeypatch.setattr(backup, 'check_tools', lambda: None)

    def fail(*args):
        raise subprocess.CalledProcessError(
            1, ['pg_dump'], stderr=b'private-password financial data')

    monkeypatch.setattr(backup, 'create_backup', fail)
    assert backup.main(['--output', str(tmp_path / 'database.dump')]) == 1
    output = capsys.readouterr()
    assert 'ERROR' in output.err
    assert 'private-password' not in output.err
    assert 'financial data' not in output.err


def test_migration_explicitly_loads_production_environment(monkeypatch):
    import app
    import flask_migrate

    monkeypatch.setenv('DATABASE_URL', 'sqlite:///wrong-default.db')
    monkeypatch.setattr(migration, 'load_env_file', lambda path: {
        'DATABASE_URL': 'postgresql+psycopg:///production'})
    observed = []

    def factory(name):
        observed.append((name, os.environ['DATABASE_URL'], os.environ['FLASK_ENV'],
                         os.environ['PGCLIENTENCODING']))
        return SimpleNamespace(app_context=nullcontext)

    monkeypatch.setattr(app, 'create_app', factory)
    monkeypatch.setattr(flask_migrate, 'upgrade', lambda **kwargs: observed.append(kwargs))
    # Restore values set by the launcher after this test.
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('PGCLIENTENCODING', 'SQL_ASCII')
    assert migration.main() == 0
    assert observed[0] == ('production', 'postgresql+psycopg:///production', 'production', 'UTF8')
    assert observed[1] == {'directory': str(migration.ROOT / 'migrations')}


def test_migration_failure_is_reported_without_database_details(monkeypatch, capsys):
    from sqlalchemy.exc import SQLAlchemyError
    import app

    monkeypatch.setattr(migration, 'load_env_file', lambda path: {})
    monkeypatch.setenv('FLASK_ENV', 'development')
    monkeypatch.setenv('PGCLIENTENCODING', 'SQL_ASCII')

    def factory(name):
        raise SQLAlchemyError('private financial values')

    monkeypatch.setattr(app, 'create_app', factory)
    assert migration.main() == 1
    output = capsys.readouterr()
    assert 'ERROR' in output.err
    assert 'private financial values' not in output.err


def bash_executable():
    candidates = [
        Path(r'C:\Program Files\Git\bin\bash.exe'),
        Path(r'C:\Program Files\Git\usr\bin\bash.exe'),
    ] if os.name == 'nt' else [Path(shutil.which('bash') or '/missing-bash')]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    pytest.skip('Bash is required to exercise updater control flow.')


def run_updater(
    tmp_path, failure, timer_active=True, recovery_failure='',
    maintenance_installed=True, probe_failures=0,
):
    executable = bash_executable()
    source = (Path(__file__).resolve().parents[1] / 'deployment' / 'quick_update.sh').read_text()
    # Only paths and the root check change; execute the actual updater control flow.
    source = source.replace('APP_DIR="/home/joneshq/joneshq-finance"', 'APP_DIR="$TEST_ROOT/app"')
    source = source.replace('BACKUP_DIR="/home/joneshq/backups"', 'BACKUP_DIR="$TEST_ROOT/backups"')
    source = source.replace('LOCK_FILE="/var/lock/joneshq-quick-update.lock"', 'LOCK_FILE="$TEST_ROOT/update.lock"')
    source = source.replace('if [ "$EUID" -ne 0 ]; then', 'if false; then')
    (tmp_path / 'update.sh').write_text(source, newline='\n')
    harness = r'''
set -e
TEST_ROOT="$(cd "$(dirname "$0")" && pwd)"
export TEST_ROOT
mkdir -p "$TEST_ROOT/app/logs" "$TEST_ROOT/app/venv/bin" "$TEST_ROOT/app/deployment"
for helper in postgres_update_recovery postgres_update_backup check_production_config; do
    touch "$TEST_ROOT/app/deployment/$helper.py"
done
cat > "$TEST_ROOT/app/venv/bin/python" <<'PYTHON'
#!/bin/bash
printf 'recover-db\n' >> "$TEST_ROOT/events"
[ "$RECOVERY_FAILURE" != database ]
PYTHON
chmod +x "$TEST_ROOT/app/venv/bin/python"
printf 'old-dependencies\n' > "$TEST_ROOT/app/venv/packages"
printf 'test configuration\n' > "$TEST_ROOT/app/.env.production"
event() { printf '%s\n' "$*" >> "$TEST_ROOT/events"; }
flock() { :; }
psql() { :; }
createdb() { :; }
sleep() { :; }
chown() { :; }
install() { mkdir -p "$BACKUP_DIR"; }
systemctl() {
    event "systemctl $*"
    if [ "$1" = cat ] && [[ "$*" = *joneshq-maintenance* ]]; then
        [ "$MAINTENANCE_INSTALLED" = yes ]
        return
    fi
    if [ "$1" = is-active ] && [ "${@: -1}" = joneshq-maintenance.timer ]; then
        [ "$TIMER_ACTIVE" = yes ]
        return
    fi
    if [ "$1" = restart ]; then
        if [ "$RECOVERY_FAILURE" = restart ]; then return 1; fi
        if [ "$PUBLIC_START_ATTEMPTED" -eq 1 ] && [ "$FAILURE" = restart ]; then return 1; fi
    fi
    return 0
}
systemd-run() {
    event probe-start
    printf '%s\n' "$@" > "$TEST_ROOT/probe-options"
    [ "$FAILURE" != probe-start ]
}
PROBE_ATTEMPTS=0
curl() {
    if [[ "$*" = *--unix-socket* ]]; then
        event probe-health
        PROBE_ATTEMPTS=$((PROBE_ATTEMPTS + 1))
        if [ "$FAILURE" = probe ] || [ "$PROBE_ATTEMPTS" -le "$PROBE_FAILURES" ]; then
            printf 'curl: (7) Unix socket is not ready\n' >&2
            return 7
        fi
        return
    fi
    event health
    if [ "$PUBLIC_START_ATTEMPTED" -eq 1 ] && [ "$FAILURE" = health ]; then
        printf 500
    else
        printf 200
    fi
}
sudo() {
    shift 2
    case "$*" in
        *postgres_update_backup.py*--check*)
            event preflight
            [ "$FAILURE" != preflight ] ;;
        *postgres_update_backup.py*--output*)
            event dump
            [ "$FAILURE" != dump ] ;;
        *"git status"*) : ;;
        *"git rev-parse"*) printf 'previous-commit\n' ;;
        *"git pull"*) event pull; [ "$FAILURE" != pull ] ;;
        *"git"*reset*)
            event rollback-code
            RECOVERING=yes
            [ "$RECOVERY_FAILURE" != code ] ;;
        *"pip install"*)
            event dependencies
            printf 'candidate-dependencies\n' > "$APP_DIR/venv/packages"
            [ "$FAILURE" != dependencies ] ;;
        *check_production_config.py*)
            event config
            if [ "${RECOVERING:-no}" = yes ]; then
                [ "$RECOVERY_FAILURE" != config ]
            else
                [ "$FAILURE" != config ]
            fi ;;
        *"&& pytest -q"*) event tests; [ "$FAILURE" != tests ] ;;
        *migrate_production.py*) event migration; [ "$FAILURE" != migration ] ;;
        mktemp*) "$@" ;;
        *) event "UNEXPECTED sudo $*"; return 1 ;;
    esac
}
source "$TEST_ROOT/update.sh"
'''
    path = tmp_path / 'harness.sh'
    path.write_text(harness, newline='\n')
    env = os.environ.copy()
    env['FAILURE'] = failure
    env['RECOVERY_FAILURE'] = recovery_failure
    env['MAINTENANCE_INSTALLED'] = 'yes' if maintenance_installed else 'no'
    env['TIMER_ACTIVE'] = 'yes' if timer_active else 'no'
    env['PROBE_FAILURES'] = str(probe_failures)
    result = subprocess.run(
        [executable, str(path)], env=env, capture_output=True, text=True,
    )
    events = (tmp_path / 'events').read_text().splitlines()
    assert 'UNEXPECTED' not in '\n'.join(events), result.stdout + result.stderr
    return result, events


@pytest.mark.parametrize('probe_failures', [1, 3])
def test_probe_waits_for_delayed_unix_socket(tmp_path, probe_failures):
    result, events = run_updater(tmp_path, '', probe_failures=probe_failures)

    assert result.returncode == 0, result.stdout + result.stderr
    assert events.count('probe-health') == probe_failures + 1
    assert events.index('probe-health') < events.index('systemctl restart joneshq-finance')
    assert 'recover-db' not in events
    assert 'rollback-code' not in events
    options = (tmp_path / 'probe-options').read_text()
    assert '--property=StandardOutput=append:' in options
    assert '/probe.log' in options
    assert '--property=StandardError=inherit' in options


def test_probe_exhaustion_is_bounded_and_reports_private_diagnostics(tmp_path):
    result, events = run_updater(tmp_path, 'probe')

    assert result.returncode == 1
    assert events.count('probe-health') == 30
    assert 'Candidate did not become healthy after 30 attempts' in result.stdout
    recovery = next((tmp_path / 'backups').glob('postgres-update-*'))
    assert str(recovery.name) + '/probe.log' in result.stdout
    assert 'Unix socket is not ready' in (recovery / 'probe-health-error.log').read_text()
    assert 'Automatic recovery completed' in result.stdout


@pytest.mark.skipif(os.name == 'nt', reason='Real curl Unix sockets require Linux CI.')
def test_probe_readiness_with_real_curl_and_delayed_unix_listener():
    from http.server import BaseHTTPRequestHandler
    from socketserver import UnixStreamServer
    from tempfile import TemporaryDirectory
    from threading import Thread
    from time import sleep

    if not shutil.which('curl'):
        pytest.skip('curl is required for the real Unix-socket readiness test.')

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == '/healthz'
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')

        def log_message(self, *_args):
            pass

    source = (Path(__file__).resolve().parents[1] / 'deployment' / 'quick_update.sh').read_text()
    prefix = source.split('recover_update() {', 1)[0]
    # Keep the socket path short enough for AF_UNIX's platform length limit.
    with TemporaryDirectory(prefix='joneshq-probe-') as directory:
        socket_path = Path(directory) / 'probe.sock'
        with UnixStreamServer(str(socket_path), Handler, bind_and_activate=False) as server:
            server.timeout = 5

            def start_delayed_listener():
                sleep(0.5)
                server.server_bind()
                server.server_activate()
                server.handle_request()

            listener = Thread(target=start_delayed_listener)
            listener.start()
            try:
                env = os.environ.copy()
                env['PROBE_TEST_ROOT'] = directory
                result = subprocess.run(
                    [bash_executable(), '-c', prefix + '\nRECOVERY_DIR="$PROBE_TEST_ROOT"\nwait_for_probe\n'],
                    env=env, capture_output=True, text=True, timeout=15,
                )
                assert result.returncode == 0, result.stdout + result.stderr
            finally:
                listener.join(timeout=10)
            assert not listener.is_alive()


@pytest.mark.parametrize('failure', [
    '', 'preflight', 'dump', 'pull', 'dependencies', 'tests', 'migration',
    'config', 'probe-start', 'probe', 'restart', 'health',
])
def test_postgres_updater_recovers_only_before_public_writes(tmp_path, failure):
    result, events = run_updater(tmp_path, failure)
    assert result.returncode == (1 if failure else 0), result.stdout + result.stderr
    if failure == 'preflight':
        assert not (tmp_path / 'backups' / 'postgres-update-incomplete').exists()
        assert not any(event.startswith('systemctl stop') for event in events)
        assert 'pull' not in events
        return
    assert events.index('systemctl stop joneshq-maintenance.timer') < events.index('dump')
    assert events.index('systemctl stop joneshq-maintenance.service') < events.index('dump')
    assert events.index('systemctl stop joneshq-finance') < events.index('dump')
    if failure == 'dump':
        assert 'pull' not in events
    else:
        assert events.index('dump') < events.index('pull')
    if not failure:
        assert not (tmp_path / 'backups' / 'postgres-update-incomplete').exists()
        assert events.index('health') < events.index('systemctl start joneshq-maintenance.timer')
        assert 'Update Complete!' in result.stdout
        assert events.index('probe-health') < events.index('systemctl restart joneshq-finance')
        assert 'rollback-code' not in events
    elif failure in ('restart', 'health'):
        assert (tmp_path / 'backups' / 'postgres-update-incomplete').exists()
        assert events[-1].startswith('systemctl stop joneshq-update-probe')
        assert 'systemctl start joneshq-maintenance.timer' not in events
        assert 'writes may have resumed' in result.stdout
        assert 'Previous commit: previous-commit' in result.stdout
        assert 'Update Complete!' not in result.stdout
        assert 'recover-db' not in events
        assert 'rollback-code' not in events
    else:
        assert not (tmp_path / 'backups' / 'postgres-update-incomplete').exists()
        assert 'Automatic recovery completed' in result.stdout
        assert ('recover-db' in events) == (failure in ('migration', 'probe-start', 'probe'))
        assert ('rollback-code' in events) == (failure != 'dump')
        assert 'systemctl start joneshq-maintenance.timer' in events
        assert 'Update Complete!' not in result.stdout
        assert (tmp_path / 'app' / 'venv' / 'packages').read_text().strip() == 'old-dependencies'


def test_postgres_updater_does_not_enable_previously_inactive_timer(tmp_path):
    result, events = run_updater(tmp_path, '', timer_active=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'systemctl start joneshq-maintenance.timer' not in events


def test_failed_postgres_update_blocks_another_attempt(tmp_path):
    first, events = run_updater(tmp_path, 'migration', recovery_failure='database')
    assert first.returncode == 1
    second, later_events = run_updater(tmp_path, '')
    assert second.returncode == 1
    assert 'previous PostgreSQL update requires manual recovery' in second.stdout
    assert later_events == events


@pytest.mark.parametrize('recovery_failure', ['database', 'code', 'config', 'restart'])
def test_failed_automatic_recovery_keeps_writers_stopped(tmp_path, recovery_failure):
    result, events = run_updater(tmp_path, 'migration', recovery_failure=recovery_failure)
    assert result.returncode == 1
    assert (tmp_path / 'backups' / 'postgres-update-incomplete').exists()
    assert 'Automatic recovery is unsafe or failed' in result.stdout
    assert events[-1].startswith('systemctl stop joneshq-update-probe')
    assert 'systemctl start joneshq-maintenance.timer' not in events


def test_recovery_does_not_start_previously_inactive_timer(tmp_path):
    result, events = run_updater(tmp_path, 'migration', timer_active=False)
    assert result.returncode == 1
    assert 'Automatic recovery completed' in result.stdout
    assert 'systemctl start joneshq-maintenance.timer' not in events


def test_recovery_supports_installations_without_retention_units(tmp_path):
    result, events = run_updater(tmp_path, 'migration', timer_active=False, maintenance_installed=False)
    assert result.returncode == 1
    assert 'Automatic recovery completed' in result.stdout
    assert 'systemctl stop joneshq-maintenance.timer' not in events
    assert 'systemctl stop joneshq-maintenance.service' not in events
