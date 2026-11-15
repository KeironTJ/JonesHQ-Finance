from datetime import datetime, time, timedelta, timezone
from uuid import UUID, uuid4

from flask import abort
from flask_login import current_user
from sqlalchemy import case, update

from extensions import db
from models.family import Family, HouseholdMembership
from models.household_tasks import HouseholdTask, TaskList
from models.rewards import (
    Reward, RewardAchievementUnlock, RewardChoreTemplate, RewardGoal, RewardJob, RewardPointEntry, RewardRequest,
)
from services.household.calendar_service import CalendarService, LONDON
from services.platform.module_access_service import ModuleAccessService
from utils.db_helpers import family_get, family_get_or_404, family_query


REWARD_ICONS = {
    'gift': 'Gift', 'controller': 'Game', 'film': 'Movie', 'cup-hot': 'Treat', 'bicycle': 'Adventure',
    'star': 'Star', 'phone': 'Screen time', 'cash-coin': 'Money', 'book': 'Book', 'music-note': 'Music',
    'balloon': 'Party', 'moon-stars': 'Late night', 'basket': 'Shopping', 'puzzle': 'Toy',
}
REWARD_CATEGORIES = {
    'treat': 'Treats', 'screen': 'Screen time', 'outing': 'Days out', 'money': 'Pocket money',
    'privilege': 'Privileges', 'toy': 'Toys & games', 'other': 'Other',
}
RECOGNITION_CATEGORIES = {
    'school': 'School', 'hobby': 'Hobby or club', 'kindness': 'Kindness', 'helping': 'Helping out',
    'behaviour': 'Behaviour', 'other': 'Other',
}
LIMIT_PERIODS = {'week': 'per week', 'month': 'per month', 'year': 'per year', 'ever': 'in total'}
MAX_GOALS = 5
STARTER_CHORES = (
    ('Make your bed', 'Straighten the covers and plump the pillow.', 5),
    ('Tidy your bedroom', 'Toys away, clothes in the basket and a clear floor.', 10),
    ('Set the table', 'Plates, cutlery and drinks ready for everyone.', 5),
    ('Empty the dishwasher', 'Put everything back where it lives.', 10),
    ('Feed the pet', 'Fresh food and water.', 5),
    ('Put laundry away', 'Fold and put away your clean clothes.', 10),
    ('Homework done', 'Finish homework without a reminder.', 10),
    ('Reading time', '20 minutes of reading.', 10),
)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_start(day):
    """UTC-naive instant for the start of a Europe/London calendar day."""
    return datetime.combine(day, time.min, tzinfo=LONDON).astimezone(timezone.utc).replace(tzinfo=None)


def local_date(moment):
    return moment.replace(tzinfo=timezone.utc).astimezone(LONDON).date()


def period_start(period, today):
    if period == 'week':
        return today - timedelta(days=today.weekday())
    if period == 'month':
        return today.replace(day=1)
    if period == 'year':
        return today.replace(month=1, day=1)
    return None


def _ids(data, key):
    values = data.getlist(key) if hasattr(data, 'getlist') else data.get(key, [])
    if not isinstance(values, (list, tuple)):
        raise ValueError('Choose one or more items.')
    return [value for value in values if value not in ('', None)]


def _form_dict(data):
    return data.to_dict() if hasattr(data, 'to_dict') else dict(data)


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
    def is_participant(member):
        """Managed children always earn points; adults opt in."""
        if member is None or not member.user.is_active:
            return False
        if member.user.is_managed_child:
            return True
        return bool(member.rewards_participant) and ModuleAccessService.can_access(
            member.user, 'household', member.family_id,
        )

    @staticmethod
    def _member(member_id):
        try:
            return family_get(HouseholdMembership, member_id) if member_id not in ('', None) else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _participant(member_id):
        member = RewardService._member(member_id)
        if not RewardService.is_participant(member):
            raise ValueError('Choose a child or an adult who earns points in this household.')
        return member

    @staticmethod
    def participants():
        return [member for member in CalendarService.members() if RewardService.is_participant(member)]

    @staticmethod
    def _integer(value, label, maximum, minimum=1):
        try:
            number = int(str(value))
        except (ValueError, TypeError) as error:
            raise ValueError(f'Enter whole {label} between {minimum} and {maximum}.') from error
        if not minimum <= number <= maximum:
            raise ValueError(f'Enter whole {label} between {minimum} and {maximum}.')
        return number

    @staticmethod
    def _optional_integer(value, label, maximum, minimum=1):
        if value in ('', None):
            return None
        return RewardService._integer(value, label, maximum, minimum)

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

    # ----- Chores -----

    @staticmethod
    def configure_task(task, data):
        job = task.reward_job
        if job and job.state == 'closed':
            raw = data.get('reward_points')
            if raw not in ('', None, '0', 0) and RewardService._integer(raw, 'chore points', 1000) != job.points:
                raise ValueError('Closed chores cannot earn points again. Create a new task instead.')
            return
        if 'reward_points' not in data:
            if job and task.assigned_membership_id != job.membership_id and job.state != 'closed':
                raise ValueError('Close the chore before changing its assignee.')
            if job:
                job.title = task.title
            return
        RewardService.require_adult()
        raw = data.get('reward_points')
        if raw in ('', None, '0', 0) and job is None:
            return
        points = RewardService._integer(raw, 'chore points', 1000)
        if task.task_list.visibility != 'shared':
            raise ValueError('Only shared tasks can earn reward points.')
        member = RewardService._participant(task.assigned_membership_id)
        if task.completed and job is None:
            raise ValueError('Choose an unfinished task for a new chore.')
        if job:
            if member.id != job.membership_id:
                raise ValueError('Create a new task for a different person.')
            if points != job.points and job.state != 'open':
                raise ValueError('Points cannot change after submission. Create a new chore instead.')
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
        selected = _ids(data, 'assigned_membership_ids') or [data.get('assigned_membership_id')]
        people = {RewardService._participant(member_id).id for member_id in selected}
        values = _form_dict(data)
        if data.get('template_id'):
            template = family_get(RewardChoreTemplate, data.get('template_id'))
            if template is None:
                raise ValueError('Choose a chore from your library.')
            if not (values.get('title') or '').strip():
                values['title'] = template.title
            if not (values.get('notes') or '').strip():
                values['notes'] = template.notes
            if values.get('reward_points') in ('', None):
                values['reward_points'] = template.points
        task_list = family_get(TaskList, data.get('list_id')) if data.get('list_id') else None
        if data.get('list_id') and task_list is None:
            raise ValueError('Choose a shared task list in this household.')
        if task_list is None:
            title = (data.get('list_title') or 'Chores').strip()
            task_list = TaskList(
                family_id=membership.family_id, creator_membership_id=membership.id,
                **TaskService._list_values({'title': title, 'visibility': 'shared', 'icon': 'star'}),
            )
            db.session.add(task_list)
            db.session.flush()
        if task_list.visibility != 'shared':
            raise ValueError('Chores need a shared task list.')
        tasks = []
        for member_id in sorted(people):
            member_values = dict(values)
            member_values['assigned_membership_id'] = member_id
            task = HouseholdTask(
                family_id=membership.family_id, task_list=task_list,
                creator_membership_id=membership.id, claim_required=mode == 'claim',
                **TaskService._task_values(member_values, task_list),
            )
            db.session.add(task)
            RewardService.configure_task(task, member_values)
            TaskService.configure_recurrence(task, member_values)
            if task.reward_job is None:
                raise ValueError('Choose points for this chore.')
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
        if job.membership_id != membership.id:
            abort(403)
        task = job.task
        if job.state != 'open' or task is None or task.expired:
            raise ValueError('This chore is no longer available to claim.')
        if not task.claim_required:
            raise ValueError('This chore is already assigned to you.')
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
            RewardService._participant(job.membership_id)
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
        if job.membership_id != membership.id:
            abort(403)
        if job.state in ('submitted', 'approved'):
            return job
        if job.state != 'open' or job.task is None:
            raise ValueError('This chore is no longer available.')
        from services.household.task_service import TaskService
        TaskService.set_completion(job.task_id, {'action': 'complete'})
        return job

    @staticmethod
    def _review_job(job, action, note, membership):
        if action not in ('approve', 'return', 'close'):
            raise ValueError('Choose approve, send back or close.')
        if action == 'approve' and job.state == 'approved' or action == 'close' and job.state == 'closed':
            return False
        if job.state in ('approved', 'closed') or action != 'close' and job.state != 'submitted':
            raise ValueError(f'"{job.title}" has changed. Refresh and review it again.')
        if action == 'return' and not note:
            raise ValueError('Add a helpful note of up to 500 characters.')
        if action == 'approve' and job.membership_id == membership.id:
            raise ValueError('Another adult needs to approve your own chores.')
        job.review_note = note
        job.reviewed_at = _now()
        job.reviewer_membership_id = membership.id
        if action == 'approve':
            RewardService._participant(job.membership_id)
            if job.task is None or not job.task.completed or job.task.assigned_membership_id != job.membership_id:
                raise ValueError('This task has changed. Review it before awarding points.')
            job.state = 'approved'
            db.session.add(RewardPointEntry(
                family_id=membership.family_id, membership_id=job.membership_id,
                actor_membership_id=membership.id, job_id=job.id, kind='earned',
                points=job.points, description=job.title, created_at=_now(),
            ))
            return True
        if action == 'return':
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
        return False

    @staticmethod
    def review_job(job_id, data):
        from services.household.reward_achievement_service import RewardAchievementService
        membership = RewardService.require_adult()
        RewardService._lock()
        job = family_get_or_404(RewardJob, job_id)
        action = data.get('action')
        note = RewardService._note(data, required=action == 'return')
        if RewardService._review_job(job, action, note, membership):
            db.session.flush()
            RewardAchievementService.evaluate([job.membership_id])
        db.session.commit()
        return job

    # ----- Reward catalogue and requests -----

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
        category = data.get('category') or 'treat'
        if category not in REWARD_CATEGORIES:
            raise ValueError('Choose a reward category from the list.')
        member_limit = RewardService._optional_integer(data.get('member_limit'), 'times per person', 100)
        limit_period = data.get('limit_period') or None if member_limit else None
        if member_limit and limit_period not in LIMIT_PERIODS:
            raise ValueError('Choose how often the per-person limit resets.')
        reward.title = title
        reward.description = description
        reward.points_cost = RewardService._integer(data.get('points_cost'), 'reward points', 10000)
        reward.icon = icon
        reward.available = available == 'yes'
        reward.category = category
        reward.stock = RewardService._optional_integer(data.get('stock'), 'items in stock', 1000, minimum=0)
        reward.cooldown_days = RewardService._optional_integer(data.get('cooldown_days'), 'cooldown days', 365)
        reward.member_limit = member_limit
        reward.limit_period = limit_period
        db.session.add(reward)
        db.session.commit()
        return reward

    @staticmethod
    def check_eligibility(reward, member_id, balance=None):
        """Raise ValueError with a friendly reason when *member_id* cannot request *reward* now."""
        if not reward.available:
            raise ValueError('This reward is taking a break. Choose another one.')
        if reward.stock is not None and reward.stock <= 0:
            raise ValueError('This reward is out of stock right now.')
        history = family_query(RewardRequest).filter(
            RewardRequest.membership_id == member_id, RewardRequest.reward_id == reward.id,
            RewardRequest.state != 'declined',
        ).all()
        if any(row.state == 'pending' for row in history):
            raise ValueError('You already have a request for this reward waiting for an adult.')
        today = datetime.now(LONDON).date()
        if reward.cooldown_days and history:
            ready = local_date(max(row.created_at for row in history)) + timedelta(days=reward.cooldown_days)
            if today < ready:
                raise ValueError(f'You can ask for this again from {ready.strftime("%a %d %b")}.')
        if reward.member_limit:
            start = period_start(reward.limit_period, today)
            used = [row for row in history if start is None or row.created_at >= utc_start(start)]
            if len(used) >= reward.member_limit:
                raise ValueError(
                    f'This reward is limited to {reward.member_limit} {LIMIT_PERIODS[reward.limit_period]} '
                    'for each person.',
                )
        if balance is None:
            balance = RewardService.balance(member_id)
        if balance < reward.points_cost:
            raise ValueError('Keep going! You need more points for this reward.')

    @staticmethod
    def eligibility(reward, member_id, balance=None):
        try:
            RewardService.check_eligibility(reward, member_id, balance)
        except ValueError as error:
            return str(error)
        return None

    @staticmethod
    def request_reward(reward_id, data):
        membership = CalendarService.require_access()
        if not RewardService.is_participant(membership):
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
        RewardService.check_eligibility(reward, membership.id)
        if reward.stock is not None:
            reward.stock -= 1
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
    def _decline(reward_request, note, actor_id):
        reward_request.review_note = note
        reward_request.state = 'declined'
        reward_request.reviewed_at = _now()
        reward_request.reviewer_membership_id = actor_id
        if reward_request.reward is not None and reward_request.reward.stock is not None:
            reward_request.reward.stock = min(reward_request.reward.stock + 1, 1000)
        db.session.add(RewardPointEntry(
            family_id=reward_request.family_id, membership_id=reward_request.membership_id,
            actor_membership_id=actor_id, request_id=reward_request.id, kind='returned',
            points=reward_request.points_cost, description=reward_request.title, created_at=_now(),
        ))

    @staticmethod
    def _review_request(reward_request, action, note, membership):
        if action not in ('approve', 'decline'):
            raise ValueError('Choose approve or decline.')
        target = 'approved' if action == 'approve' else 'declined'
        if reward_request.state == target:
            return
        if reward_request.state != 'pending':
            raise ValueError(f'The request for "{reward_request.title}" has already been reviewed.')
        if reward_request.membership_id is None:
            raise ValueError('This member has left the household.')
        if action == 'decline' and not note:
            raise ValueError('Add a helpful note of up to 500 characters.')
        if action == 'approve' and reward_request.membership_id == membership.id:
            raise ValueError('Another adult needs to approve your own reward requests.')
        if target == 'declined':
            RewardService._decline(reward_request, note, membership.id)
            return
        reward_request.review_note = note
        reward_request.state = 'approved'
        reward_request.reviewed_at = _now()
        reward_request.reviewer_membership_id = membership.id

    @staticmethod
    def review_request(request_id, data):
        membership = RewardService.require_adult()
        RewardService._lock()
        reward_request = family_get_or_404(RewardRequest, request_id)
        action = data.get('action')
        note = RewardService._note(data, required=action == 'decline')
        RewardService._review_request(reward_request, action, note, membership)
        db.session.commit()
        return reward_request

    @staticmethod
    def cancel_request(request_id, data):
        membership = CalendarService.require_access()
        RewardService._lock()
        reward_request = family_get_or_404(RewardRequest, request_id)
        if reward_request.membership_id != membership.id:
            abort(403)
        if reward_request.state == 'declined':
            return reward_request
        if reward_request.state != 'pending':
            raise ValueError('An adult has already approved this request.')
        RewardService._decline(reward_request, 'Cancelled by the requester.', membership.id)
        db.session.commit()
        return reward_request

    @staticmethod
    def bulk_review(data):
        from services.household.reward_achievement_service import RewardAchievementService
        membership = RewardService.require_adult()
        RewardService._lock()
        kind = data.get('kind')
        action = data.get('action')
        if kind not in ('jobs', 'requests'):
            raise ValueError('Choose chores or reward requests to review.')
        ids = _ids(data, 'ids')
        if not ids:
            raise ValueError('Tick at least one item to review.')
        note = RewardService._note(data, required=action in ('return', 'decline'))
        awarded = set()
        for item_id in ids:
            if kind == 'jobs':
                job = family_get_or_404(RewardJob, item_id)
                if RewardService._review_job(job, action, note, membership):
                    awarded.add(job.membership_id)
            else:
                RewardService._review_request(family_get_or_404(RewardRequest, item_id), action, note, membership)
        db.session.flush()
        RewardAchievementService.evaluate(sorted(awarded))
        db.session.commit()
        return len(ids)

    @staticmethod
    def fulfil_requests(data):
        membership = RewardService.require_adult()
        RewardService._lock()
        ids = _ids(data, 'ids') or _ids(data, 'request_id')
        if not ids:
            raise ValueError('Tick at least one reward to mark as given.')
        for item_id in ids:
            reward_request = family_get_or_404(RewardRequest, item_id)
            if reward_request.state != 'approved':
                raise ValueError('Only approved rewards can be marked as given.')
            if reward_request.fulfilled_at is None:
                reward_request.fulfilled_at = _now()
                reward_request.fulfilled_by_membership_id = membership.id
        db.session.commit()
        return len(ids)

    # ----- Bonuses, goals and participation -----

    @staticmethod
    def award_points(data):
        from services.household.reward_achievement_service import RewardAchievementService
        membership = RewardService.require_adult()
        RewardService._lock()
        kind = data.get('kind') or 'bonus'
        if kind not in ('bonus', 'deduction'):
            raise ValueError('Choose a bonus or a deduction.')
        member = RewardService._participant(data.get('membership_id'))
        if member.id == membership.id:
            raise ValueError('Another adult needs to give you bonus points or deductions.')
        points = RewardService._integer(data.get('points'), 'points', 1000)
        reason = (data.get('reason') or '').strip()
        if not reason or len(reason) > 256:
            raise ValueError('Add a reason of up to 256 characters so everyone knows what it was for.')
        category = data.get('category') or 'other'
        if category not in RECOGNITION_CATEGORIES:
            raise ValueError('Choose a category from the list.')
        if kind == 'deduction':
            available = RewardService.balance(member.id)
            if available < points:
                raise ValueError(
                    f'{member.user.name} has {available} points available. Deductions cannot take a balance below zero.',
                )
        entry = RewardPointEntry(
            family_id=membership.family_id, membership_id=member.id, actor_membership_id=membership.id,
            kind=kind, points=points if kind == 'bonus' else -points, description=reason,
            category=category, created_at=_now(),
        )
        db.session.add(entry)
        db.session.flush()
        if kind == 'bonus':
            RewardAchievementService.evaluate([member.id])
        db.session.commit()
        return entry

    @staticmethod
    def set_goal(data):
        membership = CalendarService.require_access()
        member = membership
        target_id = data.get('membership_id')
        if target_id not in ('', None) and str(target_id) != str(membership.id):
            RewardService.require_adult()
            member = RewardService._participant(target_id)
        elif not RewardService.is_participant(membership):
            abort(403)
        member_id = member.id
        RewardService._lock()
        action = data.get('action') or 'add'
        if action not in ('add', 'remove', 'clear'):
            raise ValueError('Choose whether to add or remove a goal.')
        goals = family_query(RewardGoal).filter_by(membership_id=member_id).all()
        if action == 'clear' or not data.get('reward_id'):
            for goal in goals:
                db.session.delete(goal)
            db.session.commit()
            return
        reward = family_get_or_404(Reward, data['reward_id'])
        existing = next((goal for goal in goals if goal.reward_id == reward.id), None)
        if action == 'remove':
            if existing:
                db.session.delete(existing)
            db.session.commit()
            return
        if existing:
            return
        if not reward.available:
            raise ValueError('Choose an available reward for a goal.')
        stale = [goal for goal in goals if goal.reward_id is None]
        for goal in stale:
            db.session.delete(goal)
        if len(goals) - len(stale) >= MAX_GOALS:
            raise ValueError(f'Choose up to {MAX_GOALS} goals. Remove one to add another.')
        db.session.add(RewardGoal(family_id=member.family_id, membership_id=member_id, reward_id=reward.id))
        db.session.commit()

    @staticmethod
    def goals(member_id):
        rows = family_query(RewardGoal).filter_by(membership_id=member_id).order_by(RewardGoal.id).all()
        return [row.reward for row in rows if row.reward and row.reward.available]

    @staticmethod
    def set_participation(data):
        membership = RewardService.require_adult()
        enabled = data.get('enabled')
        if enabled not in ('yes', 'no'):
            raise ValueError('Choose whether this adult earns points.')
        target = RewardService._member(data.get('membership_id') or membership.id)
        if target is None or not target.user.is_active or target.user.is_managed_child:
            raise ValueError('Choose an adult in this household.')
        if target.id != membership.id and not current_user.is_household_owner:
            abort(403)
        RewardService._lock()
        if enabled == 'yes' and not ModuleAccessService.can_access(target.user, 'household', target.family_id):
            raise ValueError(f'Give {target.user.name} Household Hub access first.')
        if enabled == 'no' and (
            family_query(RewardJob).filter(
                RewardJob.membership_id == target.id, RewardJob.state.in_(('open', 'submitted')),
            ).first() or family_query(RewardRequest).filter_by(membership_id=target.id, state='pending').first()
        ):
            raise ValueError('Finish or close their open chores and reward requests first.')
        target.rewards_participant = enabled == 'yes'
        db.session.commit()
        return target

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

    # ----- Chore library -----

    @staticmethod
    def save_template(data, template_id=None):
        membership = RewardService.require_adult()
        RewardService._lock()
        template = family_get_or_404(RewardChoreTemplate, template_id) if template_id else RewardChoreTemplate(
            family_id=membership.family_id,
        )
        title = (data.get('title') or '').strip()
        notes = (data.get('notes') or '').strip()
        if not title or len(title) > 256:
            raise ValueError('Enter a chore name of up to 256 characters.')
        if len(notes) > 5000:
            raise ValueError('Use up to 5,000 characters for chore notes.')
        template.title = title
        template.notes = notes
        template.points = RewardService._integer(data.get('points'), 'chore points', 1000)
        db.session.add(template)
        db.session.commit()
        return template

    @staticmethod
    def delete_template(data):
        RewardService.require_adult()
        RewardService._lock()
        db.session.delete(family_get_or_404(RewardChoreTemplate, data.get('template_id')))
        db.session.commit()

    # ----- Page data -----

    @staticmethod
    def celebration_data(membership):
        family = membership.family
        child = current_user.is_managed_child
        members = RewardService.participants()
        if child and not family.rewards_board_enabled:
            members = [member for member in members if member.id == membership.id]
        ids = [member.id for member in members]
        today = datetime.now(LONDON).date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=7)
        starts_at, ends_at = utc_start(week_start), utc_start(week_end)
        in_week = (RewardPointEntry.created_at >= starts_at) & (RewardPointEntry.created_at < ends_at)
        # Opt-in sharing exposes earned totals and achievements only, never ledger rows or spending.
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
        unlocks = {}
        for unlock in family_query(RewardAchievementUnlock, include_private=True).filter(
            RewardAchievementUnlock.membership_id.in_(ids),
        ).order_by(RewardAchievementUnlock.unlocked_at).all() if ids else []:
            unlocks.setdefault(unlock.membership_id, []).append((unlock.title, '', True, unlock.icon))
        cards = []
        for member in members:
            points, jobs, week_points, week_jobs = earned.get(member.id, (0, 0, 0, 0))
            cards.append(dict(
                name=member.user.name, is_you=member.id == membership.id,
                earned=points, jobs=jobs, milestones=unlocks.get(member.id, []),
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
    def refresh():
        """Generate due recurring chores and unlock any newly earned achievements."""
        from services.household.reward_achievement_service import RewardAchievementService
        from services.household.task_service import TaskService
        TaskService.refresh_recurring()
        RewardAchievementService.refresh()

    @staticmethod
    def my_chores(membership):
        """The current member's own chores, balance and goals."""
        today = datetime.now(LONDON).date()
        jobs = family_query(RewardJob).filter_by(membership_id=membership.id).order_by(RewardJob.id.desc()).all()
        active = [job for job in jobs if job.state == 'open' and job.task]
        pending = family_query(RewardRequest).filter_by(membership_id=membership.id, state='pending').all()
        goals = RewardService.goals(membership.id)
        return dict(
            today=today,
            jobs=[job for job in active if job.task.due_date is None or job.task.due_date >= today],
            earlier_jobs=[job for job in active if job.task.due_date is not None and job.task.due_date < today],
            submitted_jobs=[job for job in jobs if job.state == 'submitted' and job.task],
            balance=RewardService.balance(membership.id), goals=goals, goal=goals[0] if goals else None,
            pending=pending,
        )

    @staticmethod
    def common(membership):
        adult = not current_user.is_managed_child
        participant = RewardService.is_participant(membership)
        context = dict(
            viewer=membership, viewer_id=membership.id, is_adult=adult, child_view=not adult,
            is_participant=participant, today=datetime.now(LONDON).date(), icons=REWARD_ICONS,
            categories=REWARD_CATEGORIES, recognition_categories=RECOGNITION_CATEGORIES,
            limit_periods=LIMIT_PERIODS, reward_service=RewardService, approvals_count=0,
        )
        if adult:
            jobs = family_query(RewardJob).filter(
                RewardJob.state == 'submitted', RewardJob.membership_id.isnot(None),
                RewardJob.membership_id != membership.id,
            ).count()
            requests = family_query(RewardRequest).filter(
                RewardRequest.state == 'pending', RewardRequest.membership_id.isnot(None),
                RewardRequest.membership_id != membership.id,
            ).count()
            owed = family_query(RewardRequest).filter(
                RewardRequest.state == 'approved', RewardRequest.fulfilled_at.is_(None),
            ).count()
            context['approvals_count'] = jobs + requests + owed
        if participant:
            context.update(RewardService.my_chores(membership))
            context['request_keys'] = {}
        return context

    @staticmethod
    def overview_data():
        from services.household.reward_activity_service import RewardActivityService
        membership = CalendarService.require_access()
        RewardService.refresh()
        context = RewardService.common(membership)
        board_enabled, celebration, week_start, week_end = RewardService.celebration_data(membership)
        people = RewardService.participants() if context['is_adult'] else []
        summaries = [RewardActivityService.member_summary(member, recent=0) for member in people]
        rewards = family_query(Reward).filter_by(available=True).order_by(Reward.points_cost, Reward.id).all()
        context.update(
            board_enabled=board_enabled, celebration=celebration, board_week_start=week_start,
            board_week_end=week_end, people=people, summaries=summaries,
            personal=RewardActivityService.member_summary(membership) if context['is_participant'] else None,
            featured_rewards=rewards[:3], available_reward_count=len(rewards),
            recent=RewardActivityService.timeline(limit=8),
        )
        return context

    @staticmethod
    def chores_data():
        membership = CalendarService.require_access()
        RewardService.refresh()
        context = RewardService.common(membership)
        if context['is_adult']:
            today = context['today']
            jobs = family_query(RewardJob).filter(
                RewardJob.state.in_(('open', 'submitted')), RewardJob.membership_id.isnot(None),
                RewardJob.task_id.isnot(None),
            ).order_by(RewardJob.id.desc()).all()
            open_jobs = [job for job in jobs if job.state == 'open' and job.membership_id != membership.id]
            context.update(
                household_jobs=[job for job in open_jobs if job.task.due_date is None or job.task.due_date >= today],
                household_earlier=[job for job in open_jobs if job.task.due_date is not None and job.task.due_date < today],
                household_waiting=[job for job in jobs if job.state == 'submitted'],
                people=RewardService.participants(),
                lists=family_query(TaskList).filter_by(visibility='shared').order_by(TaskList.title).all(),
                templates=family_query(RewardChoreTemplate).order_by(RewardChoreTemplate.title).all(),
            )
        history = family_query(RewardJob).filter(RewardJob.state.in_(('approved', 'closed'))).order_by(
            RewardJob.reviewed_at.desc().nullslast(), RewardJob.id.desc(),
        ).limit(30).all()
        context['job_history'] = history
        return context

    @staticmethod
    def shop_data(category=None):
        membership = CalendarService.require_access()
        RewardService.refresh()
        context = RewardService.common(membership)
        if category and category not in REWARD_CATEGORIES:
            raise ValueError('Choose a reward category from the list.')
        rewards = family_query(Reward).order_by(Reward.points_cost, Reward.id).all()
        if not context['is_adult']:
            rewards = [row for row in rewards if row.available]
        counts = {}
        for row in rewards:
            counts[row.category] = counts.get(row.category, 0) + 1
        if category:
            rewards = [row for row in rewards if row.category == category]
        status = {}
        if context['is_participant']:
            balance = context['balance']
            status = {row.id: RewardService.eligibility(row, membership.id, balance) for row in rewards}
            context['request_keys'] = {row.id: str(uuid4()) for row in rewards}
            context['my_requests'] = family_query(RewardRequest).filter_by(membership_id=membership.id).order_by(
                RewardRequest.id.desc(),
            ).limit(20).all()
        context.update(
            rewards=rewards, category=category, category_counts=counts, status=status,
            goal_ids={row.id for row in context.get('goals', [])}, max_goals=MAX_GOALS,
        )
        return context

    @staticmethod
    def approvals_data():
        membership = RewardService.require_adult()
        RewardService.refresh()
        context = RewardService.common(membership)
        jobs = family_query(RewardJob).filter(
            RewardJob.state == 'submitted', RewardJob.membership_id.isnot(None), RewardJob.task_id.isnot(None),
        ).order_by(RewardJob.submitted_at, RewardJob.id).all()
        requests = family_query(RewardRequest).filter(
            RewardRequest.state == 'pending', RewardRequest.membership_id.isnot(None),
        ).order_by(RewardRequest.created_at, RewardRequest.id).all()
        owed = family_query(RewardRequest).filter(
            RewardRequest.state == 'approved', RewardRequest.fulfilled_at.is_(None),
        ).order_by(RewardRequest.reviewed_at, RewardRequest.id).all()
        context.update(submitted_jobs=jobs, pending=requests, owed=owed)
        return context

    @staticmethod
    def settings_data():
        from services.household.reward_achievement_service import (
            ACHIEVEMENT_ICONS, ACHIEVEMENT_METRICS, RewardAchievementService,
        )
        membership = RewardService.require_adult()
        RewardService.refresh()
        context = RewardService.common(membership)
        templates = family_query(RewardChoreTemplate).order_by(RewardChoreTemplate.title).all()
        names = {row.title.casefold() for row in templates}
        adults = [
            member for member in CalendarService.members()
            if not member.user.is_managed_child and ModuleAccessService.can_access(
                member.user, 'household', member.family_id,
            )
        ]
        context.update(
            rewards=family_query(Reward).order_by(Reward.points_cost, Reward.id).all(),
            templates=templates,
            starters=[row for row in STARTER_CHORES if row[0].casefold() not in names],
            achievements=RewardAchievementService.all(),
            achievement_icons=ACHIEVEMENT_ICONS, achievement_metrics=ACHIEVEMENT_METRICS,
            adults=adults, board_enabled=membership.family.rewards_board_enabled,
            can_manage_people=current_user.is_household_owner,
        )
        return context

    # ----- Lifecycle -----

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
            RewardService._decline(reward_request, 'The member left the household.', None)
        db.session.flush()
        for model, keys in (
            (RewardJob, ('membership_id', 'reviewer_membership_id')),
            (RewardRequest, ('membership_id', 'reviewer_membership_id', 'fulfilled_by_membership_id')),
            (RewardPointEntry, ('membership_id', 'actor_membership_id')),
            (RewardGoal, ('membership_id',)),
            (RewardAchievementUnlock, ('membership_id',)),
        ):
            for key in keys:
                family_query(model, include_private=True).filter(getattr(model, key) == membership.id).update(
                    {key: None}, synchronize_session=False,
                )
