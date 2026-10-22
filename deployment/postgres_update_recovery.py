"""Restore a stopped local deployment into a new database, preserving the failed database."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import psycopg
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deployment.postgres_update_backup import connection_environment, production_url


def restore_database(env_file, archive, write_env, app_user):
    url = production_url(env_file)
    env = connection_environment(url)
    if url.host not in (None, '', '/var/run/postgresql'):
        raise ValueError('Automatic recovery requires local Unix-socket PostgreSQL.')
    archive = Path(archive).resolve(strict=True)
    admin_env = {key: value for key, value in os.environ.items() if not key.startswith('PG')}
    metadata = subprocess.run([
        'sudo', '-u', 'postgres', 'psql', '--host=/var/run/postgresql',
        f'--port={url.port or 5432}', '--dbname=postgres', '--no-password',
        '--tuples-only', '--no-align', '--set=ON_ERROR_STOP=1', '--command',
        'SELECT json_build_array(pg_get_userbyid(datdba), pg_encoding_to_char(encoding), '
        'datcollate, datctype) FROM pg_database WHERE datname = '
        + psycopg.sql.Literal(url.database).as_string(),
    ], env=admin_env, capture_output=True, text=True, check=True)
    owner, encoding, collate, ctype = json.loads(metadata.stdout)
    if owner != app_user or url.username not in (None, app_user):
        raise ValueError('Automatic recovery requires a database owned by the app user.')
    name = 'joneshq_recovery_' + uuid.uuid4().hex[:16]
    # No credentials or inherited libpq options are passed to the local administrator.
    subprocess.run([
        'sudo', '-u', 'postgres', 'createdb',
        '--host=/var/run/postgresql', f'--port={url.port or 5432}',
        '--template=template0', f'--encoding={encoding}',
        f'--lc-collate={collate}', f'--lc-ctype={ctype}',
        f'--owner={owner}', name,
    ], env=admin_env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    env['PGDATABASE'] = name
    subprocess.run([
        'sudo', '-u', app_user, '--preserve-env=' + ','.join(
            key for key in env if key.startswith('PG')),
        'pg_restore', '--no-password', '--single-transaction', '--exit-on-error',
        f'--dbname={name}', str(archive),
    ], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)

    value = url.set(database=name).render_as_string(hide_password=False)
    if any(character in value for character in ('"', '\\', '\n', '\r', '$', '`')):
        raise ValueError('Database URL cannot be safely written as a systemd environment value.')
    original = Path(env_file).read_text(encoding='utf-8')
    lines = [line for line in original.splitlines()
             if not re.match(r'^\s*(DATABASE_URL|SQLALCHEMY_DATABASE_URI)\s*=', line)]
    lines.append(f'DATABASE_URL="{value}"')
    destination = Path(write_env)
    temporary = destination.with_name(destination.name + '.recovery-tmp')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write('\n'.join(lines) + '\n')
        output.flush()
        os.fsync(output.fileno())
    import pwd
    identity = pwd.getpwnam(app_user)
    os.chown(temporary, identity.pw_uid, identity.pw_gid)
    os.replace(temporary, destination)
    print(f'Restored recovery database: {name}. Failed database preserved.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--write-env', type=Path, required=True)
    parser.add_argument('--app-user', required=True)
    args = parser.parse_args(argv)
    try:
        restore_database(args.env_file, args.archive, args.write_env, args.app_user)
    except (OSError, ValueError, SQLAlchemyError, psycopg.Error, subprocess.CalledProcessError):
        print('ERROR: Automatic database recovery failed; keep writers stopped and inspect '
              'the recovery directory privately. No database was deleted.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
