"""
Family and FamilyInvite models for multi-user support.
A Family groups users together into a shared data pool.
FamilyInvites are token-based links that allow new members to join.
"""
import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
from extensions import db


class Family(db.Model):
    """Represents a household/family sharing a single data pool."""
    __tablename__ = 'families'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default='My Family')
    onboarding_version = db.Column(
        db.Integer,
        nullable=False,
        default=0,
        server_default='0',
    )
    setup_progress = db.Column(
        db.JSON,
        nullable=False,
        default=dict,
        server_default='{}',
    )
    rewards_board_enabled = db.Column(
        db.Boolean, nullable=False, default=False, server_default=db.false(),
    )
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)

    # Relationships
    members = db.relationship(
        'User', secondary='household_memberships', back_populates='families',
        lazy='dynamic', overlaps='memberships,family,user',
    )
    memberships = db.relationship(
        'HouseholdMembership', back_populates='family',
        cascade='all, delete-orphan',
    )
    invites = db.relationship('FamilyInvite', back_populates='family',
                              lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Family {self.name}>'


class HouseholdMembership(db.Model):
    """A user's role and Finance permissions within one household."""
    __tablename__ = 'household_memberships'
    __table_args__ = (
        db.UniqueConstraint('user_id', 'family_id', name='uq_household_membership_user_family'),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    family_id = db.Column(
        db.Integer, db.ForeignKey('families.id', ondelete='CASCADE'),
        nullable=False, index=True,
    )
    role = db.Column(db.String(20), nullable=False, default='member')
    member_name = db.Column(db.String(100), nullable=True)
    allowed_sections = db.Column(db.Text, nullable=True)
    allowed_modules = db.Column(
        db.JSON, nullable=False, default=lambda: ['finance', 'household'],
        server_default='["finance", "household"]',
    )
    created_at = db.Column(
        db.DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )

    user = db.relationship('User', back_populates='memberships', overlaps='families,members')
    family = db.relationship('Family', back_populates='memberships', overlaps='families,members')

    def get_allowed_sections(self):
        if self.role == 'admin':
            return None
        if not self.allowed_sections:
            return set()
        try:
            return set(json.loads(self.allowed_sections))
        except (ValueError, TypeError):
            return set()

    def __repr__(self):
        return f'<HouseholdMembership user={self.user_id} family={self.family_id}>'


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


class HouseholdInvite(db.Model):
    """One-time invite allowing a new household to register.

    Only a SHA-256 hash of the token is stored, so database access alone
    cannot be used to redeem an invite.
    """
    __tablename__ = 'household_invites'

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), nullable=True)
    note = db.Column(db.String(200), nullable=True)

    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    used_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    used_by = db.relationship('User', foreign_keys=[used_by_id])

    @staticmethod
    def hash_token(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    @property
    def status(self):
        if self.used_at is not None:
            return 'used'
        if self.revoked_at is not None:
            return 'revoked'
        if datetime.now(timezone.utc).replace(tzinfo=None) > self.expires_at:
            return 'expired'
        return 'active'

    @property
    def is_valid(self):
        return self.status == 'active'

    def __repr__(self):
        return f'<HouseholdInvite {self.id} {self.status}>'
