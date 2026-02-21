"""
User Model for Authentication
Simple user authentication for personal use
"""
import json
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


class User(UserMixin, db.Model):
    """User account for authentication"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime)

    # Login security fields
    failed_login_attempts = db.Column(db.Integer, default=0, nullable=False)
    locked_until = db.Column(db.DateTime)

    # Family / multi-user fields
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=True, index=True)
    # 'admin' = full access; 'member' = restricted to allowed_sections
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
        self.last_login = datetime.utcnow()
        db.session.commit()
    
    def is_locked(self):
        """Check if account is locked due to failed login attempts"""
        if self.locked_until and self.locked_until > datetime.utcnow():
            return True
        return False
    
    def record_failed_login(self):
        """Record a failed login attempt and lock if threshold exceeded"""
        from flask import current_app
        self.failed_login_attempts += 1
        
        max_attempts = current_app.config.get('MAX_LOGIN_ATTEMPTS', 5)
        lockout_duration = current_app.config.get('LOCKOUT_DURATION')
        
        if self.failed_login_attempts >= max_attempts and lockout_duration:
            self.locked_until = datetime.utcnow() + lockout_duration
        
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
    def is_admin(self):
        """True if the user has the 'admin' role."""
        return self.role == 'admin'

    def get_allowed_sections(self):
        """Return the set of section keys this user may access.

        Admin users always receive ``None`` (meaning: all sections allowed).
        Members receive a set parsed from the ``allowed_sections`` JSON column.
        """
        if self.is_admin:
            return None  # no restriction
        if not self.allowed_sections:
            return set()
        try:
            return set(json.loads(self.allowed_sections))
        except (ValueError, TypeError):
            return set()

    def can_access_section(self, section_key):
        """Return True if this user may access *section_key*.

        Admins can always access every section.
        Members need *section_key* listed in their ``allowed_sections``.
        """
        if self.is_admin:
            return True
        sections = self.get_allowed_sections()
        return section_key in sections

    def set_allowed_sections(self, sections_iterable):
        """Persist an iterable of section keys as JSON."""
        self.allowed_sections = json.dumps(sorted(set(sections_iterable)))

    def __repr__(self):
        return f'<User {self.email}>'
