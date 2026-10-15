"""Apply migrations using the same literal environment file as the live service."""
import os
from pathlib import Path
import sys

from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deployment.check_production_config import load_env_file


def main():
    try:
        os.environ.update(load_env_file(ROOT / '.env.production'))
        os.environ['FLASK_ENV'] = 'production'
        os.environ['PGCLIENTENCODING'] = 'UTF8'
        from app import create_app
        from flask_migrate import upgrade

        app = create_app('production')
        with app.app_context():
            upgrade(directory=str(ROOT / 'migrations'))
        return 0
    except (OSError, ValueError, RuntimeError, SQLAlchemyError):
        print('ERROR: Production migration failed. Service recovery policy applies; '
              'inspect the migration privately. Database details are not printed.',
              file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
