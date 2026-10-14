"""
Authentication Routes
Login, logout, and user management with security features
"""
from hashlib import sha256

from flask import render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_user, logout_user, current_user, login_required
from urllib.parse import unquote, urlsplit
from sqlalchemy.exc import SQLAlchemyError
from . import auth_bp
from .forms import LoginForm, RegisterForm
from models.users import User
from extensions import db, limiter
from services.platform.auth_service import AuthService


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
    """Public household registration — creates a new Family + admin User"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = RegisterForm()

    if form.validate_on_submit():
        # Check email is not already taken
        if User.query.filter_by(email=form.email.data.strip().lower()).first():
            flash('An account with that email already exists. Please log in.', 'warning')
            return render_template('auth/register.html', form=form)

        try:
            family, user = AuthService.register_user(
                form.household_name.data,
                form.email.data,
                form.name.data,
                form.password.data,
            )

            # Log the new user in
            login_user(user)
            flash(f'Welcome to {family.name}! Your household has been created.', 'success')
            return redirect(url_for('onboarding.index'))

        except (ValueError, TypeError) as error:
            db.session.rollback()
            flash(str(error) or 'Unable to create your account.', 'danger')
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception('Account registration failed.')
            flash('An error occurred while creating your account. Please try again.', 'danger')

    return render_template('auth/register.html', form=form)


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
