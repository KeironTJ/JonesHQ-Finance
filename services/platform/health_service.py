from flask import current_app
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from extensions import db, limiter


class HealthService:
    """Read-only checks against the configured database and rate-limit backend."""

    @staticmethod
    def check():
        checks = {}
        try:
            with db.engine.connect() as connection:
                checks['database'] = connection.execute(text('SELECT 1')).scalar() == 1
        except SQLAlchemyError as error:
            checks['database'] = False
            current_app.logger.error('HEALTH_DATABASE_FAILED error_type=%s', type(error).__name__)

        try:
            checks['rate_limit_storage'] = bool(limiter.storage.check())
        except (RedisError, OSError) as error:
            checks['rate_limit_storage'] = False
            current_app.logger.error('HEALTH_RATE_LIMIT_FAILED error_type=%s', type(error).__name__)
        if not checks['rate_limit_storage']:
            current_app.logger.error('HEALTH_RATE_LIMIT_UNAVAILABLE')
        return checks
