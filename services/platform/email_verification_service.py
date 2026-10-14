import hmac
from datetime import datetime, timezone
from hashlib import sha256

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from extensions import db
from models.users import User
from services.platform.email_service import EmailService
from services.platform.security_event_service import SecurityEventService


def _now():
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _serializer():
	return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt='email-verify')


def _email_fingerprint(email):
	return sha256((email or '').strip().lower().encode('utf-8')).hexdigest()[:20]


class EmailVerificationService:
	"""Signed links that prove a user owns their email address."""

	@staticmethod
	def create_token(user):
		return _serializer().dumps({'u': user.id, 'e': _email_fingerprint(user.email)})

	@staticmethod
	def send_verification(user):
		"""Email a verification link. Returns False if already verified or email is off."""
		if user.email_verified_at is not None or not EmailService.is_configured():
			return False
		days = current_app.config.get('EMAIL_VERIFY_DAYS', 3)
		link = EmailService.external_url('auth.verify_email', token=EmailVerificationService.create_token(user))
		return EmailService.send(user.email, 'Confirm your Family HQ email address', 'verify_email',
		                         user=user, link=link, days=days)

	@staticmethod
	def verify(token):
		"""Mark the email verified. Returns the user; raises ValueError for a bad or expired link."""
		if not token or len(token) > 500:
			raise ValueError('This verification link is not valid.')
		max_age = current_app.config.get('EMAIL_VERIFY_DAYS', 3) * 86400
		try:
			data = _serializer().loads(token, max_age=max_age)
		except SignatureExpired:
			raise ValueError('This verification link has expired. Send a new one from Account security.')
		except BadSignature:
			raise ValueError('This verification link is not valid.')
		user = db.session.get(User, data.get('u')) if isinstance(data, dict) else None
		if user is None or not hmac.compare_digest(_email_fingerprint(user.email), str(data.get('e', ''))):
			raise ValueError('This verification link is not valid.')
		if user.email_verified_at is None:
			user.email_verified_at = _now()
			db.session.commit()
			SecurityEventService.record('email_verified', user=user)
		return user
