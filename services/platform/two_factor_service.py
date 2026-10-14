import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timezone

import pyotp
import qrcode
import qrcode.image.svg
from flask import current_app

from extensions import db
from models.users import User, UserRecoveryCode
from services.platform.security_event_service import SecurityEventService


RECOVERY_CODE_COUNT = 10
TOTP_INTERVAL = 30
INVALID_CODE_MESSAGE = 'That code is not valid. Check the time on your device and try again.'


def _now():
	return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash_recovery_code(code):
	return hashlib.sha256(code.encode('utf-8')).hexdigest()


def _normalise_recovery_code(code):
	return re.sub(r'[\s-]', '', code or '').lower()


class TwoFactorService:
	"""Authenticator-app (TOTP) two-factor login with single-use recovery codes."""

	@staticmethod
	def is_required(user):
		return bool(user.is_site_admin)

	@staticmethod
	def begin_setup(user):
		"""Create a pending secret if none exists. Returns the secret."""
		if user.two_factor_enabled:
			raise ValueError('Two-factor login is already turned on.')
		if not user.totp_secret:
			user.totp_secret = pyotp.random_base32()
			user.totp_last_step = None
			db.session.commit()
		return user.totp_secret

	@staticmethod
	def provisioning_uri(user):
		issuer = current_app.config.get('TWO_FACTOR_ISSUER', 'Family HQ')
		return pyotp.TOTP(user.totp_secret).provisioning_uri(name=user.email, issuer_name=issuer)

	@staticmethod
	def qr_code_svg(uri):
		image = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
		return image.to_string(encoding='unicode')

	@staticmethod
	def _matching_totp_step(user, code):
		code = re.sub(r'\s', '', code or '')
		if not user.totp_secret or not re.fullmatch(r'\d{6}', code):
			return None
		totp = pyotp.TOTP(user.totp_secret, interval=TOTP_INTERVAL)
		current_step = int(time.time()) // TOTP_INTERVAL
		for step in (current_step - 1, current_step, current_step + 1):
			if hmac.compare_digest(totp.at(step * TOTP_INTERVAL), code):
				return step
		return None

	@staticmethod
	def _consume_totp(user, code):
		"""Accept a TOTP code once. The conditional update stops replays and concurrent reuse."""
		step = TwoFactorService._matching_totp_step(user, code)
		if step is None:
			return False
		updated = (
			User.query
			.filter(User.id == user.id)
			.filter((User.totp_last_step.is_(None)) | (User.totp_last_step < step))
			.update({User.totp_last_step: step}, synchronize_session='fetch')
		)
		return updated == 1

	@staticmethod
	def _consume_recovery_code(user, code):
		normalised = _normalise_recovery_code(code)
		if not re.fullmatch(r'[0-9a-f]{16}', normalised):
			return False
		code_hash = _hash_recovery_code(normalised)
		match = None
		for candidate in user.recovery_codes.filter(UserRecoveryCode.used_at.is_(None)).all():
			if hmac.compare_digest(candidate.code_hash, code_hash):
				match = candidate
		if match is None:
			return False
		updated = (
			UserRecoveryCode.query
			.filter(UserRecoveryCode.id == match.id, UserRecoveryCode.used_at.is_(None))
			.update({UserRecoveryCode.used_at: _now()}, synchronize_session='fetch')
		)
		return updated == 1

	@staticmethod
	def _replace_recovery_codes(user):
		user.recovery_codes.delete()
		codes = []
		for _ in range(RECOVERY_CODE_COUNT):
			raw = secrets.token_hex(8)
			db.session.add(UserRecoveryCode(user_id=user.id, code_hash=_hash_recovery_code(raw)))
			codes.append('-'.join(raw[i:i + 4] for i in range(0, 16, 4)))
		return codes

	@staticmethod
	def confirm_setup(user, data):
		"""Turn on two-factor login after the first valid code. Returns new recovery codes."""
		if user.two_factor_enabled:
			raise ValueError('Two-factor login is already turned on.')
		if not user.totp_secret:
			raise ValueError('Start two-factor setup again.')
		if not TwoFactorService._consume_totp(user, data.get('code')):
			db.session.rollback()
			raise ValueError(INVALID_CODE_MESSAGE)
		user.totp_enabled_at = _now()
		codes = TwoFactorService._replace_recovery_codes(user)
		db.session.commit()
		SecurityEventService.record('two_factor_enabled', user=user)
		return codes

	@staticmethod
	def verify_login(user, data):
		"""Check an authenticator or recovery code during login. Returns 'totp' or 'recovery'."""
		if not user.two_factor_enabled:
			raise ValueError('Two-factor login is not turned on for this account.')
		code = data.get('code') or ''
		if TwoFactorService._consume_totp(user, code):
			method = 'totp'
		elif TwoFactorService._consume_recovery_code(user, code):
			method = 'recovery'
		else:
			db.session.rollback()
			SecurityEventService.record('two_factor_failed', user=user)
			raise ValueError(INVALID_CODE_MESSAGE)
		db.session.commit()
		return method

	@staticmethod
	def _check_password(user, password):
		if not password or not user.check_password(password):
			SecurityEventService.record('password_confirm_failed', user=user)
			raise ValueError('Your password was not correct.')

	@staticmethod
	def regenerate_recovery_codes(user, data):
		if not user.two_factor_enabled:
			raise ValueError('Turn on two-factor login first.')
		TwoFactorService._check_password(user, data.get('password'))
		codes = TwoFactorService._replace_recovery_codes(user)
		db.session.commit()
		SecurityEventService.record('recovery_codes_regenerated', user=user)
		return codes

	@staticmethod
	def disable(user, data):
		if not user.two_factor_enabled:
			raise ValueError('Two-factor login is not turned on.')
		if TwoFactorService.is_required(user):
			raise ValueError('Site admins must keep two-factor login turned on.')
		TwoFactorService._check_password(user, data.get('password'))
		TwoFactorService.verify_login(user, data)
		TwoFactorService.reset(user)
		SecurityEventService.record('two_factor_disabled', user=user)

	@staticmethod
	def reset(user):
		"""Remove two-factor login entirely (used by disable and the server reset command)."""
		user.totp_secret = None
		user.totp_enabled_at = None
		user.totp_last_step = None
		user.recovery_codes.delete()
		db.session.commit()

	@staticmethod
	def remaining_recovery_codes(user):
		return user.recovery_codes.filter(UserRecoveryCode.used_at.is_(None)).count()
