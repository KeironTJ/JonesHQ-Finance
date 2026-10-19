from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import current_app
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.family import Family
from models.users import SecurityEvent, User, UserSession
from services.platform.household_invite_service import HouseholdInviteService


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SiteAdminService:
    """Service-wide counts and configuration status for the site admin overview.

    Aggregates only: no household financial records and no secrets.
    """

    @staticmethod
    def overview():
        now = _now()
        return {
            'households': db.session.query(func.count(Family.id)).scalar(),
            'active_users': User.query.filter(User.is_active.is_(True)).count(),
            'inactive_users': User.query.filter(User.is_active.is_(False)).count(),
            'locked_users': User.query.filter(User.locked_until > now).count(),
            'site_admins': User.query.filter(User.is_site_admin.is_(True)).count(),
            'active_sessions': UserSession.query.filter(
                UserSession.revoked_at.is_(None), UserSession.expires_at > now).count(),
            'active_household_invites': sum(
                1 for invite in HouseholdInviteService.list_invites() if invite.status == 'active'),
            'failed_sign_ins_24h': SecurityEvent.query.filter(
                SecurityEvent.event_type.in_(('login_failed', 'two_factor_failed', 'passkey_failed', 'account_locked')),
                SecurityEvent.created_at > now - timedelta(hours=24)).count(),
        }

    @staticmethod
    def configuration():
        """Effective configuration from the environment file. Read-only; secrets are never included."""
        config = current_app.config
        rate_limit_scheme = urlsplit(config.get('RATELIMIT_STORAGE_URI') or '').scheme or 'not set'
        return [
            ('Household registration', 'Open to anyone' if config.get('ALLOW_OPEN_REGISTRATION') else 'Invite only'),
            ('Outgoing email', 'Configured' if config.get('MAIL_SERVER') and config.get('MAIL_FROM') else 'Not configured'),
            ('Email sender', config.get('MAIL_FROM') or '—'),
            ('Public address (APP_BASE_URL)', config.get('APP_BASE_URL') or '—'),
            ('Idle sign-out', f"{config.get('SESSION_IDLE_MINUTES')} minutes"),
            ('Maximum session length', f"{config.get('SESSION_ABSOLUTE_HOURS')} hours"),
            ('Password confirmation window', f"{config.get('REAUTH_WINDOW_MINUTES')} minutes"),
            ('Security event retention', f"{config.get('SECURITY_EVENT_RETENTION_DAYS')} days"),
            ('Rate-limit storage', rate_limit_scheme),
            ('Trusted proxies', str(config.get('TRUSTED_PROXY_COUNT'))),
            ('Direct connections', 'Proxy and local only' if (config.get('TRUSTED_PROXY_IPS') or '').strip()
             else 'Accepted from any address'),
            ('Database engine', db.engine.dialect.name),
            ('Database migration', SiteAdminService._migration_revision()),
        ]

    @staticmethod
    def _migration_revision():
        try:
            return db.session.execute(text('SELECT version_num FROM alembic_version')).scalar() or '—'
        except SQLAlchemyError:
            db.session.rollback()
            return 'unknown'
