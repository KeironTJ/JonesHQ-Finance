"""
Shared pytest fixtures for JonesHQ Finance test suite.

All tests run against an in-memory SQLite database (TestingConfig).
A single app context is pushed for the whole session so that SQLAlchemy
objects remain attached throughout.  After each test, clean_db wipes all
rows so tests are fully independent.
"""
import pytest
from app import create_app
from extensions import db as _db


# ---------------------------------------------------------------------------
# Application / database lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def app():
    """Create a test Flask application with an in-memory SQLite database."""
    application = create_app('testing')
    ctx = application.app_context()
    ctx.push()
    _db.create_all()
    yield application
    _db.session.remove()
    _db.drop_all()
    ctx.pop()


@pytest.fixture(autouse=True)
def clean_db(app):
    """Wipe every table after each test so tests never share state."""
    yield
    _db.session.rollback()
    for table in reversed(_db.metadata.sorted_tables):
        _db.session.execute(table.delete())
    _db.session.commit()
    _db.session.expunge_all()


# ---------------------------------------------------------------------------
# Common model helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def family(app):
    from models.family import Family
    f = Family(name='Test Family')
    _db.session.add(f)
    _db.session.commit()
    return f


@pytest.fixture
def user(app, family):
    from models.users import User
    u = User(
        email='admin@example.com',
        name='Admin User',
        family_id=family.id,
        role='admin',
    )
    u.set_password('TestPass1!')
    _db.session.add(u)
    _db.session.commit()
    return u
