import subprocess
from pathlib import Path
import pytest

from deployment import postgres_offsite_backup as backup


def configuration(tmp_path):
    (tmp_path / 'backup.conf').write_text(
        'R2_BUCKET=finance-backups\n'
        'HEALTHCHECK_URL=https://hc-ping.com/12345678-1234-1234-1234-123456789abc\n'
    )
    (tmp_path / 'rclone.conf').write_text(
        '[r2]\ntype = s3\nprovider = Cloudflare\n'
        'endpoint = https://0123456789abcdef0123456789abcdef.eu.r2.cloudflarestorage.com\n'
    )
    (tmp_path / 'recipient.txt').write_text('age1example\n')
    return tmp_path


@pytest.fixture
def ready(tmp_path, monkeypatch):
    config = tmp_path / 'config'
    config.mkdir()
    configuration(config)
    monkeypatch.setattr(backup.shutil, 'which', lambda tool: '/usr/bin/' + tool)
    monkeypatch.setattr(backup, 'production_url', lambda path: 'database-url')
    return config


def test_backup_uploads_only_encrypted_data_then_checks_before_ping(ready, tmp_path, monkeypatch):
    calls = []

    def dump(url, path):
        assert url == 'database-url'
        Path(path).write_bytes(b'private database')
        calls.append('dump')

    def run(command, **kwargs):
        calls.append(command[0] if command[0] == 'age' else command[1])
        if command[0] == 'age':
            Path(command[command.index('-o') + 1]).write_bytes(b'encrypted')
        elif command[1] == 'copyto':
            assert Path(command[2]).read_bytes() == b'encrypted'
            assert command[3].startswith('r2:finance-backups/database/')
            assert '--immutable' in command
        elif command[1] == 'check':
            assert '--download' in command and '--one-way' in command
            assert len(list(Path(command[2]).iterdir())) == 1

    class Response:
        status = 200

        def __enter__(self):
            calls.append('ping')
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(backup, 'create_backup', dump)
    monkeypatch.setattr(backup.subprocess, 'run', run)
    monkeypatch.setattr(backup.urllib.request, 'urlopen', lambda *args, **kwargs: Response())
    backup.run_backup(ready, tmp_path / 'no-marker')
    assert calls == ['dump', 'age', 'copyto', 'check', 'ping']


@pytest.mark.parametrize('failed_step', ['age', 'copyto', 'check'])
def test_failed_backup_never_sends_success(ready, tmp_path, monkeypatch, failed_step):
    monkeypatch.setattr(backup, 'create_backup', lambda url, path: Path(path).write_bytes(b'dump'))

    def run(command, **kwargs):
        step = command[0] if command[0] == 'age' else command[1]
        if step == failed_step:
            raise subprocess.CalledProcessError(1, command)
        if step == 'age':
            Path(command[command.index('-o') + 1]).write_bytes(b'encrypted')

    monkeypatch.setattr(backup.subprocess, 'run', run)
    monkeypatch.setattr(backup.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('unexpected ping'))
    with pytest.raises(subprocess.CalledProcessError):
        backup.run_backup(ready, tmp_path / 'no-marker')


def test_incomplete_update_blocks_backup(ready, tmp_path, monkeypatch):
    marker = tmp_path / 'marker'
    marker.touch()
    monkeypatch.setattr(backup, 'create_backup', lambda *a: pytest.fail('unexpected backup'))
    with pytest.raises(ValueError, match='incomplete'):
        backup.run_backup(ready, marker)


def test_non_eu_endpoint_is_rejected(ready):
    conf = ready / 'rclone.conf'
    conf.write_text(conf.read_text().replace('.eu.r2.', '.r2.'))
    with pytest.raises(ValueError, match='EU jurisdiction'):
        backup.settings(ready)


def test_failure_does_not_log_secrets(monkeypatch, capsys):
    def fail():
        raise subprocess.CalledProcessError(1, ['secret'], stderr=b'private financial data')

    monkeypatch.setattr(backup, 'run_backup', fail)
    assert backup.main() == 1
    result = capsys.readouterr()
    assert 'ERROR' in result.err
    assert 'secret' not in result.err
    assert 'private financial data' not in result.err
