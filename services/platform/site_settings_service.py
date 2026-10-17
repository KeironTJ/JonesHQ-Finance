from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.site_settings import SiteSettings

DEFAULT_PAUSED_MESSAGE = 'New household sign-ups are paused at the moment. Please try again later.'


class SiteSettingsService:
    """Operator-managed, service-wide switches (site admin only; not household data)."""

    @staticmethod
    def get():
        """Return the settings row, or an unsaved row with defaults if none exists yet."""
        settings = db.session.get(SiteSettings, 1)
        if settings is None:
            settings = SiteSettings(id=1, household_signups_paused=False, announcement_level='info')
        return settings

    @staticmethod
    def get_safely():
        """For page rendering: never let a settings lookup break a page."""
        try:
            return SiteSettingsService.get()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Could not load site settings.')
            return None

    @staticmethod
    def update(data):
        """Update the switches from a plain dict. Returns the list of changed field names."""
        paused = data.get('household_signups_paused') in (True, 'y', 'on', 'true', '1')
        paused_message = (data.get('signups_paused_message') or '').strip() or None
        announcement = (data.get('announcement') or '').strip() or None
        level = (data.get('announcement_level') or 'info').strip()

        if paused_message and len(paused_message) > 300:
            raise ValueError('The sign-up paused message must be 300 characters or fewer.')
        if announcement and len(announcement) > 500:
            raise ValueError('The announcement must be 500 characters or fewer.')
        if level not in SiteSettings.ANNOUNCEMENT_LEVELS:
            raise ValueError('Choose a valid announcement style.')

        settings = db.session.get(SiteSettings, 1)
        if settings is None:
            settings = SiteSettings(id=1, household_signups_paused=False, announcement_level='info')
            db.session.add(settings)

        new_values = {
            'household_signups_paused': paused,
            'signups_paused_message': paused_message,
            'announcement': announcement,
            'announcement_level': level,
        }
        changed = [field for field, value in new_values.items() if getattr(settings, field) != value]
        for field, value in new_values.items():
            setattr(settings, field, value)
        db.session.commit()

        if changed:
            from services.platform.security_event_service import SecurityEventService
            SecurityEventService.record('site_settings_updated', details=', '.join(changed))
        return changed

    @staticmethod
    def household_signups_paused():
        settings = SiteSettingsService.get()
        return bool(settings.household_signups_paused)

    @staticmethod
    def signups_paused_message():
        return SiteSettingsService.get().signups_paused_message or DEFAULT_PAUSED_MESSAGE

    @staticmethod
    def ensure_household_signups_open():
        if SiteSettingsService.household_signups_paused():
            raise ValueError(SiteSettingsService.signups_paused_message())
