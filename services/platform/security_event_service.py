from datetime import datetime, timedelta, timezone

from flask import current_app, has_request_context, request
from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.users import SecurityEvent


EVENT_LABELS = {
	'login_success': 'Signed in',
	'login_failed': 'Failed sign-in attempt',
	'account_locked': 'Account temporarily locked',
	'two_factor_failed': 'Wrong two-factor code',
	'signed_out': 'Signed out',
	'session_revoked': 'Signed out a device',
	'other_sessions_revoked': 'Signed out all other devices',
	'all_sessions_revoked': 'Signed out everywhere',
	'reauthenticated': 'Confirmed password',
	'password_confirm_failed': 'Wrong password when confirming',
	'password_changed': 'Password changed',
	'two_factor_enabled': 'Two-factor login turned on',
	'two_factor_disabled': 'Two-factor login turned off',
	'two_factor_reset': 'Two-factor login reset by the server admin',
	'recovery_codes_regenerated': 'New recovery codes created',
	'household_invite_created': 'Household invite created',
	'household_invite_revoked': 'Household invite revoked',
	'family_invite_created': 'Family invite created',
	'family_invite_revoked': 'Family invite revoked',
	'family_member_updated': 'Family member permissions changed',
	'family_member_removed': 'Family member removed',
}


def _now():
	return datetime.now(timezone.utc).replace(tzinfo=None)


class SecurityEventService:
	"""Append-only audit trail for sign-ins and security-relevant changes."""

	@staticmethod
	def record(event_type, user=None, details=None):
		"""Record an event. Defaults to the signed-in user; never raises."""
		if event_type not in EVENT_LABELS:
			raise ValueError(f'Unknown security event type: {event_type}')
		in_request = has_request_context()
		if user is None and in_request and current_user.is_authenticated:
			user = current_user
		try:
			db.session.add(SecurityEvent(
				user_id=getattr(user, 'id', None),
				family_id=getattr(user, 'family_id', None),
				event_type=event_type,
				details=(details or '')[:255] or None,
				ip_address=((request.remote_addr or '')[:64] or None) if in_request else None,
				user_agent=((request.user_agent.string or '')[:255] or None) if in_request else None,
				created_at=_now(),
			))
			if event_type == 'login_success':
				SecurityEventService._prune()
			db.session.commit()
		except SQLAlchemyError:
			db.session.rollback()
			current_app.logger.exception('Failed to record security event %s', event_type)

	@staticmethod
	def _prune():
		days = current_app.config.get('SECURITY_EVENT_RETENTION_DAYS', 365)
		SecurityEvent.query.filter(SecurityEvent.created_at < _now() - timedelta(days=days)).delete(
			synchronize_session=False)

	@staticmethod
	def recent_for_user(user, limit=20):
		from services.platform.user_session_service import describe_user_agent
		events = (
			SecurityEvent.query
			.filter(SecurityEvent.user_id == user.id)
			.order_by(SecurityEvent.created_at.desc(), SecurityEvent.id.desc())
			.limit(limit)
			.all()
		)
		return [
			{
				'label': EVENT_LABELS.get(event.event_type, event.event_type),
				'event_type': event.event_type,
				'details': event.details,
				'created_at': event.created_at,
				'ip_address': event.ip_address,
				'device': describe_user_agent(event.user_agent) if event.user_agent else None,
			}
			for event in events
		]
