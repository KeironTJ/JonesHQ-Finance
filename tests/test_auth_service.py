from extensions import db
from models.family import Family
from models.users import User
from services.auth_service import AuthService


def test_register_user_creates_family_and_admin(app):
    family, user = AuthService.register_user(
        'Jones Household',
        'ADMIN@EXAMPLE.COM',
        'Admin User',
        'TestPass1!',
    )

    assert family.name == 'Jones Household'
    assert user.family_id == family.id
    assert user.role == 'admin'
    assert user.email == 'admin@example.com'
    assert user.check_password('TestPass1!') is True
    assert db.session.get(Family, family.id) is family
    assert db.session.get(User, user.id) is user
