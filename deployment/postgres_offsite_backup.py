"""Create, encrypt, upload and verify an off-site PostgreSQL backup."""
import configparser
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deployment.check_production_config import load_env_file
from deployment.postgres_update_backup import create_backup, production_url

CONFIG_DIR = Path('/etc/joneshq-offsite')
UPDATE_MARKER = Path('/home/joneshq/backups/postgres-update-incomplete')


def settings(config_dir):
    values = load_env_file(config_dir / 'backup.conf')
    bucket = values.get('R2_BUCKET', '')
    heartbeat = values.get('HEALTHCHECK_URL', '')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket):
        raise ValueError('Invalid R2 bucket name.')
    if not re.fullmatch(
        r'https://hc-ping\.com/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-'
        r'[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}', heartbeat
    ):
        raise ValueError('Expected a Healthchecks.io UUID ping URL.')
    parser = configparser.ConfigParser(interpolation=None)
    if not parser.read(config_dir / 'rclone.conf'):
        raise ValueError('Rclone configuration is missing.')
    if (not parser.has_section('r2') or parser.get('r2', 'type', fallback='') != 's3'
            or parser.get('r2', 'provider', fallback='') != 'Cloudflare'
            or not re.fullmatch(
                r'https://[0-9a-f]{32}\.eu\.r2\.cloudflarestorage\.com',
                parser.get('r2', 'endpoint', fallback='')
            )):
        raise ValueError('Rclone must use the Cloudflare EU jurisdiction endpoint.')
    if not (config_dir / 'recipient.txt').is_file():
        raise ValueError('The age recipient file is missing.')
    for tool in ('age', 'rclone'):
        if not shutil.which(tool):
            raise ValueError(f'{tool} is not installed.')
    return bucket, heartbeat


def run_backup(config_dir=CONFIG_DIR, marker=UPDATE_MARKER):
    bucket, heartbeat = settings(config_dir)
    if marker.exists():
        raise ValueError('An incomplete production update requires manual recovery.')
    url = production_url(ROOT / '.env.production')
    with tempfile.TemporaryDirectory(prefix='joneshq-offsite-') as tmp:
        work = Path(tmp)
        dump = work / 'database.dump'
        stage = work / 'encrypted'
        stage.mkdir()
        name = f"database-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex}.dump.age"
        encrypted = stage / name
        create_backup(url, dump)
        subprocess.run(
            ['age', '-R', str(config_dir / 'recipient.txt'), '-o', str(encrypted), str(dump)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        dump.unlink()
        remote = f'r2:{bucket}/database'
        common = ['--config', str(config_dir / 'rclone.conf')]
        subprocess.run(
            ['rclone', 'copyto', str(encrypted), f'{remote}/{name}', '--immutable', *common],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        subprocess.run(
            ['rclone', 'check', str(stage), remote, '--one-way', '--download', *common],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    with urllib.request.urlopen(heartbeat, timeout=15) as response:
        if response.status != 200:
            raise ValueError('Healthchecks.io did not accept the success signal.')


def main():
    try:
        run_backup()
    except (OSError, ValueError, configparser.Error, SQLAlchemyError,
            subprocess.SubprocessError) as error:
        # Underlying errors can contain credentials, URLs, or financial data.
        print(f'ERROR: Off-site backup failed ({type(error).__name__}); '
              'check its configuration and connectivity privately.', file=sys.stderr)
        return 1
    print('Off-site backup uploaded, verified and reported to Healthchecks.io.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
