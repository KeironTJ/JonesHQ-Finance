import os
import secrets
from datetime import timedelta


def _env_flag(name, default):
    return os.environ.get(name, default).strip().lower() in ('1', 'true', 'yes')


class Config:
    """Base configuration"""

    @classmethod
    def init_app(cls, app):
        if app.config['TRUSTED_PROXY_COUNT'] < 0:
            raise ValueError("TRUSTED_PROXY_COUNT must not be negative.")
        from utils.proxy_guard import parse_proxy_networks
        parse_proxy_networks(app.config.get('TRUSTED_PROXY_IPS'))
        if app.config['SESSION_IDLE_MINUTES'] < 1 or app.config['SESSION_ABSOLUTE_HOURS'] < 1:
            raise ValueError("SESSION_IDLE_MINUTES and SESSION_ABSOLUTE_HOURS must be at least 1.")
        if app.config['REAUTH_WINDOW_MINUTES'] < 1:
            raise ValueError("REAUTH_WINDOW_MINUTES must be at least 1.")
        if app.config['MAIL_SERVER'] and not app.config['MAIL_FROM']:
            raise ValueError("MAIL_FROM must be set when MAIL_SERVER is configured.")
        if app.config['MAIL_USE_SSL'] and app.config['MAIL_USE_TLS']:
            raise ValueError("Set only one of MAIL_USE_SSL and MAIL_USE_TLS.")

    # Secret key for session management
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    # Database configuration
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(os.path.abspath(os.path.dirname(__file__)), 'instance', 'joneshq_finance.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False  # Set to True for SQL query logging during development
    
    # Session configuration
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    REMEMBER_COOKIE_REFRESH_EACH_REQUEST = False
    # Server-side session limits (non-"remember me" logins); remembered logins
    # last REMEMBER_COOKIE_DURATION. All sessions can be revoked from Account security.
    SESSION_IDLE_MINUTES = int(os.environ.get('SESSION_IDLE_MINUTES', '60'))
    SESSION_ABSOLUTE_HOURS = int(os.environ.get('SESSION_ABSOLUTE_HOURS', '12'))
    # Sensitive actions need the password to have been entered within this many minutes
    REAUTH_WINDOW_MINUTES = int(os.environ.get('REAUTH_WINDOW_MINUTES', '15'))
    SECURITY_EVENT_RETENTION_DAYS = 365
    
    # CSRF Protection
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # No time limit for small user base
    
    # Rate Limiting
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_STRATEGY = 'fixed-window'
    RATELIMIT_HEADERS_ENABLED = True
    RATELIMIT_SWALLOW_ERRORS = False
    RATELIMIT_IN_MEMORY_FALLBACK_ENABLED = False
    TRUSTED_PROXY_COUNT = int(os.environ.get('TRUSTED_PROXY_COUNT', '0'))
    # Comma-separated proxy IPs/CIDRs. When set, only these (and loopback) may connect.
    TRUSTED_PROXY_IPS = os.environ.get('TRUSTED_PROXY_IPS', '')
    
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

    # New households need a one-time invite unless this is explicitly enabled
    ALLOW_OPEN_REGISTRATION = os.environ.get('ALLOW_OPEN_REGISTRATION', 'false').strip().lower() in ('1', 'true', 'yes')
    HOUSEHOLD_INVITE_DAYS = 7

    # Two-factor login
    TWO_FACTOR_ISSUER = 'Family HQ'
    TWO_FACTOR_PENDING_SECONDS = 300
    # Explicit trusted origin; never infer passkey trust from the request Host header.
    PASSKEY_ORIGIN = os.environ.get('PASSKEY_ORIGIN', os.environ.get('APP_BASE_URL', '')).strip().rstrip('/')
    PASSKEY_RP_ID = os.environ.get('PASSKEY_RP_ID', '').strip()

    # Outgoing email (e.g. Resend SMTP). Email features are off until MAIL_SERVER is set.
    MAIL_SERVER = os.environ.get('MAIL_SERVER', '').strip()
    MAIL_PORT = int(os.environ.get('MAIL_PORT', '465'))
    MAIL_USE_SSL = _env_flag('MAIL_USE_SSL', 'true')
    MAIL_USE_TLS = _env_flag('MAIL_USE_TLS', 'false')
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '').strip()
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_FROM = os.environ.get('MAIL_FROM', '').strip()
    MAIL_TIMEOUT_SECONDS = 15
    # Public address used in emailed links, e.g. https://finance.joneshq.co.uk.
    # Never derived from the request Host header, which an attacker can control.
    APP_BASE_URL = os.environ.get('APP_BASE_URL', '').strip().rstrip('/')
    PASSWORD_RESET_MINUTES = 60
    ADMIN_PASSWORD_RESET_HOURS = 24
    EMAIL_VERIFY_DAYS = 3


class DevelopmentConfig(Config):
    """Development configuration"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    # Safe for localhost development, but disable before sharing/deploying
    DEBUG = os.environ.get('FLASK_DEBUG', '0') == '1'
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
    REMEMBER_COOKIE_SECURE = True
    
    # Additional security headers
    PREFERRED_URL_SCHEME = 'https'
    
    # Validate required settings
    @classmethod
    def init_app(cls, app):
        Config.init_app(app)
        
        # Ensure SECRET_KEY is set in production
        if not app.config.get('SECRET_KEY'):
            raise ValueError("SECRET_KEY environment variable must be set in production!")
        if len(app.config['SECRET_KEY']) < 32:
            raise ValueError("SECRET_KEY must contain at least 32 characters in production.")
        if not app.config.get('SQLALCHEMY_DATABASE_URI'):
            raise ValueError("SQLALCHEMY_DATABASE_URI must be set using DATABASE_URL or SQLALCHEMY_DATABASE_URI.")
        storage_uri = app.config.get('RATELIMIT_STORAGE_URI') or ''
        if not storage_uri.startswith(('redis://', 'rediss://')):
            raise ValueError("RATELIMIT_STORAGE_URI must point to a shared Redis backend in production.")
        if app.config.get('MAIL_SERVER') and not app.config.get('APP_BASE_URL', '').startswith('https://'):
            raise ValueError("APP_BASE_URL must be set to your https:// address when email is configured.")
        
        # Warn if using SQLite in production
        if 'sqlite' in app.config.get('SQLALCHEMY_DATABASE_URI', ''):
            import warnings
            warnings.warn("Using SQLite in production is not recommended. Use PostgreSQL or MySQL.")


class TestingConfig(Config):
    """Testing configuration"""
    TESTING = True
    SECRET_KEY = 'test-only-secret-key'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
    RATELIMIT_STORAGE_URI = 'memory://'
    TRUSTED_PROXY_COUNT = 0
    TRUSTED_PROXY_IPS = ''
    # Tests capture email in EmailService's outbox instead of sending it
    MAIL_SERVER = 'smtp.test.invalid'
    MAIL_USE_SSL = True
    MAIL_USE_TLS = False
    MAIL_FROM = 'Family HQ <noreply@example.com>'
    APP_BASE_URL = 'https://finance.example.com'


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}