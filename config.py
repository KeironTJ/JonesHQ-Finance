import os
from datetime import timedelta


class Config:
    """Base configuration"""
    
    # Secret key for session management
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance', 'joneshq_finance.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False  # Set to True for SQL query logging during development
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    
    # Flask-Migrate configuration
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }


class DevelopmentConfig(Config):
    """Development configuration"""
    # Safe for localhost development, but disable before sharing/deploying
    DEBUG = True  # Convenient for local development
    SQLALCHEMY_ECHO = True  # Set to True only when debugging SQL queries
    
    # SECURITY: Only safe because Flask binds to 127.0.0.1 by default
    # Never use --host=0.0.0.0 with debug mode enabled
    # Never share screenshots showing debugger PIN


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    # Override with production database URL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    
    # Security settings for production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}