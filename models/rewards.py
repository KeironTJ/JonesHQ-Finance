from extensions import db


class Reward(db.Model):
    __tablename__ = 'household_rewards'
    __table_args__ = (
        db.CheckConstraint('points_cost BETWEEN 1 AND 10000', name='ck_household_reward_cost'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    title = db.Column(db.String(128), nullable=False)
    description = db.Column(db.Text, nullable=False, default='', server_default='')
    points_cost = db.Column(db.Integer, nullable=False)
    icon = db.Column(db.String(30), nullable=False, default='gift', server_default='gift')
    available = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())


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
    member = db.relationship('HouseholdMembership', foreign_keys=[membership_id])


class RewardPointEntry(db.Model):
    __tablename__ = 'reward_points'
    __table_args__ = (
        db.CheckConstraint(
            "(kind = 'earned' AND points > 0) OR (kind = 'reserved' AND points < 0) "
            "OR (kind = 'returned' AND points > 0)", name='ck_reward_points_kind',
        ),
        db.UniqueConstraint('job_id', name='uq_reward_points_job'),
        db.UniqueConstraint('request_id', 'kind', name='uq_reward_points_request_kind'),
    )

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    membership_id = db.Column(db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), index=True)
    actor_membership_id = db.Column(db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'))
    job_id = db.Column(db.Integer, db.ForeignKey('reward_jobs.id', ondelete='SET NULL'))
    request_id = db.Column(db.Integer, db.ForeignKey('reward_requests.id', ondelete='SET NULL'))
    kind = db.Column(db.String(10), nullable=False)
    points = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False)
    member = db.relationship('HouseholdMembership', foreign_keys=[membership_id])


class RewardGoal(db.Model):
    __tablename__ = 'reward_goals'

    id = db.Column(db.Integer, primary_key=True)
    family_id = db.Column(db.Integer, db.ForeignKey('families.id'), nullable=False, index=True)
    membership_id = db.Column(
        db.Integer, db.ForeignKey('household_memberships.id', ondelete='SET NULL'), unique=True,
    )
    reward_id = db.Column(db.Integer, db.ForeignKey('household_rewards.id', ondelete='SET NULL'))
    reward = db.relationship('Reward')
