from extensions import db


class CalendarEvent(db.Model):
    __tablename__ = 'calendar_events'
    __table_args__ = (
        db.CheckConstraint("visibility IN ('shared', 'private')", name='ck_calendar_visibility'),
        db.CheckConstraint("edit_policy IN ('creator', 'selected', 'household')", name='ck_calendar_edit_policy'),
        db.CheckConstraint("delete_policy IN ('creator', 'selected', 'household')", name='ck_calendar_delete_policy'),
        db.CheckConstraint('ends_on >= starts_on', name='ck_calendar_dates'),
        db.CheckConstraint(
            '(all_day AND starts_at IS NULL AND ends_at IS NULL) OR '
            '(NOT all_day AND starts_at IS NOT NULL AND ends_at IS NOT NULL AND ends_at > starts_at)',
            name='ck_calendar_times',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    creator_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'),
        nullable=True, index=True,
    )
    creator_membership = db.relationship('HouseholdMembership')
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default='', server_default='')
    location = db.Column(db.String(200), nullable=False, default='', server_default='')
    all_day = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    starts_on = db.Column(db.Date, nullable=False)
    ends_on = db.Column(db.Date, nullable=False)
    starts_at = db.Column(db.DateTime, nullable=True)
    ends_at = db.Column(db.DateTime, nullable=True)
    visibility = db.Column(db.String(10), nullable=False, default='shared', server_default='shared')
    edit_policy = db.Column(db.String(10), nullable=False, default='creator', server_default='creator')
    delete_policy = db.Column(db.String(10), nullable=False, default='creator', server_default='creator')
    edit_members = db.Column(db.JSON, nullable=False, default=list, server_default='[]')
    delete_members = db.Column(db.JSON, nullable=False, default=list, server_default='[]')
