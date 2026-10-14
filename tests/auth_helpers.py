"""Test helpers for signing a test client in without going through the login form."""
from flask import g

from extensions import db
from models.users import User
from services.platform.user_session_service import UserSessionService


def login_client(client, user_id, remember=False):
    """Create a real server-side session for user_id and put it in the client's cookie."""
    user = db.session.get(User, user_id)
    _, token = UserSessionService.create(user, remember=remember, user_agent='pytest')
    with client.session_transaction() as session:
        session['_user_id'] = f'{user_id}:{token}'
        session['_fresh'] = True
    # Tests share one app context, so drop any user Flask-Login cached from an earlier request.
    g.pop('_login_user', None)
    return token
