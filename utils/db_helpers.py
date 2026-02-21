"""
Database query helpers for family-scoped multi-tenancy.

All data in this application is scoped to a Family.  Every query against
a data model should go through these helpers so that one family can never
see another family's records.

Usage
-----
In any blueprint route or service function::

    from utils.db_helpers import family_query, family_get_or_404, get_family_id

    # List all accounts belonging to the current family
    accounts = family_query(Account).order_by(Account.name).all()

    # Fetch a single record safely (raises 404 if not found *or* wrong family)
    account = family_get_or_404(Account, account_id)

    # Supply family_id when creating a new record
    acc = Account(name='Savings', family_id=get_family_id())
"""

from flask_login import current_user


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def get_family_id():
    """Return ``current_user.family_id``, or ``None`` if not authenticated."""
    if current_user.is_authenticated:
        return current_user.family_id
    return None


def family_query(model):
    """Return a SQLAlchemy query pre-filtered to the current family.

    Examples::

        family_query(Account).all()
        family_query(Transaction).filter_by(is_paid=True).order_by(...).all()
        family_query(Category).count()
    """
    # Guard: if the model has no family_id column, raise early with a clear message
    if not hasattr(model, 'family_id'):
        raise AttributeError(
            f"family_query() called on {model.__name__} but it has no family_id column. "
            "Add family_id to the model and run the migration script."
        )
    fid = get_family_id()
    if fid is None:
        # Return a query that always yields zero rows rather than leaking data
        return model.query.filter(model.id == -1)
    return model.query.filter_by(family_id=fid)


def family_get(model, record_id):
    """Fetch a single record by *record_id*, scoped to the current family.

    Returns ``None`` if the record does not exist or belongs to another family.
    """
    fid = get_family_id()
    if fid is None:
        return None
    return model.query.filter_by(id=record_id, family_id=fid).first()


def family_get_or_404(model, record_id):
    """Like ``family_get`` but aborts with 404 if nothing is found."""
    fid = get_family_id()
    if fid is None:
        from flask import abort
        abort(404)
    return model.query.filter_by(id=record_id, family_id=fid).first_or_404()


def set_family_id(obj):
    """Set ``obj.family_id = get_family_id()`` in-place and return *obj*.

    Convenience shorthand when constructing new model instances::

        txn = Transaction(amount=100, ...)
        set_family_id(txn)
        db.session.add(txn)
    """
    obj.family_id = get_family_id()
    return obj
