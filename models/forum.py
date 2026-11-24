from datetime import datetime, timezone

from extensions import db


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ForumCategory(db.Model):
    __tablename__ = 'forum_categories'
    __table_args__ = (db.UniqueConstraint('family_id', 'name', name='uq_forum_category_name'),)

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    name = db.Column(db.String(80), nullable=False)


class ForumTopic(db.Model):
    __tablename__ = 'forum_topics'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    category_id = db.Column(db.Integer, db.ForeignKey('forum_categories.id'), nullable=True, index=True)
    creator_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True,
    )
    title = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_now)
    updated_at = db.Column(db.DateTime, nullable=False, default=_now, index=True)
    pinned = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    locked = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    category = db.relationship('ForumCategory')
    creator = db.relationship('HouseholdMembership')
    posts = db.relationship('ForumPost', back_populates='topic', cascade='all, delete-orphan')


class ForumPost(db.Model):
    __tablename__ = 'forum_posts'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('forum_topics.id', ondelete='CASCADE'), nullable=False, index=True)
    creator_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True,
    )
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=_now)
    edited_at = db.Column(db.DateTime, nullable=True)
    pinned = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    topic = db.relationship('ForumTopic', back_populates='posts')
    creator = db.relationship('HouseholdMembership')
    attachments = db.relationship('ForumAttachment', cascade='all, delete-orphan', back_populates='post')
    reactions = db.relationship('ForumReaction', cascade='all, delete-orphan', back_populates='post')
    notifications = db.relationship('ForumNotification', cascade='all, delete-orphan', back_populates='post')
    mentions = db.relationship('ForumMention', cascade='all, delete-orphan', back_populates='post')


class ForumAttachment(db.Model):
    __tablename__ = 'forum_attachments'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('forum_posts.id', ondelete='CASCADE'), nullable=False, index=True)
    filename = db.Column(db.String(255), nullable=False)
    content = db.Column(db.LargeBinary, nullable=False)
    post = db.relationship('ForumPost', back_populates='attachments')


class ForumReaction(db.Model):
    __tablename__ = 'forum_reactions'
    __table_args__ = (db.UniqueConstraint('post_id', 'membership_id', name='uq_forum_reaction_member'),)

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('forum_posts.id', ondelete='CASCADE'), nullable=False, index=True)
    membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    post = db.relationship('ForumPost', back_populates='reactions')


class ForumNotification(db.Model):
    __tablename__ = 'forum_notifications'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    post_id = db.Column(db.Integer, db.ForeignKey('forum_posts.id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=_now)
    read_at = db.Column(db.DateTime, nullable=True)
    mentioned = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    post = db.relationship('ForumPost', back_populates='notifications')


class ForumMention(db.Model):
    __tablename__ = 'forum_mentions'
    __table_args__ = (db.UniqueConstraint('post_id', 'membership_id', name='uq_forum_mention_member'),)

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('forum_posts.id', ondelete='CASCADE'), nullable=False, index=True)
    membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    post = db.relationship('ForumPost', back_populates='mentions')
    membership = db.relationship('HouseholdMembership')
