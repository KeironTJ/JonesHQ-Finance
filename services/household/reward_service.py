from datetime import datetime, timezone
from uuid import UUID, uuid4

from flask import abort
from flask_login import current_user
from sqlalchemy import update

from extensions import db
from models.family import Family, HouseholdMembership
from models.household_tasks import HouseholdTask, TaskList
from models.rewards import Reward, RewardGoal, RewardJob, RewardPointEntry, RewardRequest
from services.household.calendar_service import CalendarService, LONDON
from utils.db_helpers import family_get, family_get_or_404, family_query


REWARD_ICONS = {'gift': 'Gift', 'controller': 'Game', 'film': 'Movie', 'cup-hot': 'Treat', 'bicycle': 'Adventure', 'star': 'Star'}


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RewardService:
    @staticmethod
    def require_adult():
        membership = CalendarService.require_access()
        if current_user.is_managed_child:
            abort(403)
        return membership

    @staticmethod
    def _lock():
        membership = CalendarService.require_access()
        # Serialize household reward transitions and balance checks on SQLite and PostgreSQL.
        db.session.execute(update(Family).where(Family.id == membership.family_id).values(id=Family.id))
        db.session.expire_all()
        return membership

    @staticmethod
    def _child(member_id):
        member = family_get(HouseholdMembership, member_id)
        if member is None or not member.user.is_active or not member.user.is_managed_child:
            raise ValueError('Choose an active child in this household.')
        return member

    @staticmethod
    def _integer(value, label, maximum):
        try:
            number = int(str(value))
        except (ValueError, TypeError) as error:
            raise ValueError(f'Enter whole {label} between 1 and {maximum}.') from error
        if not 1 <= number <= maximum:
            raise ValueError(f'Enter whole {label} between 1 and {maximum}.')
        return number

    @staticmethod
    def _note(data, required=False):
        note = (data.get('note') or '').strip()
        if len(note) > 500 or required and not note:
            raise ValueError('Add a helpful note of up to 500 characters.')
        return note

    @staticmethod
    def balance(member_id):
        return family_query(RewardPointEntry).filter_by(membership_id=member_id).with_entities(
            db.func.coalesce(db.func.sum(RewardPointEntry.points), 0),
        ).scalar()

    @staticmethod
    def configure_task(task, data):
        job = task.reward_job
        if job and job.state == 'closed':
            raw = data.get('reward_points')
            if raw not in ('', None, '0', 0) and RewardService._integer(raw, 'job points', 1000) != job.points:
                raise ValueError('Closed jobs cannot earn points again. Create a new task instead.')
            return
        if 'reward_points' not in data:
            if job and task.assigned_membership_id != job.membership_id and job.state != 'closed':
                raise ValueError('Close the reward job before changing its assignee.')
            if job:
                job.title = task.title
            return
        RewardService.require_adult()
        raw = data.get('reward_points')
        if raw in ('', None, '0', 0) and job is None:
            return
        points = RewardService._integer(raw, 'job points', 1000)
        if task.task_list.visibility != 'shared':
            raise ValueError('Only shared tasks can earn reward points.')
        member = RewardService._child(task.assigned_membership_id)
        if task.completed and job is None:
            raise ValueError('Choose an unfinished task for a new reward job.')
        if job:
            if member.id != job.membership_id:
                raise ValueError('Create a new task for a different child.')
            if points != job.points and job.state != 'open':
                raise ValueError('Points cannot change after submission. Create a new job instead.')
            job.points = points
            job.title = task.title
        else:
            task.reward_job = RewardJob(
                family_id=task.family_id, membership_id=member.id, title=task.title, points=points,
            )

    @staticmethod
    def create_job(data):
        from services.household.task_service import TaskService
        membership = RewardService.require_adult()
        RewardService._lock()
        task_list = family_get(TaskList, data.get('list_id')) if data.get('list_id') else None
        if data.get('list_id') and task_list is None:
            raise ValueError('Choose a shared task list in this household.')
        if task_list is None:
            title = (data.get('list_title') or 'Reward jobs').strip()
            task_list = TaskList(
                family_id=membership.family_id, creator_membership_id=membership.id,
                **TaskService._list_values({'title': title, 'visibility': 'shared', 'icon': 'star'}),
            )
            db.session.add(task_list)
            db.session.flush()
        if task_list.visibility != 'shared':
            raise ValueError('Reward jobs need a shared task list.')
        task = HouseholdTask(
            family_id=membership.family_id, task_list=task_list,
            creator_membership_id=membership.id, **TaskService._task_values(data, task_list),
        )
        db.session.add(task)
        RewardService.configure_task(task, data)
        if task.reward_job is None:
            raise ValueError('Choose points for this reward job.')
        db.session.commit()
        return task

    @staticmethod
    def completion_changed(task, completed):
        job = task.reward_job
        if job is None or job.state in ('approved', 'closed'):
            return
        if completed:
            RewardService._child(job.membership_id)
            job.state = 'submitted'
            job.submitted_at = _now()
        else:
            job.state = 'open'
            job.submitted_at = None

    @staticmethod
    def submit_job(job_id, data):
        membership = CalendarService.require_access()
        RewardService._lock()
        job = family_get_or_404(RewardJob, job_id)
        if not current_user.is_managed_child or job.membership_id != membership.id:
            abort(403)
        if job.state in ('submitted', 'approved'):
            return job
        if job.state != 'open' or job.task is None:
            raise ValueError('This job is no longer available.')
        from services.household.task_service import TaskService
        TaskService.set_completion(job.task_id, {'action': 'complete'})
        return job

    @staticmethod
    def review_job(job_id, data):
        membership = RewardService.require_adult()
        RewardService._lock()
        job = family_get_or_404(RewardJob, job_id)
        action = data.get('action')
        if action not in ('approve', 'return', 'close'):
            raise ValueError('Choose approve, send back or close.')
        if action == 'approve' and job.state == 'approved' or action == 'close' and job.state == 'closed':
            return job
        if job.state in ('approved', 'closed') or action != 'close' and job.state != 'submitted':
            raise ValueError('This job has changed. Refresh and review it again.')
        job.review_note = RewardService._note(data, required=action == 'return')
        job.reviewed_at = _now()
        job.reviewer_membership_id = membership.id
        if action == 'approve':
            RewardService._child(job.membership_id)
            if job.task is None or not job.task.completed or job.task.assigned_membership_id != job.membership_id:
                raise ValueError('This task has changed. Review it before awarding points.')
            job.state = 'approved'
            db.session.add(RewardPointEntry(
                family_id=membership.family_id, membership_id=job.membership_id,
                actor_membership_id=membership.id, job_id=job.id, kind='earned',
                points=job.points, description=job.title, created_at=_now(),
            ))
        elif action == 'return':
            job.state = 'open'
            job.submitted_at = None
            if job.task:
                job.task.completed = False
                job.task.completed_at = None
                job.task.completed_by_membership_id = None
        else:
            job.state = 'closed'
            if job.task and not job.task.completed:
                job.task.completed = True
                job.task.completed_at = _now()
                job.task.completed_by_membership_id = membership.id
        db.session.commit()
        return job

    @staticmethod
    def save_reward(data, reward_id=None):
        membership = RewardService.require_adult()
        RewardService._lock()
        reward = family_get_or_404(Reward, reward_id) if reward_id is not None else Reward(family_id=membership.family_id)
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        icon = data.get('icon', 'gift')
        if not title or len(title) > 128 or len(description) > 1000:
            raise ValueError('Enter a reward title up to 128 characters and description up to 1,000 characters.')
        if icon not in REWARD_ICONS:
            raise ValueError('Choose a reward icon from the list.')
        available = data.get('available', 'yes')
        if available not in ('yes', 'no'):
            raise ValueError('Choose whether this reward is available.')
        reward.title = title
        reward.description = description
        reward.points_cost = RewardService._integer(data.get('points_cost'), 'reward points', 10000)
        reward.icon = icon
        reward.available = available == 'yes'
        db.session.add(reward)
        db.session.commit()
        return reward

    @staticmethod
    def request_reward(reward_id, data):
        membership = CalendarService.require_access()
        if not current_user.is_managed_child:
            abort(403)
        RewardService._lock()
        reward = family_get_or_404(Reward, reward_id)
        try:
            key = str(UUID(data.get('request_key', '')))
        except (ValueError, TypeError, AttributeError) as error:
            raise ValueError('Refresh the reward page before requesting again.') from error
        existing = family_query(RewardRequest).filter_by(membership_id=membership.id, request_key=key).first()
        if existing:
            if existing.reward_id != reward.id:
                raise ValueError('Refresh the reward page before requesting a different reward.')
            return existing
        if not reward.available:
            raise ValueError('This reward is taking a break. Choose another one.')
        if family_query(RewardRequest).filter_by(
            membership_id=membership.id, reward_id=reward.id, state='pending',
        ).first():
            raise ValueError('You already have a request for this reward waiting for an adult.')
        if RewardService.balance(membership.id) < reward.points_cost:
            raise ValueError('Keep going! You need more points for this reward.')
        reward_request = RewardRequest(
            family_id=membership.family_id, membership_id=membership.id, reward_id=reward.id,
            title=reward.title, points_cost=reward.points_cost, request_key=key, created_at=_now(),
        )
        db.session.add(reward_request)
        db.session.flush()
        db.session.add(RewardPointEntry(
            family_id=membership.family_id, membership_id=membership.id,
            actor_membership_id=membership.id, request_id=reward_request.id, kind='reserved',
            points=-reward.points_cost, description=reward.title, created_at=_now(),
        ))
        db.session.commit()
        return reward_request

    @staticmethod
    def review_request(request_id, data):
        membership = RewardService.require_adult()
        RewardService._lock()
        reward_request = family_get_or_404(RewardRequest, request_id)
        action = data.get('action')
        if action not in ('approve', 'decline'):
            raise ValueError('Choose approve or decline.')
        target = 'approved' if action == 'approve' else 'declined'
        if reward_request.state == target:
            return reward_request
        if reward_request.state != 'pending':
            raise ValueError('This request has already been reviewed.')
        if reward_request.membership_id is None:
            raise ValueError('This member has left the household.')
        reward_request.review_note = RewardService._note(data, required=action == 'decline')
        reward_request.state = target
        reward_request.reviewed_at = _now()
        reward_request.reviewer_membership_id = membership.id
        if target == 'declined':
            db.session.add(RewardPointEntry(
                family_id=membership.family_id, membership_id=reward_request.membership_id,
                actor_membership_id=membership.id, request_id=reward_request.id, kind='returned',
                points=reward_request.points_cost, description=reward_request.title, created_at=_now(),
            ))
        db.session.commit()
        return reward_request

    @staticmethod
    def set_goal(data):
        membership = CalendarService.require_access()
        if not current_user.is_managed_child:
            abort(403)
        RewardService._lock()
        reward = family_get_or_404(Reward, data['reward_id']) if data.get('reward_id') else None
        if reward and not reward.available:
            raise ValueError('Choose an available reward for your goal.')
        goal = family_query(RewardGoal).filter_by(membership_id=membership.id).first()
        if goal is None:
            goal = RewardGoal(family_id=membership.family_id, membership_id=membership.id)
            db.session.add(goal)
        goal.reward_id = reward.id if reward else None
        db.session.commit()

    @staticmethod
    def page_data(view):
        membership = CalendarService.require_access()
        if view not in ('jobs', 'shop', 'progress', 'manage'):
            raise ValueError('Choose jobs, rewards or progress.')
        child = current_user.is_managed_child
        if view == 'manage':
            RewardService.require_adult()
        today = datetime.now(LONDON).date()
        jobs = family_query(RewardJob).order_by(RewardJob.id.desc()).all()
        requests = family_query(RewardRequest).order_by(RewardRequest.id.desc()).all()
        rewards = family_query(Reward).order_by(Reward.points_cost, Reward.id).all()
        if child:
            rewards = [row for row in rewards if row.available]
        goal = family_query(RewardGoal).filter_by(membership_id=membership.id).first() if child else None
        balance = RewardService.balance(membership.id) if child else 0
        active = [job for job in jobs if job.state == 'open' and job.task and job.membership_id]
        current = [job for job in active if job.task.due_date is None or job.task.due_date >= today]
        earlier = [job for job in active if job.task.due_date is not None and job.task.due_date < today]
        return dict(
            child_view=child, view=view, jobs=current, earlier_jobs=earlier,
            submitted_jobs=[job for job in jobs if job.state == 'submitted' and job.task and job.membership_id],
            job_history=[job for job in jobs if job.state in ('approved', 'closed')],
            requests=requests, pending=[row for row in requests if row.state == 'pending' and row.membership_id],
            rewards=rewards, balance=balance, goal=goal.reward if goal and goal.reward and goal.reward.available else None,
            entries=family_query(RewardPointEntry).order_by(RewardPointEntry.id.desc()).limit(100).all(),
            members=[member for member in CalendarService.members() if member.user.is_managed_child] if not child else [],
            lists=family_query(TaskList).filter_by(visibility='shared').order_by(TaskList.title).all() if not child else [],
            request_keys={row.id: str(uuid4()) for row in rewards},
            icons=REWARD_ICONS, reward_service=RewardService, today=today,
        )

    @staticmethod
    def detach_tasks(tasks):
        ids = [task.id for task in tasks]
        if not ids:
            return
        for job in family_query(RewardJob, include_private=True).filter(RewardJob.task_id.in_(ids)).all():
            if job.state in ('open', 'submitted'):
                job.state = 'closed'
                job.review_note = 'The task was removed.'
            job.task_id = None

    @staticmethod
    def detach_membership(membership):
        for job in family_query(RewardJob, include_private=True).filter_by(membership_id=membership.id).all():
            if job.state in ('open', 'submitted'):
                job.state = 'closed'
                job.review_note = 'The member left the household.'
        for reward_request in family_query(RewardRequest, include_private=True).filter_by(
            membership_id=membership.id, state='pending',
        ).all():
            reward_request.state = 'declined'
            reward_request.review_note = 'The member left the household.'
            reward_request.reviewed_at = _now()
            db.session.add(RewardPointEntry(
                family_id=membership.family_id, membership_id=membership.id,
                request_id=reward_request.id, kind='returned', points=reward_request.points_cost,
                description=reward_request.title, created_at=_now(),
            ))
        db.session.flush()
        for model, keys in (
            (RewardJob, ('membership_id', 'reviewer_membership_id')),
            (RewardRequest, ('membership_id', 'reviewer_membership_id')),
            (RewardPointEntry, ('membership_id', 'actor_membership_id')),
            (RewardGoal, ('membership_id',)),
        ):
            for key in keys:
                family_query(model, include_private=True).filter(getattr(model, key) == membership.id).update(
                    {key: None}, synchronize_session=False,
                )
