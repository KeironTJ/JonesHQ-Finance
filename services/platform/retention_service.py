from datetime import datetime, timezone

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from services.platform.security_event_service import SecurityEventService
from services.platform.user_session_service import UserSessionService


class RetentionService:
    """Server-only maintenance across households; never deletes financial records."""

    @staticmethod
    def cleanup(dry_run=False):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        try:
            counts = {
                'security_events': SecurityEventService._prune(dry_run=dry_run, now=now),
                'user_sessions': UserSessionService.prune(dry_run=dry_run, now=now),
            }
            if not dry_run:
                db.session.commit()
        except (SQLAlchemyError, ValueError) as error:
            db.session.rollback()
            current_app.logger.error('RETENTION_CLEANUP_FAILED error_type=%s', type(error).__name__)
            raise
        current_app.logger.info(
            'RETENTION_CLEANUP_%s security_events=%s user_sessions=%s',
            'PREVIEW' if dry_run else 'COMPLETED', counts['security_events'], counts['user_sessions'])
        return counts
