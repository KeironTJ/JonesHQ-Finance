import os
import logging
import click
from logging.handlers import RotatingFileHandler
from flask import Flask
from flask_wtf.csrf import CSRFError
from config import config
from extensions import db, migrate, login_manager, csrf, limiter


def configure_logging(app):
    """Configure application logging"""
    if not app.debug and not app.testing:
        # Create logs directory if it doesn't exist
        if not os.path.exists('logs'):
            os.mkdir('logs')
        
        # File handler for errors
        file_handler = RotatingFileHandler(
            'logs/joneshq_finance.log',
            maxBytes=10240000,  # 10MB
            backupCount=10
        )
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s %(levelname)s: %(message)s '
            '[in %(pathname)s:%(lineno)d]'
        ))
        file_handler.setLevel(logging.INFO)
        app.logger.addHandler(file_handler)
        
        app.logger.setLevel(logging.INFO)
        app.logger.info('Family HQ startup')
    else:
        # Development logging to console
        app.logger.setLevel(logging.DEBUG)
        app.logger.info('Family HQ startup (DEBUG mode)')


def create_app(config_name=None):
    """Application factory pattern"""
    
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    config[config_name].init_app(app)

    from utils.proxy_guard import wrap_wsgi_app
    wrap_wsgi_app(app)

    # Ensure Jinja template edits are picked up immediately in development.
    if app.debug or app.config.get('TESTING'):
        app.config['TEMPLATES_AUTO_RELOAD'] = True
    
    # Configure logging
    configure_logging(app)
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    
    # Add security headers
    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses"""
        from flask import request

        headers = app.config.get('SECURITY_HEADERS', {})
        for header, value in headers.items():
            response.headers[header] = value
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response
    
    # Configure Flask-Login
    login_manager.login_view = 'auth.intro'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    # User loader callback for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from services.platform.user_session_service import UserSessionService
        return UserSessionService.load_user(user_id)

    @app.before_request
    def refresh_user_session():
        from flask import request
        from flask_login import current_user
        if request.endpoint in ('static', 'auth.health'):
            return
        if current_user.is_authenticated:
            from services.platform.user_session_service import UserSessionService
            UserSessionService.touch(current_user)
    
    # Import models to ensure they're registered with SQLAlchemy
    with app.app_context():
        import models
    
    # Register blueprints
    from blueprints.auth import auth_bp
    from blueprints.dashboard import dashboard_bp
    from blueprints.accounts import accounts_bp
    from blueprints.transactions import transactions_bp
    from blueprints.categories import bp as categories_bp
    from blueprints.vendors import bp as vendors_bp
    from blueprints.loans import loans_bp
    from blueprints.credit_cards import credit_cards_bp
    from blueprints.vehicles import vehicles_bp
    from blueprints.childcare import childcare_bp
    from blueprints.pensions import pensions_bp
    from blueprints.income import income_bp
    from blueprints.mortgage import mortgage_bp
    from blueprints.networth import networth_bp
    from blueprints.settings import settings_bp
    from blueprints.preferences import preferences_bp
    from blueprints.expenses import expenses_bp
    from blueprints.family import family_bp
    from blueprints.plans import plans_bp
    from blueprints.onboarding import onboarding_bp
    from blueprints.site_admin import site_admin_bp
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(loans_bp, url_prefix='/loans')
    app.register_blueprint(credit_cards_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(childcare_bp)
    app.register_blueprint(pensions_bp)
    app.register_blueprint(income_bp)
    app.register_blueprint(mortgage_bp)
    app.register_blueprint(networth_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(preferences_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(family_bp)
    app.register_blueprint(plans_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(site_admin_bp)

    # ── Section-level access enforcement ──────────────────────────────────
    @app.before_request
    def enforce_section_access():
        """Abort 403 when a member tries to access a forbidden section."""
        from flask import request
        if request.endpoint == 'auth.health':
            return
        from utils.permissions import check_section_access
        check_section_access()

    # Site admins must have two-factor login before using the app
    _two_factor_exempt_endpoints = {
        'auth.storage_notice', 'auth.privacy_notice',
        'static', 'auth.logout', 'auth.account_security', 'auth.two_factor_setup',
        'auth.revoke_session', 'auth.revoke_other_sessions', 'auth.reauthenticate',
        'auth.verify_email', 'auth.resend_verification', 'auth.reset_password', 'auth.reset_password_token',
    }

    @app.before_request
    def require_site_admin_two_factor():
        from flask import redirect, request, url_for
        from flask_login import current_user
        if request.endpoint == 'auth.health':
            return
        if (
            current_user.is_authenticated
            and current_user.is_site_admin
            and not current_user.two_factor_enabled
            and request.endpoint not in _two_factor_exempt_endpoints
        ):
            return redirect(url_for('auth.two_factor_setup'))

    # ── Jinja2 custom filter ────────────────────────────────────────────
    import json as _json

    @app.template_filter('from_json')
    def from_json_filter(value):
        """Parse a JSON string in templates, returning [] on failure."""
        if not value:
            return []
        try:
            return _json.loads(value)
        except (ValueError, TypeError):
            return []
    
    # Add context processors
    @app.context_processor
    def utility_processor():
        from datetime import date, timedelta
        from utils.permissions import can_access_section
        return dict(
            today=lambda: date.today().strftime('%Y-%m-%d'),
            timedelta=timedelta,
            can_access_section=can_access_section,
            site_settings_banner=_site_settings_banner,
        )

    def _site_settings_banner():
        from services.platform.site_settings_service import SiteSettingsService
        settings = SiteSettingsService.get_safely()
        if settings is None or not settings.announcement:
            return None
        return {'text': settings.announcement, 'level': settings.announcement_level}
    
    # ── Auto-set family_id on every new record ─────────────────────────────
    from sqlalchemy import event as _sa_event

    @_sa_event.listens_for(db.session, 'before_flush')
    def _auto_family_id(session, flush_context, instances):
        """Automatically stamp family_id on any new record that has the column
        but no value, using the currently logged-in user's family."""
        try:
            from flask_login import current_user
            if current_user and current_user.is_authenticated and current_user.family_id:
                fid = current_user.family_id
                for obj in session.new:
                    if getattr(obj, '_global_record', False):
                        continue
                    if hasattr(obj, 'family_id') and obj.family_id is None:
                        obj.family_id = fid
        except RuntimeError:
            pass  # outside request context (e.g. db.create_all() at startup)

    # Registered after the auto-stamp so new records already have family_id.
    from utils.tenancy_guard import register_cross_family_guard
    register_cross_family_guard(db)
    # Register Flask-Admin (must come after db.init_app and all models are loaded)
    from admin_panel import init_admin
    init_admin(app, db)
    # Flask-Admin views use their own SecureForm CSRF tokens (admin_panel.OperatorView);
    # exempt its blueprint from Flask-WTF's global CSRF so the two don't conflict.
    csrf.exempt(app.blueprints['admin'])

    @app.route('/admin', strict_slashes=False)
    def legacy_admin_redirect():
        from flask import redirect, url_for
        return redirect(url_for('site_admin.index'))

    # Register error handlers
    register_error_handlers(app)

    # Register CLI commands
    register_commands(app)

    return app


def register_error_handlers(app):
    """Register global error handlers"""
    
    @app.errorhandler(404)
    def not_found_error(error):
        from flask import render_template
        return render_template('errors/404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        from flask import render_template
        db.session.rollback()
        app.logger.error(f'Internal Server Error: {error}')
        return render_template('errors/500.html'), 500
    
    @app.errorhandler(403)
    def forbidden_error(error):
        from flask import render_template
        return render_template('errors/403.html'), 403
    
    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        from flask import render_template, flash
        from flask_wtf.csrf import CSRFError
        flash('CSRF token validation failed. Please try again.', 'danger')
        return render_template('errors/csrf.html', reason=error.description), 400

    from utils.tenancy_guard import CrossFamilyReferenceError

    @app.errorhandler(CrossFamilyReferenceError)
    def handle_cross_family_reference(error):
        # The guard aborted the flush; discard the partial unit of work and send the user back.
        from urllib.parse import urlsplit
        from flask import flash, redirect, request, url_for
        db.session.rollback()
        flash(str(error), 'danger')
        target = url_for('dashboard.index')
        referrer = urlsplit(request.referrer or '')
        if referrer.netloc == request.host and referrer.path.startswith('/'):
            target = referrer.path + (f'?{referrer.query}' if referrer.query else '')
        return redirect(target)


def register_commands(app):
    """Register Flask CLI commands."""

    @app.cli.group('maintenance')
    def maintenance_cli():
        """Server-only retention maintenance."""
        pass

    @maintenance_cli.command('cleanup')
    @click.option('--dry-run', is_flag=True, help='Count eligible records without deleting them.')
    def cleanup_retained_records(dry_run):
        """Remove security events and expired/revoked sessions beyond retention."""
        from sqlalchemy.exc import SQLAlchemyError
        from services.platform.retention_service import RetentionService
        try:
            counts = RetentionService.cleanup(dry_run=dry_run)
        except ValueError as error:
            raise click.ClickException(str(error)) from error
        except SQLAlchemyError as error:
            raise click.ClickException(
                'Retention cleanup failed; no changes were committed. Check database availability and logs.'
            ) from error
        click.echo('Preview only; no records deleted.' if dry_run else 'Retention cleanup completed.')
        for name, count in counts.items():
            click.echo(f'{name}: {count}')

    @maintenance_cli.command('check-tenancy')
    def check_tenancy():
        """Read-only: report records that reference another household's records."""
        from utils.tenancy_guard import find_cross_family_references
        violations = find_cross_family_references(db)
        db.session.rollback()
        if not violations:
            click.echo('Household isolation check passed: no cross-household references.')
            return
        click.echo('Cross-household references found (table.column: rows):')
        for name, count in sorted(violations.items()):
            click.echo(f'{name}: {count}')
        raise SystemExit(1)

    @maintenance_cli.command('purge-orphan-income-forecasts')
    @click.option('--apply', is_flag=True, help='Delete the records (default is a preview).')
    @click.option('--family', 'family_id', type=int, help='Limit to one household id.')
    def purge_orphan_income_forecasts(apply, family_id):
        """Remove future income forecasts left behind by deleted templates."""
        from services.finance.income_service import IncomeService
        groups = IncomeService.purge_orphaned_forecasts(dry_run=not apply, family_id=family_id)
        if not groups:
            click.echo('No orphaned income forecasts found.')
            return
        for g in groups:
            click.echo(f"family {g['family_id']}: {g['person']} / {g['source'] or '-'}: "
                       f"{g['count']} records {g['first']} -> {g['last']} "
                       f"({g['with_transactions']} with forecast transactions)")
        click.echo('Deleted.' if apply else 'Preview only; re-run with --apply to delete.')

    @app.cli.command('health')
    def health_check():
        """Check database and rate-limit storage without exposing settings."""
        from services.platform.health_service import HealthService
        checks = HealthService.check()
        for name, healthy in checks.items():
            click.echo(f'{name}: {"OK" if healthy else "FAILED"}')
        click.echo('Email delivery is not checked; use flask email test ADDRESS.')
        if not all(checks.values()):
            raise SystemExit(1)

    @app.cli.group()
    def site_admin():
        """Manage site admin (service operator) access to the /site-admin area."""
        pass

    @site_admin.command('grant')
    @click.argument('email')
    def grant_site_admin(email):
        """Grant /admin panel access to a user by EMAIL."""
        from models.users import User
        user = User.query.filter_by(email=email).first()
        if not user:
            click.echo(f'ERROR: No user found with email "{email}"', err=True)
            return
        if user.is_site_admin:
            click.echo(f'"{user.name}" ({email}) already has site admin access.')
            return
        user.is_site_admin = True
        db.session.commit()
        click.echo(f'SUCCESS: "{user.name}" ({email}) granted site admin access.')

    @site_admin.command('revoke')
    @click.argument('email')
    def revoke_site_admin(email):
        """Revoke /admin panel access from a user by EMAIL."""
        from models.users import User
        user = User.query.filter_by(email=email).first()
        if not user:
            click.echo(f'ERROR: No user found with email "{email}"', err=True)
            return
        if not user.is_site_admin:
            click.echo(f'"{user.name}" ({email}) does not have site admin access.')
            return
        user.is_site_admin = False
        db.session.commit()
        click.echo(f'SUCCESS: Site admin access revoked from "{user.name}" ({email}).')

    @site_admin.command('list')
    def list_site_admins():
        """List all users with site admin access."""
        from models.users import User
        admins = User.query.filter_by(is_site_admin=True).all()
        if not admins:
            click.echo('No site admins found.')
            return
        click.echo(f'{"ID":<5} {"Name":<25} {"Email":<40} {"Active":<8}')
        click.echo('-' * 80)
        for u in admins:
            click.echo(f'{u.id:<5} {u.name:<25} {u.email:<40} {str(u.is_active):<8}')

    @app.cli.group('household-invite')
    def household_invite():
        """Manage one-time invites for new households."""
        pass

    @household_invite.command('create')
    @click.option('--email', default='', help='Only allow this email address to register.')
    @click.option('--note', default='', help='Reminder of who the invite is for.')
    @click.option('--days', default=7, show_default=True, help='Days until the link expires (1-30).')
    @click.option('--base-url', default='', help='Public site address, e.g. https://finance.example.com')
    def create_household_invite(email, note, days, base_url):
        """Create a one-time household invite link."""
        from services.platform.household_invite_service import HouseholdInviteService
        try:
            invite, token = HouseholdInviteService.create_invite({'email': email, 'note': note, 'days': days})
        except ValueError as error:
            click.echo(f'ERROR: {error}', err=True)
            raise SystemExit(1)
        click.echo(f'Invite {invite.id} created, expires {invite.expires_at:%d %b %Y %H:%M} UTC.')
        click.echo('Send this link (shown once only):')
        click.echo(f'{base_url.rstrip("/")}/register?invite={token}')

    @household_invite.command('list')
    def list_household_invites():
        """List household invites."""
        from services.platform.household_invite_service import HouseholdInviteService
        invites = HouseholdInviteService.list_invites()
        if not invites:
            click.echo('No household invites found.')
            return
        click.echo(f'{"ID":<5} {"Status":<9} {"Email":<35} {"Expires":<18} Note')
        for invite in invites:
            click.echo(f'{invite.id:<5} {invite.status:<9} {(invite.email or "Any"):<35} '
                       f'{invite.expires_at:%d %b %Y %H:%M}  {invite.note or ""}')

    @household_invite.command('revoke')
    @click.argument('invite_id', type=int)
    def revoke_household_invite(invite_id):
        """Revoke an active household invite by ID."""
        from services.platform.household_invite_service import HouseholdInviteService
        try:
            HouseholdInviteService.revoke_invite(invite_id)
        except ValueError as error:
            click.echo(f'ERROR: {error}', err=True)
            raise SystemExit(1)
        click.echo(f'Invite {invite_id} revoked.')

    @app.cli.group('two-factor')
    def two_factor():
        """Manage two-factor login."""
        pass

    @two_factor.command('reset')
    @click.argument('email')
    def reset_two_factor(email):
        """Turn off two-factor login for a user who has lost their device and recovery codes."""
        from models.users import User
        from services.platform.two_factor_service import TwoFactorService
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            click.echo(f'ERROR: No user found with email {email}', err=True)
            raise SystemExit(1)
        TwoFactorService.reset(user)
        from services.platform.security_event_service import SecurityEventService
        from services.platform.user_session_service import UserSessionService
        SecurityEventService.record('two_factor_reset', user=user)
        UserSessionService.revoke_all(user, reason='two-factor reset')
        note = ' They are a site admin, so they will be asked to set it up again at next login.' if user.is_site_admin else ''
        click.echo(f'Two-factor login reset and all sessions signed out for {user.email}.{note}')

    @app.cli.group('sessions')
    def sessions_cli():
        """Manage signed-in sessions."""
        pass

    @sessions_cli.command('revoke')
    @click.argument('email')
    def revoke_user_sessions(email):
        """Sign a user out of every browser and device."""
        from models.users import User
        from services.platform.user_session_service import UserSessionService
        user = User.query.filter_by(email=email.strip().lower()).first()
        if not user:
            click.echo(f'ERROR: No user found with email {email}', err=True)
            raise SystemExit(1)
        count = UserSessionService.revoke_all(user, reason='server command')
        click.echo(f'Signed {user.email} out of {count} session(s).')

    @app.cli.group('email')
    def email_cli():
        """Outgoing email."""
        pass

    @email_cli.command('test')
    @click.argument('address')
    def send_test_email(address):
        """Send a test email to check the MAIL_* settings."""
        from services.platform.email_service import EmailService
        if not EmailService.is_configured():
            click.echo('ERROR: Email is not configured. Set MAIL_SERVER and MAIL_FROM.', err=True)
            raise SystemExit(1)
        try:
            EmailService.send(address, 'Family HQ test email', 'test', wait=True,
                              base_url=app.config.get('APP_BASE_URL'))
        except Exception as error:
            click.echo(f'ERROR: Sending failed: {error}', err=True)
            raise SystemExit(1)
        click.echo(f'Test email sent to {address} via {app.config["MAIL_SERVER"]}.')

    @app.cli.group('users')
    def users_cli():
        """Manage user accounts."""
        pass

    @users_cli.command('reset-link')
    @click.argument('email')
    def user_reset_link(email):
        """Create a password reset link to pass on to a user yourself."""
        from services.platform.password_reset_service import PasswordResetService
        try:
            user, link, hours = PasswordResetService.create_admin_link(email)
        except ValueError as error:
            click.echo(f'ERROR: {error}', err=True)
            raise SystemExit(1)
        click.echo(f'Password reset link for {user.email} (works once, expires in {hours} hours):')
        click.echo(link)
        click.echo('Send it to them privately. Two-factor login, if on, is still required afterwards.')


if __name__ == '__main__':
    app = create_app()
    # SECURITY: Only bind to localhost in development
    # Never use 0.0.0.0 with debug mode - it exposes the debugger to the network
    app.run(host='127.0.0.1', port=5000, debug=True)