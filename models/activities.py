from extensions import db


class Activity(db.Model):
    __tablename__ = 'activities'
    __table_args__ = (
        db.CheckConstraint("status IN ('pending', 'approved', 'rejected')", name='ck_activity_status'),
        db.CheckConstraint("recurrence IN ('none', 'weekly')", name='ck_activity_recurrence'),
        db.CheckConstraint(
            "(recurrence = 'none' AND repeat_until IS NULL) OR "
            "(recurrence = 'weekly' AND repeat_until IS NOT NULL AND repeat_until >= starts_on)",
            name='ck_activity_repeat_until',
        ),
        db.CheckConstraint('ends_on >= starts_on', name='ck_activity_dates'),
        db.CheckConstraint(
            '(all_day AND starts_at IS NULL AND ends_at IS NULL) OR '
            '(NOT all_day AND starts_at IS NOT NULL AND ends_at IS NOT NULL AND ends_at > starts_at)',
            name='ck_activity_times',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    creator_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )
    reviewer_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True,
    )
    creator_membership = db.relationship('HouseholdMembership', foreign_keys=[creator_membership_id])
    reviewer_membership = db.relationship('HouseholdMembership', foreign_keys=[reviewer_membership_id])
    reviewed_at = db.Column(db.DateTime, nullable=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default='', server_default='')
    comments = db.Column(db.Text, nullable=False, default='', server_default='')
    location = db.Column(db.String(200), nullable=False, default='', server_default='')
    all_day = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    starts_on = db.Column(db.Date, nullable=False, index=True)
    ends_on = db.Column(db.Date, nullable=False)
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    recurrence = db.Column(db.String(10), nullable=False, default='none', server_default='none')
    repeat_until = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(10), nullable=False, default='pending', server_default='pending')
    attendees = db.relationship('ActivityAttendee', cascade='all, delete-orphan', back_populates='activity')


class ActivityAttendee(db.Model):
    __tablename__ = 'activity_attendees'
    __table_args__ = (
        db.UniqueConstraint('activity_id', 'membership_id', name='uq_activity_attendee'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    activity_id = db.Column(
        db.Integer, db.ForeignKey('activities.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    activity = db.relationship('Activity', back_populates='attendees')
    membership = db.relationship('HouseholdMembership')
