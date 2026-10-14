import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, request
from flask_login import login_user

from extensions import db
from models.users import User, UserSession
from services.platform.security_event_service import SecurityEventService


TOUCH_INTERVAL = timedelta(seconds=60)
PRUNE_AFTER = timedelta(days=30)

_BROWSERS = (
	('Edg/', 'Edge'), ('OPR/', 'Opera'), ('Firefox/', 'Firefox'), ('FxiOS', 'Firefox'),
	('CriOS', 'Chrome'), ('Chrome/', 'Chrome'), ('Safari/', 'Safari'),
)
_PLATFORMS = (
	('iPhone', 'iPhone'), ('iPad', 'iPad'), ('Android', 'Android'), ('Windows', 'Windows'),
	('Mac OS X', 'macOS'), ('CrOS', 'ChromeOS'), ('Linux', 'Linux'),
)


def _now():
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_token(token):
	return hashlib.sha256(token.encode('utf-8')).hexdigest()


def describe_user_agent(user_agent):
	user_agent = user_agent or ''
	browser = next((name for marker, name in _BROWSERS if marker in user_agent), 'Unknown browser')
	platform = next((name for marker, name in _PLATFORMS if marker in user_agent), 'unknown device')
	return f'{browser} on {platform}'


class UserSessionService:
	"""Revocable server-side login sessions with idle and absolute expiry."""

	@staticmethod
	def _lifetime(remember):
		if remember:
			return current_app.config['REMEMBER_COOKIE_DURATION']
		return timedelta(hours=current_app.config['SESSION_ABSOLUTE_HOURS'])

	@staticmethod
	def _idle_limit():
		return timedelta(minutes=current_app.config['SESSION_IDLE_MINUTES'])

	@staticmethod
	def create(user, remember=False, ip_address=None, user_agent=None):
		"""Create a session record. Returns (record, token); only the hash is stored."""
		now = _now()
		token = secrets.token_urlsafe(32)
		record = UserSession(
			user_id=user.id,
			token_hash=_hash_token(token),
			remember=bool(remember),
			created_at=now,
			last_seen_at=now,
			expires_at=now + UserSessionService._lifetime(remember),
			ip_address=(ip_address or '')[:64] or None,
			user_agent=(user_agent or '')[:255] or None,
			reauthenticated_at=now,
		)
		db.session.add(record)
		UserSession.query.filter(
			UserSession.user_id == user.id,
			(UserSession.expires_at < now - PRUNE_AFTER) | (UserSession.revoked_at < now - PRUNE_AFTER),
		).delete(synchronize_session=False)
		db.session.commit()
		return record, token

	@staticmethod
	def start(user, remember=False, method='password'):
		"""Create a session record for this browser and log the user in with it."""
		record, token = UserSessionService.create(
			user, remember=remember,
			ip_address=request.remote_addr,
			user_agent=request.user_agent.string,
		)
		UserSessionService._attach(user, record, token)
		login_user(user, remember=bool(remember))
		details = method + (', remembered' if remember else '')
		SecurityEventService.record('login_success', user=user, details=details)
		return record

	@staticmethod
	def _attach(user, record, token):
		user._session_token = token
		user._session_id = record.id
		user._session_last_seen = record.last_seen_at
		user._session_reauth_at = record.reauthenticated_at

	@staticmethod
	def is_live(record, now=None):
		now = now or _now()
		if record.revoked_at is not None or now >= record.expires_at:
			return False
		if not record.remember and now - record.last_seen_at > UserSessionService._idle_limit():
			return False
		return True

	@staticmethod
	def load_user(value):
		"""Flask-Login user loader: value is '<user id>:<session token>'."""
		if not isinstance(value, str):
			return None
		user_part, separator, token = value.partition(':')
		if not separator or not token or not user_part.isascii() or not user_part.isdecimal():
			return None
		record = UserSession.query.filter_by(token_hash=_hash_token(token)).first()
		if record is None or record.user_id != int(user_part) or not UserSessionService.is_live(record):
			return None
		user = db.session.get(User, record.user_id)
		if user is None or not user.is_active:
			return None
		UserSessionService._attach(user, record, token)
		return user

	@staticmethod
	def touch(user):
		"""Record activity for the current session, at most once a minute."""
		session_id = getattr(user, '_session_id', None)
		last_seen = getattr(user, '_session_last_seen', None)
		now = _now()
		if session_id is None or (last_seen is not None and now - last_seen < TOUCH_INTERVAL):
			return
		UserSession.query.filter_by(id=session_id).update(
			{UserSession.last_seen_at: now, UserSession.ip_address: (request.remote_addr or '')[:64] or None},
			synchronize_session=False,
		)
		db.session.commit()
		user._session_last_seen = now

	@staticmethod
	def list_active(user):
		now = _now()
		records = (
			UserSession.query
			.filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None), UserSession.expires_at > now)
			.order_by(UserSession.last_seen_at.desc())
			.all()
		)
		current_id = getattr(user, '_session_id', None)
		return [
			{
				'id': record.id,
				'device': describe_user_agent(record.user_agent),
				'ip_address': record.ip_address,
				'created_at': record.created_at,
				'last_seen_at': record.last_seen_at,
				'remember': record.remember,
				'is_current': record.id == current_id,
			}
			for record in records if UserSessionService.is_live(record, now)
		]

	@staticmethod
	def revoke(user, session_id):
		"""Revoke one of the user's sessions. Returns True if it was the current session."""
		updated = (
			UserSession.query
			.filter(UserSession.id == session_id, UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
			.update({UserSession.revoked_at: _now()}, synchronize_session=False)
		)
		if updated != 1:
			db.session.rollback()
			raise ValueError('That session was not found or has already ended.')
		db.session.commit()
		SecurityEventService.record('session_revoked', user=user)
		return session_id == getattr(user, '_session_id', None)

	@staticmethod
	def revoke_current(user):
		session_id = getattr(user, '_session_id', None)
		if session_id is not None:
			UserSession.query.filter(UserSession.id == session_id, UserSession.revoked_at.is_(None)).update(
				{UserSession.revoked_at: _now()}, synchronize_session=False)
			db.session.commit()
			SecurityEventService.record('signed_out', user=user)

	@staticmethod
	def revoke_others(user):
		"""Sign the user out everywhere except this browser. Returns the number revoked."""
		query = UserSession.query.filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
		current_id = getattr(user, '_session_id', None)
		if current_id is not None:
			query = query.filter(UserSession.id != current_id)
		count = query.update({UserSession.revoked_at: _now()}, synchronize_session=False)
		db.session.commit()
		if count:
			SecurityEventService.record('other_sessions_revoked', user=user, details=f'{count} session(s)')
		return count

	@staticmethod
	def revoke_all(user, reason=None):
		count = (
			UserSession.query
			.filter(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
			.update({UserSession.revoked_at: _now()}, synchronize_session=False)
		)
		db.session.commit()
		details = f'{count} session(s)' + (f' - {reason}' if reason else '')
		SecurityEventService.record('all_sessions_revoked', user=user, details=details)
		return count

	@staticmethod
	def is_recently_authenticated(user):
		"""True if the password was entered in this session within REAUTH_WINDOW_MINUTES."""
		reauth_at = getattr(user, '_session_reauth_at', None)
		if reauth_at is None:
			return False
		window = timedelta(minutes=current_app.config['REAUTH_WINDOW_MINUTES'])
		return _now() - reauth_at < window

	@staticmethod
	def mark_reauthenticated(user):
		session_id = getattr(user, '_session_id', None)
		if session_id is None:
			return
		now = _now()
		UserSession.query.filter_by(id=session_id).update(
			{UserSession.reauthenticated_at: now}, synchronize_session=False)
		db.session.commit()
		user._session_reauth_at = now
