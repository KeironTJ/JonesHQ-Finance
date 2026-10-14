import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app

from extensions import db
from models.family import HouseholdInvite


def _now():
	return datetime.now(timezone.utc).replace(tzinfo=None)


class HouseholdInviteService:
	"""One-time invites that allow a new household to register."""

	@staticmethod
	def create_invite(data, created_by_id=None):
		"""Create an invite. Returns (invite, token); the token cannot be recovered later."""
		email = (data.get('email') or '').strip().lower() or None
		note = (data.get('note') or '').strip() or None
		if email and ('@' not in email or len(email) > 120):
			raise ValueError('Enter a valid email address, or leave it blank.')
		if note and len(note) > 200:
			raise ValueError('Note must be 200 characters or fewer.')
		days = data.get('days')
		if days is None or days == '':
			days = current_app.config.get('HOUSEHOLD_INVITE_DAYS', 7)
		try:
			days = int(days)
		except (TypeError, ValueError):
			raise ValueError('Expiry must be a whole number of days.')
		if not 1 <= days <= 30:
			raise ValueError('Expiry must be between 1 and 30 days.')

		token = secrets.token_urlsafe(32)
		invite = HouseholdInvite(
			token_hash=HouseholdInvite.hash_token(token),
			email=email,
			note=note,
			created_by_id=created_by_id,
			expires_at=_now() + timedelta(days=days),
		)
		db.session.add(invite)
		db.session.commit()
		return invite, token

	@staticmethod
	def get_valid_invite(token):
		if not token or len(token) > 200:
			return None
		invite = HouseholdInvite.query.filter_by(token_hash=HouseholdInvite.hash_token(token)).first()
		if invite is None or not invite.is_valid:
			return None
		return invite

	@staticmethod
	def claim_invite(invite):
		"""Atomically mark an invite used (without committing) so it cannot be redeemed twice."""
		now = _now()
		claimed = (
			HouseholdInvite.query
			.filter(
				HouseholdInvite.id == invite.id,
				HouseholdInvite.used_at.is_(None),
				HouseholdInvite.revoked_at.is_(None),
				HouseholdInvite.expires_at >= now,
			)
			.update({HouseholdInvite.used_at: now}, synchronize_session='fetch')
		)
		if claimed != 1:
			raise ValueError('This invite link is invalid, has expired or has already been used.')

	@staticmethod
	def list_invites():
		return HouseholdInvite.query.order_by(HouseholdInvite.created_at.desc()).all()

	@staticmethod
	def revoke_invite(invite_id):
		invite = db.session.get(HouseholdInvite, invite_id)
		if invite is None:
			raise ValueError('Invite not found.')
		if invite.status != 'active':
			raise ValueError('Only active invites can be revoked.')
		invite.revoked_at = _now()
		db.session.commit()
		return invite
