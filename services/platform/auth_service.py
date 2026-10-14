import re
from datetime import datetime, timezone

from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models.family import Family
from models.users import User
from models.tax_settings import TaxSettings
from services.platform.household_invite_service import HouseholdInviteService


_DUMMY_PASSWORD_HASH = generate_password_hash('not-a-user-password')


class AuthService:
	@staticmethod
	def validate_password_strength(password):
		errors = []
		min_length = current_app.config.get('PASSWORD_MIN_LENGTH', 10)
		if len(password) < min_length:
			errors.append(f"at least {min_length} characters")
		requirements = (
			('PASSWORD_REQUIRE_UPPERCASE', r'[A-Z]', "an uppercase letter"),
			('PASSWORD_REQUIRE_LOWERCASE', r'[a-z]', "a lowercase letter"),
			('PASSWORD_REQUIRE_DIGIT', r'\d', "a number"),
			('PASSWORD_REQUIRE_SPECIAL', r'[!@#$%^&*(),.?":{}|<>]', "a special character (!@#$%^&*(),.?\":{}|<>)"),
		)
		for setting, pattern, message in requirements:
			if current_app.config.get(setting, True) and not re.search(pattern, password):
				errors.append(message)
		if errors:
			return False, f"Password must contain {', '.join(errors)}"
		return True, None

	@staticmethod
	def authenticate(data):
		email = data.get('email', '').strip().lower()
		password = data.get('password', '')
		user = User.query.filter_by(email=email).first()
		if user is None:
			check_password_hash(_DUMMY_PASSWORD_HASH, password)
			raise ValueError('Invalid email or password.')

		password_matches = user.check_password(password)
		if not user.is_active or user.is_locked():
			raise ValueError('Invalid email or password.')
		if not password_matches:
			if user.locked_until is not None:
				user.failed_login_attempts = 0
				user.locked_until = None
			user.record_failed_login()
			raise ValueError('Invalid email or password.')

		user.failed_login_attempts = 0
		user.locked_until = None
		user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
		db.session.commit()
		return user

	@staticmethod
	def registration_is_open():
		return bool(current_app.config.get('ALLOW_OPEN_REGISTRATION'))

	@staticmethod
	def register_household(data):
		"""Register a new household, enforcing a one-time invite unless registration is open."""
		email = (data.get('email') or '').strip().lower()
		invite = None
		if not AuthService.registration_is_open():
			invite = HouseholdInviteService.get_valid_invite(data.get('invite_token'))
			if invite is None:
				raise ValueError('This invite link is invalid, has expired or has already been used.')
			if invite.email and invite.email != email:
				raise ValueError('This invite was issued for a different email address.')

		valid, error = AuthService.validate_password_strength(data.get('password') or '')
		if not valid:
			raise ValueError(error)
		if User.query.filter_by(email=email).first():
			raise ValueError('An account with that email already exists. Please log in.')

		if invite is not None:
			HouseholdInviteService.claim_invite(invite)
		family, user = AuthService._create_household(
			data.get('household_name') or '', email, data.get('name') or '', data.get('password') or ''
		)
		if invite is not None:
			invite.used_by_id = user.id
		db.session.commit()
		return family, user

	@staticmethod
	def register_user(household_name, email, name, password):
		valid, error = AuthService.validate_password_strength(password)
		if not valid:
			raise ValueError(error)
		family, user = AuthService._create_household(household_name, email, name, password)
		db.session.commit()
		return family, user

	@staticmethod
	def _create_household(household_name, email, name, password):
		family = Family(name=household_name.strip())
		db.session.add(family)
		db.session.flush()

		templates = TaxSettings.query.filter_by(family_id=None).all()
		if not templates:
			templates = TaxSettings.query.order_by(
				TaxSettings.family_id.asc(), TaxSettings.tax_year.asc()
			).all()

		seen_tax_years = set()
		for template in templates:
			if template.tax_year in seen_tax_years:
				continue
			seen_tax_years.add(template.tax_year)
			db.session.add(TaxSettings(
				family_id=family.id,
				tax_year=template.tax_year,
				effective_from=template.effective_from,
				effective_to=template.effective_to,
				personal_allowance=template.personal_allowance,
				basic_rate_limit=template.basic_rate_limit,
				higher_rate_limit=template.higher_rate_limit,
				basic_rate=template.basic_rate,
				higher_rate=template.higher_rate,
				additional_rate=template.additional_rate,
				ni_threshold=template.ni_threshold,
				ni_upper_earnings=template.ni_upper_earnings,
				ni_basic_rate=template.ni_basic_rate,
				ni_additional_rate=template.ni_additional_rate,
				is_active=template.is_active,
				notes=template.notes,
			))

		user = User(
			email=email.strip().lower(),
			name=name.strip(),
			family_id=family.id,
			role='admin',
		)
		user.set_password(password)
		db.session.add(user)
		db.session.flush()
		return family, user
