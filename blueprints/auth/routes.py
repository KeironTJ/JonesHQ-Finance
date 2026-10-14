"""
Authentication Routes
Login, logout, and user management with security features
"""
from hashlib import sha256

from flask import abort, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, current_user, login_required
from urllib.parse import unquote, urlsplit
from sqlalchemy.exc import SQLAlchemyError
from . import auth_bp
from .forms import HouseholdInviteForm, LoginForm, RegisterForm
from extensions import db, limiter
from services.platform.auth_service import AuthService
from services.platform.household_invite_service import HouseholdInviteService


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
            login_user(user, remember=form.remember.data)
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(_safe_next_page())
    
    return render_template('auth/login.html', form=form)


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
            login_user(user)
            flash(f'Welcome to {family.name}! Your household has been created.', 'success')
            return redirect(url_for('onboarding.index'))

    return render_template('auth/register.html', form=form, invite=invite)


def _require_site_admin():
    if not current_user.is_site_admin:
        abort(403)


@auth_bp.route('/site-admin/household-invites', methods=['GET', 'POST'])
@login_required
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
def revoke_household_invite(invite_id):
    _require_site_admin()
    try:
        HouseholdInviteService.revoke_invite(invite_id)
    except ValueError as error:
        flash(str(error) or 'Unable to revoke invite.', 'danger')
    else:
        flash('Invite revoked.', 'success')
    return redirect(url_for('auth.household_invites'))


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    """User logout"""
    logout_user()
    remember = session.get('_remember')
    session.clear()
    if remember == 'clear':
        session['_remember'] = 'clear'
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/intro')
def intro():
    """Public introduction / landing page"""
    return render_template('public/intro.html')


@auth_bp.route('/help')
def help():
    """Public help / support page"""
    return render_template('public/help.html')
