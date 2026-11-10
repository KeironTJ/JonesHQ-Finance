from extensions import db


class TaskList(db.Model):
    __tablename__ = 'task_lists'
    __table_args__ = (
        db.CheckConstraint("visibility IN ('personal', 'shared')", name='ck_task_list_visibility'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    creator_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    creator_membership = db.relationship('HouseholdMembership')
    title = db.Column(db.String(128), nullable=False)
    visibility = db.Column(db.String(10), nullable=False, default='personal', server_default='personal')
    icon = db.Column(db.String(30), nullable=False, default='list-check', server_default='list-check')
    colour = db.Column(db.String(20), nullable=False, default='primary', server_default='primary')
    tasks = db.relationship('HouseholdTask', cascade='all, delete-orphan', back_populates='task_list')


class HouseholdTask(db.Model):
    __tablename__ = 'household_tasks'
    __table_args__ = (
        db.CheckConstraint("priority IN ('low', 'medium', 'high', 'urgent')", name='ck_household_task_priority'),
        db.CheckConstraint('due_time IS NULL OR due_date IS NOT NULL', name='ck_household_task_due_time'),
        db.CheckConstraint(
            '(completed AND completed_at IS NOT NULL) OR '
            '(NOT completed AND completed_at IS NULL AND completed_by_membership_id IS NULL)',
            name='ck_household_task_completion',
        ),
        db.CheckConstraint("recurrence IN ('none', 'daily', 'weekly')", name='ck_task_recurrence'),
        db.CheckConstraint("missed_policy IN ('skip', 'backlog')", name='ck_task_missed_policy'),
        db.UniqueConstraint('series_id', 'period_start', name='uq_task_series_period'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    list_id = db.Column(
        db.Integer, db.ForeignKey('task_lists.id', ondelete='CASCADE'), nullable=False, index=True,
    )
    creator_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True,
    )
    assigned_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True, index=True,
    )
    completed_by_membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), nullable=True,
    )
    task_list = db.relationship('TaskList', back_populates='tasks')
    creator_membership = db.relationship('HouseholdMembership', foreign_keys=[creator_membership_id])
    assignee = db.relationship('HouseholdMembership', foreign_keys=[assigned_membership_id])
    completer = db.relationship('HouseholdMembership', foreign_keys=[completed_by_membership_id])
    title = db.Column(db.String(256), nullable=False)
    notes = db.Column(db.Text, nullable=False, default='', server_default='')
    priority = db.Column(db.String(10), nullable=False, default='medium', server_default='medium')
    due_date = db.Column(db.Date, nullable=True, index=True)
    due_time = db.Column(db.Time, nullable=True)
    completed = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    completed_at = db.Column(db.DateTime, nullable=True)
    recurrence = db.Column(db.String(10), nullable=False, default='none', server_default='none')
    missed_policy = db.Column(db.String(10), nullable=False, default='skip', server_default='skip')
    repeat_active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    series_id = db.Column(db.Integer, db.ForeignKey(
        'household_tasks.id', name='fk_household_tasks_series_id', ondelete='SET NULL',
    ), nullable=True, index=True)
    period_start = db.Column(db.Date, nullable=True)
    expired = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    claim_required = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    claimed_at = db.Column(db.DateTime, nullable=True)
    series = db.relationship('HouseholdTask', remote_side=[id], foreign_keys=[series_id])
    reward_job = db.relationship('RewardJob', back_populates='task', uselist=False)
