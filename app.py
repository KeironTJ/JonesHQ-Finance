import os
from flask import Flask
from config import config
from extensions import db, migrate, login_manager, csrf, limiter


def create_app(config_name=None):
    """Application factory pattern"""
    
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
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
    login_manager.login_view = 'auth.login'
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
    from blueprints.budgets import budgets_bp
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
    
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(budgets_bp)
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
    
    # Add context processors
    @app.context_processor
    def utility_processor():
        from datetime import date, timedelta
        return dict(
            today=lambda: date.today().strftime('%Y-%m-%d'),
            timedelta=timedelta
        )
    
    # Create database tables
    with app.app_context():
        db.create_all()
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)