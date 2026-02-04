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
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # No time limit for small user base
    
    # Rate Limiting
    RATELIMIT_STORAGE_URL = 'memory://'
    RATELIMIT_STRATEGY = 'fixed-window'
    RATELIMIT_HEADERS_ENABLED = True
    
    # Security Headers
    SECURITY_HEADERS = {
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'X-Content-Type-Options': 'nosniff',
        'X-Frame-Options': 'SAMEORIGIN',
        'X-XSS-Protection': '1; mode=block',
        'Referrer-Policy': 'strict-origin-when-cross-origin'
    }
    
    # Flask-Migrate configuration
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }
    
    # Password Requirements
    PASSWORD_MIN_LENGTH = 10
    PASSWORD_REQUIRE_UPPERCASE = True
    PASSWORD_REQUIRE_LOWERCASE = True
    PASSWORD_REQUIRE_DIGIT = True
    PASSWORD_REQUIRE_SPECIAL = True
    
    # Login Security
    MAX_LOGIN_ATTEMPTS = 5
    LOCKOUT_DURATION = timedelta(minutes=15)


class DevelopmentConfig(Config):
    """Development configuration"""
    # Safe for localhost development, but disable before sharing/deploying
    DEBUG = True  # Convenient for local development
    SQLALCHEMY_ECHO = False  # Set to True only when debugging SQL queries
    
    # SECURITY: Only safe because Flask binds to 127.0.0.1 by default
    # Never use --host=0.0.0.0 with debug mode enabled
    # Never share screenshots showing debugger PIN


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    
    # MUST set these environment variables in production
    SECRET_KEY = os.environ.get('SECRET_KEY')  # Generate with: python -c 'import secrets; print(secrets.token_hex(32))'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or os.environ.get('SQLALCHEMY_DATABASE_URI')
    
    # Security settings for production
    SESSION_COOKIE_SECURE = True  # Requires HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    
    # Additional security headers
    PREFERRED_URL_SCHEME = 'https'
    
    # Validate required settings
    @classmethod
    def init_app(cls, app):
        Config.init_app(app)
        
        # Ensure SECRET_KEY is set in production
        if not app.config.get('SECRET_KEY'):
            raise ValueError("SECRET_KEY environment variable must be set in production!")
        
        # Warn if using SQLite in production
        if 'sqlite' in app.config.get('SQLALCHEMY_DATABASE_URI', ''):
            import warnings
            warnings.warn("Using SQLite in production is not recommended. Use PostgreSQL or MySQL.")


# Add init_app to base config
Config.init_app = classmethod(lambda cls, app: None)


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