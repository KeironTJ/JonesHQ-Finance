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
        app.logger.info('JonesHQ Finance startup')
    else:
        # Development logging to console
        app.logger.setLevel(logging.DEBUG)
        app.logger.info('JonesHQ Finance startup (DEBUG mode)')


def create_app(config_name=None):
    """Application factory pattern"""
    
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
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
        headers = app.config.get('SECURITY_HEADERS', {})
        for header, value in headers.items():
            response.headers[header] = value
        return response
    
    # Configure Flask-Login
    login_manager.login_view = 'auth.intro'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'
    
    # User loader callback for Flask-Login
    @login_manager.user_loader
    def load_user(user_id):
        from models.users import User
        return User.query.get(int(user_id))
    
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
    from blueprints.expenses import expenses_bp
    from blueprints.family import family_bp
    
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
    app.register_blueprint(expenses_bp)
    app.register_blueprint(family_bp)

    # ── Section-level access enforcement ──────────────────────────────────
    @app.before_request
    def enforce_section_access():
        """Abort 403 when a member tries to access a forbidden section."""
        from utils.permissions import check_section_access
        check_section_access()

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
        )
    
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
                    if hasattr(obj, 'family_id') and obj.family_id is None:
                        obj.family_id = fid
        except RuntimeError:
            pass  # outside request context (e.g. db.create_all() at startup)

    # Create database tables
    with app.app_context():
        db.create_all()

    # Register Flask-Admin (must come after db.init_app and all models are loaded)
    from admin_panel import init_admin
    init_admin(app, db)
    # Flask-Admin generates its own form tokens; exempt its blueprint from
    # Flask-WTF's global CSRF so the two don't conflict.
    csrf.exempt(app.blueprints['admin'])

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


def register_commands(app):
    """Register Flask CLI commands."""

    @app.cli.group()
    def site_admin():
        """Manage site-level admin access to /admin panel."""
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


if __name__ == '__main__':
    app = create_app()
    # SECURITY: Only bind to localhost in development
    # Never use 0.0.0.0 with debug mode - it exposes the debugger to the network
    app.run(host='127.0.0.1', port=5000, debug=True)