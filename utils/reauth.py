"""Require a recent password confirmation before sensitive actions."""
from functools import wraps
from urllib.parse import urlsplit

from flask import flash, redirect, request, url_for
from flask_login import current_user

from services.platform.user_session_service import UserSessionService


def _return_path():
    """Where to send the user after confirming. POSTs can't be replayed, so go back to the referring page."""
    if request.method == 'GET':
        return request.full_path.rstrip('?')
    referrer = urlsplit(request.referrer or '')
    if referrer.netloc == request.host and referrer.path.startswith('/') and not referrer.path.startswith('//'):
        return referrer.path + (f'?{referrer.query}' if referrer.query else '')
    return url_for('auth.account_security')


def reauthentication_redirect():
    flash('Please confirm your password to continue.', 'info')
    return redirect(url_for('auth.reauthenticate', next=_return_path()))


def recent_auth_required(view):
    """Use after @login_required. Asks for the password if it wasn't entered recently."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user.is_authenticated and not UserSessionService.is_recently_authenticated(current_user):
            return reauthentication_redirect()
        return view(*args, **kwargs)
    return wrapped
