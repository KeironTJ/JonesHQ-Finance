from datetime import datetime, timezone

from extensions import db


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SiteSettings(db.Model):
    """Service-wide switches managed by the site admin. A single row (id 1), not household data."""

    __tablename__ = 'site_settings'

    ANNOUNCEMENT_LEVELS = ('info', 'warning', 'danger')
    DEFAULT_TRIP_PLANNING_DAYS = 1800
    DEFAULT_ACTIVE_TRIP_ROUTINES = 25
    MAX_TRIP_PLANNING_DAYS = 3650
    MAX_ACTIVE_TRIP_ROUTINES = 100

    id = db.Column(db.Integer, primary_key=True)
    household_signups_paused = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    signups_paused_message = db.Column(db.String(300), nullable=True)
    announcement = db.Column(db.String(500), nullable=True)
    announcement_level = db.Column(db.String(10), nullable=False, default='info', server_default='info')
    trip_planning_max_days = db.Column(
        db.Integer, nullable=False, default=DEFAULT_TRIP_PLANNING_DAYS, server_default='1800',
    )
    trip_active_routine_limit = db.Column(
        db.Integer, nullable=False, default=DEFAULT_ACTIVE_TRIP_ROUTINES, server_default='25',
    )
    updated_at = db.Column(db.DateTime, nullable=True, default=_utcnow, onupdate=_utcnow)

    def __repr__(self):
        return f'<SiteSettings signups_paused={self.household_signups_paused}>'
