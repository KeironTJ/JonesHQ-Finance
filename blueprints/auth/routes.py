"""
Authentication Routes
Login, logout, and user management with security features
"""
from hashlib import sha256
import time

from flask import abort, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import logout_user, current_user, login_required
from flask_limiter.util import get_remote_address
from urllib.parse import unquote, urlsplit
from sqlalchemy.exc import SQLAlchemyError
from . import auth_bp
from .forms import (
    ChangePasswordForm, HouseholdInviteForm, LoginForm, PasswordConfirmForm, ReauthenticateForm,
    RegisterForm, TwoFactorCodeForm,
)
from extensions import db, limiter
from models.users import User
from services.platform.auth_service import AuthService
from services.platform.household_invite_service import HouseholdInviteService
from services.platform.security_event_service import SecurityEventService
from services.platform.two_factor_service import TwoFactorService
from services.platform.user_session_service import UserSessionService
from utils.reauth import recent_auth_required


def _login_account_key():
    email = request.form.get('email', '').strip().lower()
    return sha256(email.encode('utf-8')).hexdigest()


def _safe_next_page():
    target = request.args.get('next', '')
    decoded = unquote(target)
    if (
        not decoded.startswith('/') or decoded.startswith('//')
        or '\\' in decoded or any(ord(char) < 32 or ord(char) == 127 for char in decoded)
    ):
        return url_for('dashboard.index')
    try:
        parsed = urlsplit(decoded)
    except ValueError:
        return url_for('dashboard.index')
    if parsed.scheme or parsed.netloc:
        return url_for('dashboard.index')
    return target


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("20 per hour", key_func=_login_account_key, methods=["POST"])
def login():
    """User login page with security features"""
    # Redirect if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    form = LoginForm()
    
    if form.validate_on_submit():
        try:
            user = AuthService.authenticate({
                'email': form.email.data,
                'password': form.password.data,
            })
        except ValueError as error:
            flash(str(error) or 'Invalid email or password.', 'danger')
        else:
            if user.two_factor_enabled:
                session.pop('2fa_pending', None)
                session['2fa_pending'] = {
                    'user_id': user.id,
                    'remember': bool(form.remember.data),
                    'next': _safe_next_page(),
                    'started': int(time.time()),
                }
                return redirect(url_for('auth.two_factor_login'))
            UserSessionService.start(user, remember=form.remember.data)
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(_safe_next_page())
    
    return render_template('auth/login.html', form=form)


def _pending_two_factor():
    pending = session.get('2fa_pending')
    if not isinstance(pending, dict):
        return None
    max_age = current_app.config.get('TWO_FACTOR_PENDING_SECONDS', 300)
    if int(time.time()) - int(pending.get('started', 0)) > max_age:
        session.pop('2fa_pending', None)
        return None
    return pending


def _two_factor_user_key():
    pending = session.get('2fa_pending')
    if isinstance(pending, dict) and pending.get('user_id'):
        return f"2fa-user:{pending['user_id']}"
    return f"2fa-ip:{get_remote_address()}"


@auth_bp.route('/login/two-factor', methods=['GET', 'POST'])
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("5 per 15 minutes", key_func=_two_factor_user_key, methods=["POST"])
def two_factor_login():
    """Second login step: authenticator or recovery code"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    pending = _pending_two_factor()
    if pending is None:
        flash('Your sign-in has expired. Please log in again.', 'warning')
        return redirect(url_for('auth.login'))

    user = db.session.get(User, pending.get('user_id'))
    if user is None or not user.is_active or user.is_locked() or not user.two_factor_enabled:
        session.pop('2fa_pending', None)
        flash('Please log in again.', 'warning')
        return redirect(url_for('auth.login'))

    form = TwoFactorCodeForm()
    if form.validate_on_submit():
        try:
            method = TwoFactorService.verify_login(user, {'code': form.code.data})
        except ValueError as error:
            flash(str(error) or 'That code is not valid.', 'danger')
        else:
            session.pop('2fa_pending', None)
            UserSessionService.start(user, remember=pending.get('remember', False),
                                     method='recovery code' if method == 'recovery' else 'two-factor')
            flash(f'Welcome back, {user.name}!', 'success')
            if method == 'recovery':
                remaining = TwoFactorService.remaining_recovery_codes(user)
                flash(f'You used a recovery code. {remaining} remaining - generate new ones from Account security if you are running low.', 'warning')
            return redirect(pending.get('next') or url_for('dashboard.index'))

    return render_template('auth/two_factor_login.html', form=form)


@auth_bp.route('/account/security')
@login_required
def account_security():
    return render_template(
        'auth/account_security.html',
        password_form=PasswordConfirmForm(),
        two_factor_required=TwoFactorService.is_required(current_user),
        remaining_codes=TwoFactorService.remaining_recovery_codes(current_user) if current_user.two_factor_enabled else 0,
        sessions=UserSessionService.list_active(current_user),
        change_password_form=ChangePasswordForm(formdata=None),
        events=SecurityEventService.recent_for_user(current_user),
    )


def _current_user_key():
    if current_user.is_authenticated:
        return f"user:{current_user.get_id().split(':', 1)[0]}"
    return f"ip:{get_remote_address()}"


@auth_bp.route('/account/confirm', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per minute", methods=["POST"])
@limiter.limit("5 per 15 minutes", key_func=_current_user_key, methods=["POST"])
def reauthenticate():
    """Ask for the password again before a sensitive action"""
    form = ReauthenticateForm()
    if form.validate_on_submit():
        try:
            AuthService.reauthenticate(current_user, {'password': form.password.data})
        except ValueError as error:
            flash(str(error) or 'Your password was not correct.', 'danger')
        else:
            return redirect(_safe_next_page())
    return render_template('auth/reauthenticate.html', form=form)


@auth_bp.route('/account/security/password', methods=['POST'])
@login_required
@limiter.limit("5 per 15 minutes", key_func=_current_user_key)
def change_password():
    form = ChangePasswordForm()
    if not form.validate_on_submit():
        errors = [message for messages in form.errors.values() for message in messages]
        flash(errors[0] if errors else 'Unable to change your password.', 'danger')
        return redirect(url_for('auth.account_security'))
    try:
        signed_out = AuthService.change_password(current_user, {
            'current_password': form.current_password.data,
            'new_password': form.new_password.data,
            'confirm_password': form.confirm_password.data,
        })
    except ValueError as error:
        flash(str(error) or 'Unable to change your password.', 'danger')
    else:
        message = 'Your password has been changed.'
        if signed_out:
            message += f' {signed_out} other session{"" if signed_out == 1 else "s"} signed out.'
        flash(message, 'success')
    return redirect(url_for('auth.account_security'))


@auth_bp.route('/account/security/sessions/<int:session_id>/revoke', methods=['POST'])
@login_required
@limiter.limit("30 per hour")
def revoke_session(session_id):
    try:
        was_current = UserSessionService.revoke(current_user, session_id)
    except ValueError as error:
        flash(str(error) or 'Unable to sign out that session.', 'danger')
        return redirect(url_for('auth.account_security'))
    if was_current:
        _clear_browser_login()
        flash('You have been signed out.', 'info')
        return redirect(url_for('auth.login'))
    flash('That device has been signed out.', 'success')
    return redirect(url_for('auth.account_security'))


@auth_bp.route('/account/security/sessions/revoke-others', methods=['POST'])
@login_required
@limiter.limit("30 per hour")
def revoke_other_sessions():
    count = UserSessionService.revoke_others(current_user)
    flash(f'Signed out of {count} other session{"" if count == 1 else "s"}.', 'success')
    return redirect(url_for('auth.account_security'))


@auth_bp.route('/account/security/two-factor/setup', methods=['GET', 'POST'])
@login_required
@recent_auth_required
@limiter.limit("10 per minute", methods=["POST"])
def two_factor_setup():
    if current_user.two_factor_enabled:
        return redirect(url_for('auth.account_security'))

    TwoFactorService.begin_setup(current_user)
    form = TwoFactorCodeForm()
    if form.validate_on_submit():
        try:
            codes = TwoFactorService.confirm_setup(current_user, {'code': form.code.data})
        except ValueError as error:
            flash(str(error) or 'That code is not valid.', 'danger')
        else:
            # Sessions that started before 2FA was turned on did not pass a code
            signed_out = UserSessionService.revoke_others(current_user)
            message = 'Two-factor login is now on.'
            if signed_out:
                message += f' {signed_out} other session{"" if signed_out == 1 else "s"} signed out.'
            flash(message, 'success')
            return render_template('auth/recovery_codes.html', codes=codes)

    uri = TwoFactorService.provisioning_uri(current_user)
    return render_template(
        'auth/two_factor_setup.html',
        form=form,
        qr_svg=TwoFactorService.qr_code_svg(uri),
        secret=current_user.totp_secret,
        required=TwoFactorService.is_required(current_user),
    )


@auth_bp.route('/account/security/two-factor/recovery-codes', methods=['POST'])
@login_required
@limiter.limit("5 per 15 minutes")
def two_factor_regenerate_codes():
    form = PasswordConfirmForm()
    if form.validate_on_submit():
        try:
            codes = TwoFactorService.regenerate_recovery_codes(current_user, {'password': form.password.data})
        except ValueError as error:
            flash(str(error) or 'Unable to create new recovery codes.', 'danger')
        else:
            flash('New recovery codes created. Your old codes no longer work.', 'success')
            return render_template('auth/recovery_codes.html', codes=codes)
    else:
        flash('Enter your password to continue.', 'danger')
    return redirect(url_for('auth.account_security'))


@auth_bp.route('/account/security/two-factor/disable', methods=['POST'])
@login_required
@limiter.limit("5 per 15 minutes")
def two_factor_disable():
    form = PasswordConfirmForm()
    if form.validate_on_submit():
        try:
            TwoFactorService.disable(current_user, {'password': form.password.data, 'code': form.code.data})
        except ValueError as error:
            flash(str(error) or 'Unable to turn off two-factor login.', 'danger')
        else:
            flash('Two-factor login has been turned off.', 'success')
    else:
        flash('Enter your password and a code to continue.', 'danger')
    return redirect(url_for('auth.account_security'))


@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per hour", methods=["POST"])
def register():
    """Household registration — requires a one-time invite unless open registration is enabled"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegisterForm()
    if request.method == 'GET':
        form.invite_token.data = request.args.get('invite', '')

    invite = None
    if not AuthService.registration_is_open():
        invite = HouseholdInviteService.get_valid_invite(form.invite_token.data)
        if invite is None:
            return render_template('auth/register.html', form=None, invite_required=True)
        if request.method == 'GET' and invite.email:
            form.email.data = invite.email

    if form.validate_on_submit():
        try:
            family, user = AuthService.register_household({
                'household_name': form.household_name.data,
                'email': form.email.data,
                'name': form.name.data,
                'password': form.password.data,
                'invite_token': form.invite_token.data,
            })
        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Unable to create your account.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Account registration failed.')
            flash('An error occurred while creating your account. Please try again.', 'danger')
        else:
            UserSessionService.start(user, method='registration')
            flash(f'Welcome to {family.name}! Your household has been created.', 'success')
            return redirect(url_for('onboarding.index'))

    return render_template('auth/register.html', form=form, invite=invite)


def _require_site_admin():
    if not current_user.is_site_admin:
        abort(403)


@auth_bp.route('/site-admin/household-invites', methods=['GET', 'POST'])
@login_required
@recent_auth_required
def household_invites():
    """Site-admin page for issuing one-time household invite links"""
    _require_site_admin()
    form = HouseholdInviteForm()
    new_link = None

    if form.validate_on_submit():
        try:
            _, token = HouseholdInviteService.create_invite({
                'email': form.email.data,
                'note': form.note.data,
                'days': form.days.data,
            }, created_by_id=current_user.id)
        except ValueError as error:
            flash(str(error) or 'Unable to create invite.', 'danger')
        else:
            SecurityEventService.record('household_invite_created', details=form.email.data or form.note.data)
            new_link = url_for('auth.register', invite=token, _external=True)
            form = HouseholdInviteForm(formdata=None)

    return render_template(
        'auth/household_invites.html',
        form=form,
        invites=HouseholdInviteService.list_invites(),
        new_link=new_link,
    )


@auth_bp.route('/site-admin/household-invites/<int:invite_id>/revoke', methods=['POST'])
@login_required
@recent_auth_required
def revoke_household_invite(invite_id):
    _require_site_admin()
    try:
        HouseholdInviteService.revoke_invite(invite_id)
    except ValueError as error:
        flash(str(error) or 'Unable to revoke invite.', 'danger')
    else:
        SecurityEventService.record('household_invite_revoked', details=f'invite {invite_id}')
        flash('Invite revoked.', 'success')
    return redirect(url_for('auth.household_invites'))


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """User logout"""
    UserSessionService.revoke_current(current_user)
    _clear_browser_login()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


def _clear_browser_login():
    logout_user()
    remember = session.get('_remember')
    session.clear()
    if remember == 'clear':
        session['_remember'] = 'clear'


@auth_bp.route('/intro')
def intro():
    """Public introduction / landing page"""
    return render_template('public/intro.html')


@auth_bp.route('/help')
def help():
    """Public help / support page"""
    return render_template('public/help.html')
