"""
Family and FamilyInvite models for multi-user support.
A Family groups users together into a shared data pool.
FamilyInvites are token-based links that allow new members to join.
"""
import secrets
from datetime import datetime, timedelta, timezone
from extensions import db


class Family(db.Model):
    """Represents a household/family sharing a single data pool."""
    __tablename__ = 'families'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default='My Family')
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)

    # Relationships
    members = db.relationship('User', back_populates='family', lazy='dynamic')
    invites = db.relationship('FamilyInvite', back_populates='family',
                              lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Family {self.name}>'


class FamilyInvite(db.Model):
    """One-time invite token for a new family member."""
    __tablename__ = 'family_invites'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)

    # The token sent in the invite link
    token = db.Column(db.String(64), unique=True, nullable=False, index=True,
                      default=lambda: secrets.token_urlsafe(32))

    # What role and name should the new member receive
    role = db.Column(db.String(20), nullable=False, default='member')  # 'admin' | 'member'
    member_name = db.Column(db.String(100), nullable=False)

    # JSON-encoded list of allowed section keys, e.g. '["transactions","income"]'
    # NULL means admin (all sections)
    allowed_sections = db.Column(db.Text, nullable=True)

    # Audit
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False,
                           default=lambda: datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7))
    used_at = db.Column(db.DateTime, nullable=True)
    used_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Relationships
    family = db.relationship('Family', back_populates='invites')
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    used_by = db.relationship('User', foreign_keys=[used_by_id])

    @property
    def is_valid(self):
        """True if the invite has not been used and has not expired."""
        return self.used_at is None and datetime.now(timezone.utc).replace(tzinfo=None) <= self.expires_at

    def mark_used(self, user):
        """Mark this invite as consumed by *user*."""
        self.used_at = datetime.now(timezone.utc).replace(tzinfo=None)
        self.used_by_id = user.id
        db.session.commit()

    def __repr__(self):
        return f'<FamilyInvite {self.token[:8]}… role={self.role}>'
