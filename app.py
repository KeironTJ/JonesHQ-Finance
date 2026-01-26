import os
from flask import Flask
from config import config
from extensions import db, migrate


def create_app(config_name=None):
    """Application factory pattern"""
    
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Import models to ensure they're registered with SQLAlchemy
    with app.app_context():
        import models
    
    # Register blueprints
    from blueprints.dashboard import dashboard_bp
    from blueprints.accounts import accounts_bp
    from blueprints.transactions import transactions_bp
    from blueprints.categories import bp as categories_bp
    from blueprints.vendors import bp as vendors_bp
    from blueprints.budgets import budgets_bp
    from blueprints.loans import loans_bp
    from blueprints.vehicles import vehicles_bp
    from blueprints.childcare import childcare_bp
    from blueprints.pensions import pensions_bp
    from blueprints.mortgage import mortgage_bp
    from blueprints.networth import networth_bp
    
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(accounts_bp)
    app.register_blueprint(transactions_bp)
    app.register_blueprint(categories_bp)
    app.register_blueprint(vendors_bp)
    app.register_blueprint(budgets_bp)
    app.register_blueprint(loans_bp)
    app.register_blueprint(vehicles_bp)
    app.register_blueprint(childcare_bp)
    app.register_blueprint(pensions_bp)
    app.register_blueprint(mortgage_bp)
    app.register_blueprint(networth_bp)
    
    # Create database tables
    with app.app_context():
        db.create_all()
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)