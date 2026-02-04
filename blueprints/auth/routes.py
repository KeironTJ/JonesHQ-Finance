"""
Authentication Routes
Login, logout, and user management with security features
"""
from flask import render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from urllib.parse import urlparse
from datetime import datetime, timedelta
from . import auth_bp
from .forms import LoginForm
from models.users import User
from extensions import db

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://"
)


@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")  # Rate limit login attempts
def login():
    """User login page with security features"""
    # Redirect if already logged in
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    
    form = LoginForm()
    
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        password = form.password.data
        remember = form.remember.data
        
        # Find user
        user = User.query.filter_by(email=email).first()
        
        if user:
            # Check if account is locked
            if user.is_locked():
                minutes_left = int((user.locked_until - datetime.utcnow()).total_seconds() / 60) + 1
                flash(f'Account temporarily locked due to multiple failed login attempts. Try again in {minutes_left} minutes.', 'danger')
                return render_template('auth/login.html', form=form)
            
            # Check if user is active
            if not user.is_active:
                flash('This account has been deactivated. Please contact support.', 'danger')
                return render_template('auth/login.html', form=form)
            
            # Check password
            if user.check_password(password):
                # Successful login
                login_user(user, remember=remember)
                user.update_last_login()
                user.reset_failed_logins()
                
                flash(f'Welcome back, {user.name}!', 'success')
                
                # Redirect to next page or dashboard
                next_page = request.args.get('next')
                if not next_page or urlparse(next_page).netloc != '':
                    next_page = url_for('dashboard.index')
                
                return redirect(next_page)
            else:
                # Failed login - record attempt
                user.record_failed_login()
                remaining = max(0, 5 - user.failed_login_attempts)
                if remaining > 0:
                    flash(f'Invalid email or password. {remaining} attempts remaining before lockout.', 'danger')
                else:
                    flash('Account locked due to too many failed attempts.', 'danger')
        else:
            # User not found - generic error to prevent user enumeration
            flash('Invalid email or password.', 'danger')
    
    return render_template('auth/login.html', form=form)


@auth_bp.route('/logout')
def logout():
    """User logout"""
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('auth.login'))
