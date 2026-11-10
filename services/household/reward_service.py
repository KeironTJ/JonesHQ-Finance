from datetime import datetime, time, timedelta, timezone
from uuid import UUID, uuid4

from flask import abort
from flask_login import current_user
from sqlalchemy import case, update

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
        mode = data.get('assignment_mode', 'assigned')
        if mode not in ('assigned', 'claim'):
            raise ValueError('Choose automatic assignment or optional claiming.')
        if hasattr(data, 'getlist'):
            selected = data.getlist('assigned_membership_ids')
        else:
            selected = data.get('assigned_membership_ids', [])
        if not isinstance(selected, (list, tuple)):
            raise ValueError('Choose one or more eligible children.')
        selected = selected or [data.get('assigned_membership_id')]
        children = {RewardService._child(member_id).id for member_id in selected}
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
        tasks = []
        for member_id in sorted(children):
            values = dict(data)
            values['assigned_membership_id'] = member_id
            task = HouseholdTask(
                family_id=membership.family_id, task_list=task_list,
                creator_membership_id=membership.id, claim_required=mode == 'claim',
                **TaskService._task_values(values, task_list),
            )
            db.session.add(task)
            RewardService.configure_task(task, values)
            TaskService.configure_recurrence(task, values)
            if task.reward_job is None:
                raise ValueError('Choose points for this reward job.')
            tasks.append(task)
        db.session.commit()
        return tasks[0]

    @staticmethod
    def claim_job(job_id, data):
        from services.household.task_service import TaskService
        membership = CalendarService.require_access()
        RewardService._lock()
        TaskService.refresh_recurring(commit=False)
        job = family_get_or_404(RewardJob, job_id)
        if not current_user.is_managed_child or job.membership_id != membership.id:
            abort(403)
        task = job.task
        if job.state != 'open' or task is None or task.expired:
            raise ValueError('This job is no longer available to claim.')
        if not task.claim_required:
            raise ValueError('This job is already assigned to you.')
        if task.period_start and task.period_start > datetime.now(LONDON).date():
            raise ValueError('This repeat interval has not started yet.')
        if task.claimed_at is None:
            task.claimed_at = _now()
        db.session.commit()
        return job

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
            if job.task and job.task.period_start:
                root = job.task.series or job.task
                if root.missed_policy == 'skip' and job.task.due_date < datetime.now(LONDON).date():
                    raise ValueError('This interval has ended. Approve the submitted work or close it without points.')
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
    def set_board(data):
        membership = RewardService.require_adult()
        enabled = data.get('enabled')
        if enabled not in ('yes', 'no'):
            raise ValueError('Choose whether to share the celebration board.')
        RewardService._lock()
        family = membership.family
        family.rewards_board_enabled = enabled == 'yes'
        db.session.commit()

    @staticmethod
    def celebration_data(membership):
        family = membership.family
        child = current_user.is_managed_child
        members = [member for member in CalendarService.members() if member.user.is_managed_child]
        if child and not family.rewards_board_enabled:
            members = [member for member in members if member.id == membership.id]
        ids = [member.id for member in members]
        today = datetime.now(LONDON).date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=7)
        starts_at = datetime.combine(week_start, time.min, tzinfo=LONDON).astimezone(timezone.utc).replace(tzinfo=None)
        ends_at = datetime.combine(week_end, time.min, tzinfo=LONDON).astimezone(timezone.utc).replace(tzinfo=None)
        in_week = (RewardPointEntry.created_at >= starts_at) & (RewardPointEntry.created_at < ends_at)
        # Opt-in sharing exposes earned totals only, never ledger rows or spending.
        totals = family_query(RewardPointEntry, include_private=True).filter(
            RewardPointEntry.membership_id.in_(ids), RewardPointEntry.kind == 'earned',
        ).with_entities(
            RewardPointEntry.membership_id,
            db.func.sum(RewardPointEntry.points),
            db.func.count(RewardPointEntry.id),
            db.func.sum(case((in_week, RewardPointEntry.points), else_=0)),
            db.func.sum(case((in_week, 1), else_=0)),
        ).group_by(RewardPointEntry.membership_id).all() if ids else []
        earned = {
            member_id: (int(points), count, int(week_points), int(week_jobs))
            for member_id, points, count, week_points, week_jobs in totals
        }
        cards = []
        for member in members:
            points, jobs, week_points, week_jobs = earned.get(member.id, (0, 0, 0, 0))
            milestones = [
                ('First step', 'Your first approved job', jobs >= 1, 'star'),
                ('Helping hand', '5 approved jobs', jobs >= 5, 'hand-thumbs-up'),
                ('Team player', '10 approved jobs', jobs >= 10, 'people'),
                ('100-point milestone', '100 points earned in total', points >= 100, 'trophy'),
            ]
            cards.append(dict(
                name=member.user.name, is_you=member.id == membership.id,
                earned=points, jobs=jobs, milestones=milestones,
                week_points=week_points, week_jobs=week_jobs,
            ))
        cards.sort(key=lambda card: (-card['week_points'], card['name'].casefold()))
        rank, previous_points = 0, None
        for index, card in enumerate(cards, start=1):
            if card['week_points'] != previous_points:
                rank = index
            card['rank'] = rank
            previous_points = card['week_points']
        return family.rewards_board_enabled, cards, week_start, week_end - timedelta(days=1)

    @staticmethod
    def page_data(view):
        from services.household.task_service import TaskService
        membership = CalendarService.require_access()
        if view not in ('home', 'jobs', 'shop', 'progress', 'manage'):
            raise ValueError('Choose overview, jobs, rewards or progress.')
        child = current_user.is_managed_child
        if view == 'manage':
            RewardService.require_adult()
        TaskService.refresh_recurring()
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
        board_enabled = membership.family.rewards_board_enabled
        celebration, week_start, week_end = [], None, None
        if view == 'home':
            board_enabled, celebration, week_start, week_end = RewardService.celebration_data(membership)
        personal = next((card for card in celebration if card['is_you']), None)
        active_rewards = [reward for reward in rewards if reward.available]
        return dict(
            board_enabled=board_enabled, celebration=celebration, personal=personal,
            board_week_start=week_start, board_week_end=week_end,
            featured_rewards=active_rewards[:3],
            available_reward_count=len(active_rewards),
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
