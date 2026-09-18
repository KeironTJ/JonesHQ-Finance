from extensions import db
from models.family import Family
from models.users import User
from models.tax_settings import TaxSettings


class AuthService:
	@staticmethod
	def register_user(household_name, email, name, password):
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
		db.session.commit()
		return family, user
