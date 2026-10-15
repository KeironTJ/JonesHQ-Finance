"""Validate the database backend before the updater pulls code."""
import argparse
from pathlib import Path
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deployment.check_production_config import load_env_file


def production_url(path):
    env = load_env_file(path)
    return make_url(env.get('DATABASE_URL') or env.get('SQLALCHEMY_DATABASE_URI') or '')


def main(argv=()):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', action='store_true',
                        help='Allow the PostgreSQL maintenance path and print the backend.')
    args = parser.parse_args(argv)
    path = Path(__file__).resolve().parent.parent / '.env.production'
    try:
        url = production_url(path)
    except (OSError, ValueError, SQLAlchemyError):
        print('ERROR: Cannot read a valid production database setting.', file=sys.stderr)
        return 1
    backend = url.get_backend_name()
    if args.backend and url.drivername == 'postgresql+psycopg' and url.database and not url.query:
        print('postgresql')
        return 0
    if backend != 'sqlite':
        print('ERROR: This updater only supports SQLite backup/restore. '
              'PostgreSQL requires --backend, postgresql+psycopg, a database name '
              'and no URL query overrides.', file=sys.stderr)
        return 1
    if args.backend:
        print('sqlite')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
