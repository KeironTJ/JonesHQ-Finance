"""
User Model for Authentication
Simple user authentication for personal use
"""
import json
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone


class User(UserMixin, db.Model):
    """User account for authentication"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    onboarding_version = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default='0',
    )
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    last_login = db.Column(db.DateTime)

    # Login security fields
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)

    # Set when the user proves they own their email address (verification or reset link)
    email_verified_at = db.Column(db.DateTime, nullable=True)

    # Service operator ("site admin"): the /site-admin area. Granted only on the server
    # (flask site-admin grant). Unrelated to 'role', which is a household-level concept.
    is_site_admin = db.Column(db.Boolean, default=False, server_default='0', nullable=False)

    # Two-factor login (TOTP). A secret without totp_enabled_at is a pending setup.
    totp_secret = db.Column(db.String(64), nullable=True)
    totp_enabled_at = db.Column(db.DateTime, nullable=True)
    # Last accepted 30-second time step, so a code cannot be replayed
    totp_last_step = db.Column(db.Integer, nullable=True)
    recovery_codes = db.relationship('UserRecoveryCode', back_populates='user',
                                     lazy='dynamic', cascade='all, delete-orphan')
    sessions = db.relationship('UserSession', back_populates='user',
                               lazy='dynamic', cascade='all, delete-orphan')

    # Family / multi-user fields
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    default_account_id = db.Column(
        db.Integer,
        db.ForeignKey(
            'accounts.id',
            name='fk_users_default_account',
            ondelete='SET NULL',
            use_alter=True,
        ),
        nullable=True,
    )
    # Household role. 'admin' is shown as "Owner" (full access to their own household);
    # 'member' is restricted to allowed_sections. The stored value stays 'admin'.
    role = db.Column(db.String(20), nullable=False, default='admin')
    # Display name that maps to 'assigned_to' values in transaction data
    member_name = db.Column(db.String(100), nullable=True)
    # JSON list of section keys this member may access, e.g. '["transactions","income"]'
    # NULL / empty means all sections (used automatically for admins)
    allowed_sections = db.Column(db.Text, nullable=True)

    # Relationship back to Family
    family = db.relationship('Family', back_populates='members', foreign_keys=[family_id])
    
    def set_password(self, password):
        """Hash and set the user's password"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """Check if provided password matches the hash"""
        return check_password_hash(self.password_hash, password)
    
    def update_last_login(self):
        """Update the last login timestamp"""
        self.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
    
    def is_locked(self):
        """Check if account is locked due to failed login attempts"""
        if self.locked_until and self.locked_until > datetime.now(timezone.utc).replace(tzinfo=None):
            return True
        return False
    
    def record_failed_login(self):
        """Record a failed login attempt and lock if threshold exceeded"""
        from flask import current_app
        self.failed_login_attempts += 1
        
        max_attempts = current_app.config.get('MAX_LOGIN_ATTEMPTS', 5)
        lockout_duration = current_app.config.get('LOCKOUT_DURATION')
        
        if self.failed_login_attempts >= max_attempts and lockout_duration:
            self.locked_until = datetime.now(timezone.utc).replace(tzinfo=None) + lockout_duration
        
        db.session.commit()
    
    def reset_failed_logins(self):
        """Reset failed login attempts after successful login"""
        self.failed_login_attempts = 0
        self.locked_until = None
        db.session.commit()

    # ------------------------------------------------------------------
    # Family / permissions helpers
    # ------------------------------------------------------------------

    @property
    def is_household_owner(self):
        """True for a household owner (stored role 'admin'). Not the same as is_site_admin."""
        return self.role == 'admin'

    @property
    def two_factor_enabled(self):
        return self.totp_enabled_at is not None and bool(self.totp_secret)

    def get_id(self):
        # Flask-Login stores this in the session and remember cookie; the token ties
        # the login to a revocable UserSession row.
        token = getattr(self, '_session_token', None)
        return f'{self.id}:{token}' if token else str(self.id)

    def get_allowed_sections(self):
        """Return the set of section keys this user may access.

        Household owners always receive ``None`` (meaning: all sections allowed).
        Members receive a set parsed from the ``allowed_sections`` JSON column.
        """
        if self.is_household_owner:
            return None  # no restriction
        if not self.allowed_sections:
            return set()
        try:
            return set(json.loads(self.allowed_sections))
        except (ValueError, TypeError):
            return set()

    def can_access_section(self, section_key):
        """Return True if this user may access *section_key*.

        Household owners can always access every section.
        Members need *section_key* listed in their ``allowed_sections``.
        """
        if self.is_household_owner:
            return True
        sections = self.get_allowed_sections()
        return section_key in sections

    def set_allowed_sections(self, sections_iterable):
        """Persist an iterable of section keys as JSON."""
        self.allowed_sections = json.dumps(sorted(set(sections_iterable)))

    def __repr__(self):
        return f'<User {self.email}>'


class UserSession(db.Model):
    """Server-side record of one signed-in browser. Only a SHA-256 hash of the token is stored."""
    __tablename__ = 'user_sessions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    remember = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False)
    last_seen_at = db.Column(db.DateTime, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    revoked_at = db.Column(db.DateTime, nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    # Last time the password was entered in this session; sensitive actions need it to be recent
    reauthenticated_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', back_populates='sessions')

    def __repr__(self):
        return f'<UserSession {self.id} user={self.user_id}>'


class SecurityEvent(db.Model):
    """Audit trail of sign-ins and security-relevant account changes."""
    __tablename__ = 'security_events'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id', ondelete='SET NULL'), nullable=True, index=True)
    event_type = db.Column(db.String(50), nullable=False, index=True)
    details = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, index=True,
                           default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    user = db.relationship('User')

    def __repr__(self):
        return f'<SecurityEvent {self.event_type} user={self.user_id}>'


class UserRecoveryCode(db.Model):
    """Single-use two-factor recovery code. Only a SHA-256 hash is stored."""
    __tablename__ = 'user_recovery_codes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    code_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', back_populates='recovery_codes')

    def __repr__(self):
        return f'<UserRecoveryCode {self.id} user={self.user_id}>'
