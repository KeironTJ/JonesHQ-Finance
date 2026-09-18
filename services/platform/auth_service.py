from extensions import db
from models.family import Family
from models.users import User


class AuthService:
	@staticmethod
	def register_user(household_name, email, name, password):
		family = Family(name=household_name.strip())
		db.session.add(family)
		db.session.flush()

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
