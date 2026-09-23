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
    if getattr(current_user, 'is_authenticated', False):
        try:
            return current_user.family_id
        except Exception:
            # current_user instance may have been detached from the session
            # (e.g. after db.session.remove()). Re-query to re-attach it.
            from extensions import db
            from models.users import User
            user = db.session.get(User, current_user.get_id())
            return user.family_id if user else None
    return None


def get_current_user_id():
    """Return the current user's id, or ``None`` if not authenticated."""
    if getattr(current_user, 'is_authenticated', False):
        return current_user.id
    return None


# Models whose visibility is inherited from a related parent model rather
# than an `owner_id` column of their own, e.g. a Transaction is private if the
# Account it belongs to is private. Mapping of {model: (fk_column_name, parent_model_loader)}.
# Populated lazily to avoid circular imports at module load time.
_INHERITED_VISIBILITY_MODELS = None


def _inherited_visibility_models():
    global _INHERITED_VISIBILITY_MODELS
    if _INHERITED_VISIBILITY_MODELS is None:
        from models.transactions import Transaction
        from models.pension_snapshots import PensionSnapshot
        from models.accounts import Account
        from models.pensions import Pension
        from models.loan_payments import LoanPayment
        from models.loans import Loan
        from models.credit_card_transactions import CreditCardTransaction
        from models.credit_cards import CreditCard
        from models.fuel import FuelRecord
        from models.trips import Trip
        from models.vehicles import Vehicle
        from models.balances import Balance
        from models.plans import Plan, PlanItem
        _INHERITED_VISIBILITY_MODELS = {
            Transaction: ('account_id', Account),
            PensionSnapshot: ('pension_id', Pension),
            LoanPayment: ('loan_id', Loan),
            CreditCardTransaction: ('credit_card_id', CreditCard),
            FuelRecord: ('vehicle_id', Vehicle),
            Trip: ('vehicle_id', Vehicle),
            Balance: ('account_id', Account),
            PlanItem: ('plan_id', Plan),
        }
    return _INHERITED_VISIBILITY_MODELS


def _apply_visibility(model, query):
    """Restrict *query* to rows visible to the current user.

    A record with ``owner_id`` set is a "private" record only its owner may
    see. ``owner_id`` of ``None`` means the record is shared with the whole
    family. Models without an ``owner_id`` column (e.g. Transaction,
    PensionSnapshot) inherit visibility from a related parent model instead
    (e.g. a Transaction is private only if the Account it belongs to is
    private — a private Income record does NOT hide its deposit transaction
    if the account itself is shared, since shared accounts show every
    transaction in them to the whole family).

    A model could theoretically have both its own ``owner_id`` and an
    inherited parent; if so both checks are combined with AND.
    """
    uid = get_current_user_id()
    conditions = []

    if hasattr(model, 'owner_id'):
        conditions.append((model.owner_id.is_(None)) | (model.owner_id == uid))

    entry = _inherited_visibility_models().get(model)
    if entry:
        fk_name, parent_model = entry
        # Use a correlated subquery (rather than a join) so this doesn't shift
        # the query's implicit entity, which would break callers using
        # .filter_by() afterwards.
        fk_column = getattr(model, fk_name)
        owner_subq = (
            parent_model.query.with_entities(parent_model.owner_id)
            .filter(parent_model.id == fk_column)
            .correlate(model)
            .scalar_subquery()
        )
        conditions.append(
            (fk_column.is_(None)) | (owner_subq.is_(None)) | (owner_subq == uid)
        )

    for condition in conditions:
        query = query.filter(condition)
    return query


def family_query(model):
    """Return a SQLAlchemy query pre-filtered to the current family.

    Also excludes records that are private to another family member (see
    ``_apply_visibility``).

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
    query = model.query.filter_by(family_id=fid)
    return _apply_visibility(model, query)


def family_get(model, record_id):
    """Fetch a single record by *record_id*, scoped to the current family.

    Returns ``None`` if the record does not exist, belongs to another family,
    or is private to another family member.
    """
    fid = get_family_id()
    if fid is None:
        return None
    query = model.query.filter(model.id == record_id, model.family_id == fid)
    return _apply_visibility(model, query).first()


def family_get_or_404(model, record_id):
    """Like ``family_get`` but aborts with 404 if nothing is found."""
    fid = get_family_id()
    if fid is None:
        from flask import abort
        abort(404)
    query = model.query.filter(model.id == record_id, model.family_id == fid)
    return _apply_visibility(model, query).first_or_404()


def set_family_id(obj):
    """Set ``obj.family_id = get_family_id()`` in-place and return *obj*.

    Convenience shorthand when constructing new model instances::

        txn = Transaction(amount=100, ...)
        set_family_id(txn)
        db.session.add(txn)
    """
    obj.family_id = get_family_id()
    return obj
