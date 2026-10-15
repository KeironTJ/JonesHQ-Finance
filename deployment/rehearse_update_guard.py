"""Prevent the SQLite updater from operating against another database backend."""
from pathlib import Path
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deployment.check_production_config import load_env_file


def main():
    path = Path(__file__).resolve().parent.parent / '.env.production'
    try:
        env = load_env_file(path)
        url = make_url(env.get('DATABASE_URL') or env.get('SQLALCHEMY_DATABASE_URI') or '')
    except (OSError, ValueError, SQLAlchemyError):
        print('ERROR: Cannot read a valid production database setting.', file=sys.stderr)
        return 1
    if url.get_backend_name() != 'sqlite':
        print('ERROR: This updater only supports SQLite backup/restore. '
              'Do not use it for PostgreSQL yet.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
