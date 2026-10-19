from extensions import db


class UserPasskey(db.Model):
    __tablename__ = 'user_passkeys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    credential_id = db.Column(db.String(1400), nullable=False, unique=True)
    public_key = db.Column(db.LargeBinary, nullable=False)
    sign_count = db.Column(db.BigInteger, nullable=False, default=0)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    last_used_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship('User', back_populates='passkeys')


class PasskeyChallenge(db.Model):
    """Short-lived, browser-bound challenges, consumed atomically before verification."""
    __tablename__ = 'passkey_challenges'

    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True)
    challenge = db.Column(db.LargeBinary, nullable=False)
    purpose = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)
    context = db.Column(db.JSON, nullable=False)

    user = db.relationship('User', back_populates='passkey_challenges')
