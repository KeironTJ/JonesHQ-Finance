import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from deployment import postgres_update_recovery as recovery


@pytest.mark.parametrize('failure', ['metadata', 'create', 'restore', None])
def test_recovery_preserves_failed_database_and_switches_only_after_restore(
        tmp_path, monkeypatch, capsys, failure):
    saved = tmp_path / 'saved.env'
    saved.write_text('SECRET_KEY=private-secret\nDATABASE_URL=postgresql+psycopg:///old\n')
    active = tmp_path / 'active.env'
    active.write_text(saved.read_text())
    archive = tmp_path / 'database.dump'
    archive.write_bytes(b'archive')
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        stage = 'metadata' if 'psql' in command else 'create' if 'createdb' in command else 'restore'
        if stage == failure:
            raise subprocess.CalledProcessError(1, command, stderr=b'private database data')
        return SimpleNamespace(stdout='["joneshq", "UTF8", "C", "C"]')

    monkeypatch.setattr(recovery.subprocess, 'run', run)
    monkeypatch.setitem(sys.modules, 'pwd', SimpleNamespace(
        getpwnam=lambda name: SimpleNamespace(pw_uid=1, pw_gid=1)))
    monkeypatch.setattr(os, 'chown', lambda *args: None, raising=False)
    args = ['--env-file', str(saved), '--archive', str(archive), '--write-env', str(active),
            '--app-user', 'joneshq']
    assert recovery.main(args) == (1 if failure else 0)
    assert not any('dropdb' in command for command, _ in calls)
    if failure:
        assert active.read_text() == saved.read_text()
    else:
        assert 'SECRET_KEY=private-secret' in active.read_text()
        assert 'joneshq_recovery_' in active.read_text()
        command, kwargs = calls[-1]
        assert command[:3] == ['sudo', '-u', 'joneshq']
        assert '--single-transaction' in command
        assert '--exit-on-error' in command
        assert kwargs['env']['PGDATABASE'].startswith('joneshq_recovery_')
    output = capsys.readouterr()
    assert 'private-secret' not in output.out + output.err
    assert 'private database data' not in output.out + output.err


def test_recovery_refuses_remote_database_without_running_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'production_url',
                        lambda path: make_url('postgresql+psycopg://remote.invalid/finance'))
    monkeypatch.setattr(recovery.subprocess, 'run', lambda *a, **kw: pytest.fail('Remote recovery ran'))
    with pytest.raises(ValueError, match='local Unix-socket'):
        recovery.restore_database(tmp_path / 'env', tmp_path / 'dump', tmp_path / 'active', 'joneshq')
