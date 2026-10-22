"""
Shared pytest fixtures for FamilyHQ Finance test suite.

A TEST_DATABASE_URL can select a disposable local PostgreSQL CI database;
otherwise tests use in-memory SQLite. PostgreSQL runs use a unique schema.
A single app context is pushed for the whole session so that SQLAlchemy
objects remain attached throughout.  After each test, clean_db wipes all
rows so tests are fully independent.
"""
import os
import uuid

import pytest
from app import create_app
from config import TestingConfig
from extensions import db as _db
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


# ---------------------------------------------------------------------------
# Application / database lifecycle
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def app():
    """Create the test app, never connecting to a production database."""
    test_url = os.environ.get('TEST_DATABASE_URL')
    admin_engine = None
    schema = None
    old_uri = TestingConfig.SQLALCHEMY_DATABASE_URI
    old_options = TestingConfig.SQLALCHEMY_ENGINE_OPTIONS
    if test_url:
        url = make_url(test_url)
        if (url.drivername != 'postgresql+psycopg'
                or url.host not in ('localhost', '127.0.0.1')
                or not (url.database or '').startswith('joneshq_ci_')
                or url.query):
            raise ValueError('TEST_DATABASE_URL must name a local joneshq_ci_ PostgreSQL database.')
        schema = 'test_' + uuid.uuid4().hex
        admin_engine = create_engine(url)
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        TestingConfig.SQLALCHEMY_DATABASE_URI = test_url
        TestingConfig.SQLALCHEMY_ENGINE_OPTIONS = {
            'connect_args': {'options': f'-csearch_path={schema}'},
        }
    try:
        try:
            application = create_app('testing')
        finally:
            TestingConfig.SQLALCHEMY_DATABASE_URI = old_uri
            TestingConfig.SQLALCHEMY_ENGINE_OPTIONS = old_options
        with application.app_context():
            _db.session.configure(expire_on_commit=False)
            try:
                _db.create_all()
                yield application
            finally:
                _db.session.remove()
                if admin_engine is None:
                    _db.drop_all()
                else:
                    _db.engine.dispose()
    finally:
        if admin_engine is not None:
            with admin_engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin_engine.dispose()


@pytest.fixture(autouse=True)
def clean_db(app):
    """Wipe every table after each test so tests never share state."""
    yield
    _db.session.rollback()
    if _db.engine.dialect.name == 'postgresql':
        tables = ', '.join(f'"{table.name}"' for table in _db.metadata.tables.values())
        _db.session.execute(text(f'TRUNCATE {tables} RESTART IDENTITY CASCADE'))
        _db.session.commit()
        _db.session.remove()
        return
    _db.session.execute(text('PRAGMA foreign_keys = OFF'))
    for table in reversed(list(_db.metadata.tables.values())):
        _db.session.execute(table.delete())
    _db.session.execute(text('PRAGMA foreign_keys = ON'))
    _db.session.commit()
    _db.session.remove()


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
