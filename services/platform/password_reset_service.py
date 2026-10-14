import hmac
import time
from datetime import datetime, timezone
from hashlib import sha256

from flask import current_app
from itsdangerous import BadSignature, URLSafeTimedSerializer

from extensions import db
from models.users import User
from services.platform.email_service import EmailService
from services.platform.security_event_service import SecurityEventService
from services.platform.user_session_service import UserSessionService


INVALID_LINK = 'This reset link is invalid, has expired or has already been used.'


def _now():
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _serializer():
	return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='password-reset')


def _password_fingerprint(user):
	# Changes whenever the password changes, so each link works only once.
	return sha256(user.password_hash.encode('utf-8')).hexdigest()[:20]


class PasswordResetService:
	"""Signed, single-use password reset links."""

	@staticmethod
	def create_token(user, minutes, emailed=True):
		return _serializer().dumps({
			'u': user.id,
			'p': _password_fingerprint(user),
			'm': int(minutes),
			'e': 1 if emailed else 0,
		})

	@staticmethod
	def _load(token):
		if not token or len(token) > 500:
			return None, None
		try:
			data, signed_at = _serializer().loads(token, return_timestamp=True)
		except BadSignature:
			return None, None
		if not isinstance(data, dict):
			return None, None
		age = time.time() - signed_at.timestamp()
		if age < 0 or age > int(data.get('m', 0)) * 60:
			return None, None
		user = db.session.get(User, data.get('u'))
		if user is None or not user.is_active:
			return None, None
		if not hmac.compare_digest(_password_fingerprint(user), str(data.get('p', ''))):
			return None, None
		return user, data

	@staticmethod
	def get_user(token):
		"""The active user a valid, unused reset token belongs to, otherwise None."""
		return PasswordResetService._load(token)[0]

	@staticmethod
	def request_reset(data):
		"""Email a reset link if the address belongs to an active account.

		The caller must respond the same way either way so accounts can't be discovered.
		"""
		email = (data.get('email') or '').strip().lower()
		user = User.query.filter_by(email=email).first() if email else None
		if user is None or not user.is_active or not EmailService.is_configured():
			return False
		minutes = current_app.config.get('PASSWORD_RESET_MINUTES', 60)
		link = EmailService.external_url(
			'auth.reset_password_token', token=PasswordResetService.create_token(user, minutes))
		EmailService.send(user.email, 'Reset your Family HQ password', 'password_reset',
		                  user=user, link=link, minutes=minutes)
		SecurityEventService.record('password_reset_requested', user=user)
		return True

	@staticmethod
	def create_admin_link(email):
		"""Reset link for the server admin to pass on by hand. Returns (user, link, hours)."""
		user = User.query.filter_by(email=(email or '').strip().lower()).first()
		if user is None:
			raise ValueError(f'No user found with email {email}')
		if not user.is_active:
			raise ValueError(f'{user.email} is deactivated.')
		hours = current_app.config.get('ADMIN_PASSWORD_RESET_HOURS', 24)
		link = EmailService.external_url(
			'auth.reset_password_token',
			token=PasswordResetService.create_token(user, hours * 60, emailed=False))
		SecurityEventService.record('password_reset_link_created', user=user, details='server command')
		return user, link, hours

	@staticmethod
	def reset_password(token, data):
		"""Set a new password from a reset link and sign out everywhere. Returns the user."""
		from services.platform.auth_service import AuthService

		user, payload = PasswordResetService._load(token)
		if user is None:
			raise ValueError(INVALID_LINK)
		new_password = data.get('new_password') or ''
		if new_password != (data.get('confirm_password') or ''):
			raise ValueError('The passwords do not match.')
		valid, error = AuthService.validate_password_strength(new_password)
		if not valid:
			raise ValueError(error)

		user.set_password(new_password)
		user.failed_login_attempts = 0
		user.locked_until = None
		if payload.get('e') and user.email_verified_at is None:
			user.email_verified_at = _now()
		db.session.commit()
		UserSessionService.revoke_all(user, reason='password reset')
		SecurityEventService.record('password_reset', user=user)
		return user
