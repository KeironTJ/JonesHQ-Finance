"""
Tests for multi-family data isolation.

These are the most security-critical tests in the suite.  They verify that
family_query() and family_get() never leak one family's data to another,
and that unauthenticated access yields zero rows.
"""
from decimal import Decimal

import pytest

from extensions import db
from models.accounts import Account
from models.family import Family
from utils.db_helpers import family_query, family_get


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def two_family_ids(app):
    f1 = Family(name='Family One')
    f2 = Family(name='Family Two')
    db.session.add_all([f1, f2])
    db.session.commit()
    return f1.id, f2.id


@pytest.fixture
def patch_family(monkeypatch):
    """Return a helper that re-patches get_family_id within a test."""
    def _set(family_id):
        monkeypatch.setattr('utils.db_helpers.get_family_id', lambda: family_id)
    return _set


def _make_account(family_id, name='Test Account'):
    a = Account(family_id=family_id, name=name, account_type='Current', balance=Decimal('0'))
    db.session.add(a)
    db.session.commit()
    return a


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFamilyQueryIsolation:
    def test_query_returns_own_family_records_only(self, app, two_family_ids, patch_family):
        f1_id, f2_id = two_family_ids
        _make_account(f1_id, name='Family 1 Account')
        _make_account(f2_id, name='Family 2 Account')

        patch_family(f1_id)
        results = family_query(Account).all()
        names = {a.name for a in results}

        assert 'Family 1 Account' in names
        assert 'Family 2 Account' not in names, \
            "family_query must not return another family's records"

    def test_query_excludes_all_records_when_unauthenticated(
        self, app, two_family_ids, patch_family
    ):
        f1_id, _ = two_family_ids
        _make_account(f1_id)

        patch_family(None)  # simulate no logged-in user
        results = family_query(Account).all()

        assert results == [], "Unauthenticated user must see zero records"


class TestFamilyGetIsolation:
    def test_returns_own_family_record(self, app, two_family_ids, patch_family):
        f1_id, _ = two_family_ids
        account = _make_account(f1_id, name='My Account')

        patch_family(f1_id)
        result = family_get(Account, account.id)

        assert result is not None
        assert result.id == account.id

    def test_returns_none_for_other_familys_record(self, app, two_family_ids, patch_family):
        f1_id, f2_id = two_family_ids
        f2_account = _make_account(f2_id, name='Private Account')

        patch_family(f1_id)
        result = family_get(Account, f2_account.id)

        assert result is None, \
            "family_get must return None when the record belongs to a different family"

    def test_returns_none_when_unauthenticated(self, app, two_family_ids, patch_family):
        f1_id, _ = two_family_ids
        account = _make_account(f1_id)

        patch_family(None)
        result = family_get(Account, account.id)

        assert result is None
