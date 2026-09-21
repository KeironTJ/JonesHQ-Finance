"""
Permission helpers for section-level access control.

Sections map 1-to-1 to URL prefixes and blueprint groups.  Each section has
a *key* (short string) used as the canonical identifier across the codebase:

    key                URL prefix(es)
    ─────────────────  ────────────────────────────────────────────
    accounts           /accounts
    transactions       /transactions
    expenses           /expenses
    categories         /categories
    vendors            /vendors
    credit_cards       /credit-cards
    loans              /loans
    mortgage           /mortgage
    income             /income
    pensions           /pensions
    networth           /networth
    vehicles           /vehicles, /vehicles/fuel, /vehicles/trips
    childcare          /childcare
    plans              /plans
    settings           /settings            (admin-only by default)
    family             /family              (admin-only by default)

Admin users bypass all section checks.
Members must have the section key listed in their ``allowed_sections`` column.
"""

from flask import request, abort, session
from flask_login import current_user, login_user
from sqlalchemy.orm.exc import DetachedInstanceError

# ── Section registry ──────────────────────────────────────────────────────────

# Maps URL path-prefix → section key.
# Longer/more-specific entries must come first so they match before shorter ones.
SECTION_MAP = [
    ('/credit-cards', 'credit_cards'),
    ('/accounts',     'accounts'),
    ('/transactions', 'transactions'),
    ('/expenses',     'expenses'),
    ('/categories',   'categories'),
    ('/vendors',      'vendors'),
    ('/loans',        'loans'),
    ('/mortgage',     'mortgage'),
    ('/income',       'income'),
    ('/pensions',     'pensions'),
    ('/networth',     'networth'),
    ('/vehicles',     'vehicles'),
    ('/childcare',    'childcare'),
    ('/plans',        'plans'),
    ('/settings',     'settings'),
    ('/family',       'family'),
]

# Section keys that only admins can ever access regardless of allowed_sections
ADMIN_ONLY_SECTIONS = {'settings', 'family'}

# Human-readable labels (used in invite-creation UI)
SECTION_LABELS = {
    'accounts':     'Accounts',
    'transactions': 'Transactions',
    'expenses':     'Work Expenses',
    'categories':   'Categories',
    'vendors':      'Vendors',
    'credit_cards': 'Credit Cards',
    'loans':        'Loans',
    'mortgage':     'Mortgage',
    'income':       'Income',
    'pensions':     'Pensions',
    'networth':     'Net Worth',
    'vehicles':     'Vehicles',
    'childcare':    'Childcare',
    'plans':        'Plans',
}

# Sections grouped for easier nav/checkbox rendering
SECTION_GROUPS = {
    'Banking':      ['accounts', 'transactions', 'expenses', 'categories', 'vendors'],
    'Credit & Debt':['credit_cards', 'loans', 'mortgage'],
    'Wealth':       ['income', 'pensions', 'networth'],
    'Lifestyle':    ['vehicles', 'childcare', 'plans'],
}


def section_for_path(path):
    """Return the section key matching *path*, or ``None`` for un-protected routes."""
    for prefix, key in SECTION_MAP:
        if path == prefix or path.startswith(prefix + '/'):
            return key
    return None


def check_section_access():
    """Call from a ``before_request`` hook to enforce section-level restrictions.

    Does nothing for anonymous users (Flask-Login's own ``login_required``
    handles those). Does nothing for admin users.
    Raises 403 if a member tries to access a forbidden section.
    """
    user = current_user
    try:
        authenticated = user.is_authenticated
    except DetachedInstanceError:
        user_id = session.get('_user_id')
        if not user_id:
            return
        from extensions import db
        from models.users import User
        user = db.session.get(User, int(user_id))
        if user is None:
            return
        login_user(user, fresh=False)
        authenticated = user.is_authenticated

    if not authenticated:
        return  # Flask-Login login_required takes care of this
    if user.is_admin:
        return  # admins have unrestricted access

    section = section_for_path(request.path)
    if section is None:
        return  # dashboard, static files, auth routes – always allowed

    # Members cannot access admin-only sections regardless of their list
    if section in ADMIN_ONLY_SECTIONS:
        abort(403)

    if not user.can_access_section(section):
        abort(403)


def can_access_section(section_key):
    """Template-safe helper – returns True/False for the current user.

    Usage in Jinja2::

        {% if can_access_section('income') %}
            <a href="/income">Income</a>
        {% endif %}
    """
    if not current_user.is_authenticated:
        return False
    return current_user.can_access_section(section_key)
