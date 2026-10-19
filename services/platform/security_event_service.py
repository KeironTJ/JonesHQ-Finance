from datetime import datetime, timedelta, timezone

from flask import current_app, has_request_context, request
from flask_login import current_user
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.users import SecurityEvent


EVENT_LABELS = {
	'passkey_added': 'Passkey added',
	'passkey_removed': 'Passkey removed',
	'passkey_failed': 'Failed passkey verification',
	'passkey_reauthenticated': 'Confirmed identity with a passkey',
	'passkeys_reset': 'Passkeys reset by the server admin',
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
	'household_deleted': 'Household deleted; login account retained',
	'password_reset_requested': 'Password reset email requested',
	'password_reset': 'Password reset with a reset link',
	'password_reset_link_created': 'Password reset link created by the server admin',
	'email_verified': 'Email address verified',
	'data_exported': 'Downloaded a data export',
	'account_deactivated': 'Account deactivated by the service operator',
	'account_reactivated': 'Account reactivated by the service operator',
	'account_unlocked': 'Sign-in lockout cleared by the service operator',
	'site_settings_updated': 'Site settings changed by the service operator',
}

# Events that also send the user an email, with the alert subject.
ALERT_SUBJECTS = {
	'passkey_added': 'A passkey was added to your Family HQ account',
	'passkey_removed': 'A passkey was removed from your Family HQ account',
	'passkeys_reset': 'Passkeys were reset for your Family HQ account',
	'login_success': 'New sign-in to your Family HQ account',
	'password_changed': 'Your Family HQ password was changed',
	'password_reset': 'Your Family HQ password was reset',
	'two_factor_enabled': 'Two-factor login turned on for Family HQ',
	'two_factor_disabled': 'Two-factor login turned off for Family HQ',
	'two_factor_reset': 'Two-factor login reset for Family HQ',
	'recovery_codes_regenerated': 'New Family HQ recovery codes created',
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
		user_agent = ((request.user_agent.string or '')[:255] or None) if in_request else None
		try:
			send_alert = SecurityEventService._should_alert(event_type, user, details, user_agent)
		except SQLAlchemyError:
			db.session.rollback()
			send_alert = False
		try:
			db.session.add(SecurityEvent(
				user_id=getattr(user, 'id', None),
				family_id=getattr(user, 'family_id', None),
				event_type=event_type,
				details=(details or '')[:255] or None,
				ip_address=((request.remote_addr or '')[:64] or None) if in_request else None,
				user_agent=user_agent,
				created_at=_now(),
			))
			if event_type == 'login_success':
				SecurityEventService._prune()
			db.session.commit()
		except SQLAlchemyError:
			db.session.rollback()
			current_app.logger.exception('Failed to record security event %s', event_type)
		if send_alert:
			SecurityEventService._send_alert(event_type, user, user_agent, in_request)

	@staticmethod
	def _should_alert(event_type, user, details, user_agent):
		if event_type not in ALERT_SUBJECTS or not getattr(user, 'email', None):
			return False
		if event_type != 'login_success':
			return True
		# Only alert for a browser this user hasn't signed in from before, and not on their first sign-in.
		if (details or '').startswith(('registration', 'family invite')):
			return False
		previous = SecurityEvent.query.filter_by(user_id=user.id, event_type='login_success')
		if previous.first() is None:
			return False
		return previous.filter(SecurityEvent.user_agent == user_agent).first() is None

	@staticmethod
	def _send_alert(event_type, user, user_agent, in_request):
		from services.platform.email_service import EmailService
		from services.platform.user_session_service import describe_user_agent
		try:
			if not EmailService.is_configured():
				return
			EmailService.send(
				user.email, ALERT_SUBJECTS[event_type], 'security_alert',
				user=user,
				label=EVENT_LABELS[event_type],
				when=_now(),
				device=describe_user_agent(user_agent) if user_agent else None,
				ip_address=(request.remote_addr if in_request else None),
				security_link=EmailService.external_url('auth.account_security'),
			)
		except Exception:
			current_app.logger.exception('Failed to send security alert %s', event_type)

	@staticmethod
	def _prune(dry_run=False, now=None):
		days = current_app.config.get('SECURITY_EVENT_RETENTION_DAYS', 365)
		if not isinstance(days, int) or isinstance(days, bool) or days < 1:
			raise ValueError('SECURITY_EVENT_RETENTION_DAYS must be a positive integer.')
		query = SecurityEvent.query.filter(
			SecurityEvent.created_at < (now or _now()) - timedelta(days=days))
		return query.count() if dry_run else query.delete(synchronize_session=False)

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
