from extensions import db


class Reward(db.Model):
    __tablename__ = 'household_rewards'
    __table_args__ = (
        db.CheckConstraint('points_cost BETWEEN 1 AND 10000', name='ck_household_reward_cost'),
        db.CheckConstraint('stock IS NULL OR stock BETWEEN 0 AND 1000', name='ck_household_reward_stock'),
        db.CheckConstraint(
            'cooldown_days IS NULL OR cooldown_days BETWEEN 1 AND 365', name='ck_household_reward_cooldown',
        ),
        db.CheckConstraint(
            "(member_limit IS NULL AND limit_period IS NULL) OR (member_limit BETWEEN 1 AND 100 "
            "AND limit_period IN ('week','month','year','ever'))", name='ck_household_reward_limit',
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=False, default='', server_default='')
    points_cost = db.Column(db.Integer, nullable=False)
    icon = db.Column(db.String(30), nullable=False, default='gift', server_default='gift')
    available = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    category = db.Column(db.String(20), nullable=False, default='treat', server_default='treat')
    # NULL stock means unlimited; requests hold one unit until declined.
    stock = db.Column(db.Integer)
    cooldown_days = db.Column(db.Integer)
    member_limit = db.Column(db.Integer)
    limit_period = db.Column(db.String(10))


class RewardJob(db.Model):
    __tablename__ = 'reward_jobs'
    __table_args__ = (
        db.CheckConstraint('points BETWEEN 1 AND 1000', name='ck_reward_job_points'),
        db.CheckConstraint("state IN ('open','submitted','approved','closed')", name='ck_reward_job_state'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    task_id = db.Column(db.Integer, db.ForeignKey('household_tasks.id', ondelete='SET NULL'), unique=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), index=True)
    reviewer_membership_id = db.Column(db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'))
    title = db.Column(db.String(256), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    state = db.Column(db.String(12), nullable=False, default='open', server_default='open')
    submitted_at = db.Column(db.DateTime)
    reviewed_at = db.Column(db.DateTime)
    review_note = db.Column(db.Text, nullable=False, default='', server_default='')
    task = db.relationship('HouseholdTask', back_populates='reward_job')
    member = db.relationship('HouseholdMembership', foreign_keys=[membership_id])


class RewardRequest(db.Model):
    __tablename__ = 'reward_requests'
    __table_args__ = (
        db.CheckConstraint('points_cost BETWEEN 1 AND 10000', name='ck_reward_request_cost'),
        db.CheckConstraint("state IN ('pending','approved','declined')", name='ck_reward_request_state'),
        db.UniqueConstraint('membership_id', 'request_key', name='uq_reward_request_key'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), index=True)
    reward_id = db.Column(db.Integer, db.ForeignKey('household_rewards.id', ondelete='SET NULL'), index=True)
    reviewer_membership_id = db.Column(db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'))
    title = db.Column(db.String(128), nullable=False)
    points_cost = db.Column(db.Integer, nullable=False)
    request_key = db.Column(db.String(36), nullable=False)
    state = db.Column(db.String(12), nullable=False, default='pending', server_default='pending')
    created_at = db.Column(db.DateTime, nullable=False)
    reviewed_at = db.Column(db.DateTime)
    review_note = db.Column(db.Text, nullable=False, default='', server_default='')
    fulfilled_at = db.Column(db.DateTime)
    fulfilled_by_membership_id = db.Column(
        db.Integer, db.ForeignKey(
            'household_memberships.id', ondelete='SET NULL', name='fk_reward_requests_fulfilled_by',
        ),
    )
    member = db.relationship('HouseholdMembership', foreign_keys=[membership_id])
    reward = db.relationship('Reward')


class RewardPointEntry(db.Model):
    __tablename__ = 'reward_points'
    __table_args__ = (
        db.CheckConstraint(
            "(kind IN ('earned','returned','bonus','milestone') AND points > 0) "
            "OR (kind IN ('reserved','deduction') AND points < 0)", name='ck_reward_points_kind',
        ),
        db.UniqueConstraint('job_id', name='uq_reward_points_job'),
        db.UniqueConstraint('request_id', 'kind', name='uq_reward_points_request_kind'),
        db.UniqueConstraint('unlock_id', name='uq_reward_points_unlock'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), index=True)
    actor_membership_id = db.Column(db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'))
    job_id = db.Column(db.Integer, db.ForeignKey('reward_jobs.id', ondelete='SET NULL'))
    request_id = db.Column(db.Integer, db.ForeignKey('reward_requests.id', ondelete='SET NULL'))
    unlock_id = db.Column(db.Integer, db.ForeignKey(
        'reward_achievement_unlocks.id', ondelete='SET NULL', name='fk_reward_points_unlock_id',
    ))
    kind = db.Column(db.String(10), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(256), nullable=False)
    # Recognition category for manual bonus/deduction entries.
    category = db.Column(db.String(20))
    created_at = db.Column(db.DateTime, nullable=False)
    member = db.relationship('HouseholdMembership', foreign_keys=[membership_id])
    actor = db.relationship('HouseholdMembership', foreign_keys=[actor_membership_id])


class RewardGoal(db.Model):
    __tablename__ = 'reward_goals'
    __table_args__ = (
        db.UniqueConstraint('membership_id', 'reward_id', name='uq_reward_goal_member_reward'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), index=True,
    )
    reward_id = db.Column(db.Integer, db.ForeignKey('household_rewards.id', ondelete='SET NULL'))
    reward = db.relationship('Reward')


class RewardAchievement(db.Model):
    __tablename__ = 'reward_achievements'
    __table_args__ = (
        db.CheckConstraint(
            "metric IN ('chores','points','streak','recognition')", name='ck_reward_achievement_metric',
        ),
        db.CheckConstraint('threshold BETWEEN 1 AND 100000', name='ck_reward_achievement_threshold'),
        db.CheckConstraint('bonus_points BETWEEN 0 AND 1000', name='ck_reward_achievement_bonus'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    title = db.Column(db.String(64), nullable=False)
    description = db.Column(db.String(256), nullable=False, default='', server_default='')
    icon = db.Column(db.String(30), nullable=False, default='trophy', server_default='trophy')
    metric = db.Column(db.String(12), nullable=False)
    threshold = db.Column(db.Integer, nullable=False)
    bonus_points = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    active = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())


class RewardAchievementUnlock(db.Model):
    __tablename__ = 'reward_achievement_unlocks'
    __table_args__ = (
        db.UniqueConstraint('achievement_id', 'membership_id', name='uq_reward_unlock_member'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    achievement_id = db.Column(
        db.Integer, db.ForeignKey('reward_achievements.id', ondelete='SET NULL'), index=True,
    )
    membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), index=True,
    )
    title = db.Column(db.String(64), nullable=False)
    icon = db.Column(db.String(30), nullable=False, default='trophy', server_default='trophy')
    unlocked_at = db.Column(db.DateTime, nullable=False)
    achievement = db.relationship('RewardAchievement')
    member = db.relationship('HouseholdMembership', foreign_keys=[membership_id])


class RewardChoreTemplate(db.Model):
    __tablename__ = 'reward_chore_templates'
    __table_args__ = (
        db.CheckConstraint('points BETWEEN 1 AND 1000', name='ck_reward_template_points'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    title = db.Column(db.String(256), nullable=False)
    notes = db.Column(db.Text, nullable=False, default='', server_default='')
    points = db.Column(db.Integer, nullable=False)
