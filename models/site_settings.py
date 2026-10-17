from datetime import datetime, timezone

from extensions import db


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SiteSettings(db.Model):
    """Service-wide switches managed by the site admin. A single row (id 1), not household data."""

    __tablename__ = 'site_settings'

    ANNOUNCEMENT_LEVELS = ('info', 'warning', 'danger')

    id = db.Column(db.Integer, primary_key=True)
    household_signups_paused = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    signups_paused_message = db.Column(db.String(300), nullable=True)
    announcement = db.Column(db.String(500), nullable=True)
    announcement_level = db.Column(db.String(10), nullable=False, default='info', server_default='info')
    updated_at = db.Column(db.DateTime, nullable=True, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f'<SiteSettings signups_paused={self.household_signups_paused}>'
