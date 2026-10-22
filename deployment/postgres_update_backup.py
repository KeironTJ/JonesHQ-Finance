"""Create a private PostgreSQL recovery dump before an update; never restore automatically."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deployment.check_production_config import load_env_file


def production_url(path):
    env = load_env_file(path)
    return make_url(env.get('DATABASE_URL') or env.get('SQLALCHEMY_DATABASE_URI') or '')


def connection_environment(url):
    if url.drivername != 'postgresql+psycopg' or not url.database or url.query:
        raise ValueError('Expected postgresql+psycopg with a database name and no query overrides.')
    # Do not inherit libpq overrides or put credentials in process arguments.
    env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    env.update(PGDATABASE=url.database, PGCLIENTENCODING='UTF8', PGCONNECT_TIMEOUT='10')
    for key, value in (
        ('PGHOST', url.host), ('PGPORT', url.port),
        ('PGUSER', url.username), ('PGPASSWORD', url.password),
    ):
        if value is not None:
            env[key] = str(value)
    return env


def check_tools():
    if not all(shutil.which(tool) for tool in ('pg_dump', 'pg_restore')):
        raise ValueError('pg_dump and pg_restore must be installed before updating PostgreSQL.')


def create_backup(url, destination):
    check_tools()
    env = connection_environment(url)
    destination = Path(destination)
    created = False
    try:
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        with os.fdopen(descriptor, 'wb') as output:
            subprocess.run(
                ['pg_dump', '--format=custom', '--no-password'],
                env=env, stdout=output, stderr=subprocess.PIPE, check=True,
            )
            output.flush()
            os.fsync(output.fileno())
        subprocess.run(
            ['pg_restore', '--list', str(destination)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        if created:
            destination.unlink()
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.env.production')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    try:
        url = production_url(args.env_file)
        connection_environment(url)
        check_tools()
        if args.output:
            create_backup(url, args.output)
            print('PostgreSQL recovery dump created; archive listing verified.')
        return 0
    except (OSError, ValueError, SQLAlchemyError, subprocess.CalledProcessError):
        # libpq stderr and exception strings may include credentials or database details.
        print('ERROR: PostgreSQL backup/preflight failed. Check configuration, PostgreSQL '
              'client tools, permissions, disk space and connectivity privately. '
              'No recovery dump was confirmed by this invocation.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
