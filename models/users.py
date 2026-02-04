"""
User Model for Authentication
Simple user authentication for personal use
"""
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
    
    def __repr__(self):
        return f'<User {self.email}>'
