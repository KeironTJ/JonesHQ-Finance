from datetime import date, datetime, timedelta, timezone

from flask import abort
from flask_login import current_user
from sqlalchemy import case, or_
from sqlalchemy.orm import joinedload

from extensions import db
from models.family import HouseholdMembership
from models.household_tasks import HouseholdTask, TaskList
from models.rewards import RewardJob
from services.household.calendar_service import CalendarService, LONDON
from utils.db_helpers import family_get, family_get_or_404, family_query


PRIORITIES = {'low': 'Low', 'medium': 'Medium', 'high': 'High', 'urgent': 'Urgent'}
FILTERS = {'active': 'Active', 'all': 'All', 'today': 'Today', 'overdue': 'Overdue', 'completed': 'Completed', 'mine': 'Assigned to me'}
ICONS = {'list-check': 'Checklist', 'house': 'Home', 'cart': 'Shopping', 'book': 'School', 'heart': 'Personal', 'star': 'Starred', 'airplane': 'Travel'}
COLOURS = {'primary': 'Primary', 'success': 'Green', 'warning': 'Amber', 'danger': 'Red', 'info': 'Blue', 'secondary': 'Grey'}


class TaskService:
    @staticmethod
    def configure_recurrence(task, data):
        recurrence = data.get('recurrence', task.recurrence or 'none')
        policy = data.get('missed_policy', task.missed_policy or 'skip')
        if recurrence not in ('none', 'daily', 'weekly') or policy not in ('skip', 'backlog'):
            raise ValueError('Choose a supported repeat interval and missed-task policy.')
        if task.series_id:
            if recurrence != 'none':
                raise ValueError('Change the repeat schedule on the original task.')
            return
        if task.period_start:
            if recurrence != task.recurrence or policy != task.missed_policy:
                raise ValueError('Repeat interval and missed-task policy cannot change. Stop this series and create a new task.')
            active = data.get('repeat_active', 'yes' if task.repeat_active else 'no')
            if active not in ('yes', 'no'):
                raise ValueError('Choose whether this task should keep repeating.')
            if not task.repeat_active and active == 'yes':
                raise ValueError('This series has stopped. Create a new repeating task to start again.')
            task.repeat_active = active == 'yes'
            return
        if recurrence != 'none':
            today = datetime.now(LONDON).date()
            if task.completed or task.reward_job and task.reward_job.state not in (None, 'open'):
                raise ValueError('Start repeats from a new unfinished task.')
            if task.due_date is None or task.due_date < today:
                raise ValueError('Choose today or a future start date for a repeating task.')
            task.period_start = task.due_date if recurrence == 'daily' else task.due_date - timedelta(days=task.due_date.weekday())
            task.due_date = task.period_start + timedelta(days=0 if recurrence == 'daily' else 6)
            if task.due_date.year > 2100:
                raise ValueError('Choose a repeat interval ending by 2100.')
        task.recurrence, task.missed_policy = recurrence, policy

    @staticmethod
    def refresh_recurring(commit=True):
        from services.household.reward_service import RewardService
        CalendarService.require_access()
        roots = family_query(HouseholdTask).filter(HouseholdTask.recurrence != 'none').all()
        if not roots:
            return
        RewardService._lock()
        today = datetime.now(LONDON).date()
        for root in roots:
            step = 1 if root.recurrence == 'daily' else 7
            occurrences = [root] + family_query(HouseholdTask).filter_by(series_id=root.id).all()
            existing = {row.period_start for row in occurrences}
            current = today if step == 1 else today - timedelta(days=today.weekday())
            if root.repeat_active and root.period_start <= current:
                last_start = max(existing)
                start = last_start + timedelta(days=step)
                while start <= current and (start + timedelta(days=step - 1)).year <= 2100:
                    expired = root.missed_policy == 'skip' and start < current
                    task = HouseholdTask(
                        family_id=root.family_id, list_id=root.list_id,
                        creator_membership_id=root.creator_membership_id,
                        assigned_membership_id=root.assigned_membership_id,
                        title=root.title, notes=root.notes, priority=root.priority,
                        due_date=start + timedelta(days=step - 1), due_time=root.due_time,
                        series_id=root.id, period_start=start, expired=expired,
                        claim_required=root.claim_required,
                    )
                    if root.reward_job and root.assigned_membership_id and root.assignee.user.is_active:
                        task.reward_job = RewardJob(
                            family_id=root.family_id, membership_id=root.assigned_membership_id,
                            title=root.title, points=root.reward_job.points,
                            state='closed' if expired else 'open',
                            review_note='Not completed in its interval.' if expired else '',
                        )
                    db.session.add(task)
                    occurrences.append(task)
                    start += timedelta(days=step)
            for task in occurrences:
                if root.missed_policy == 'skip' and task.due_date < today and not task.completed and (
                    not task.reward_job or task.reward_job.state == 'open'
                ):
                    task.expired = True
                    if task.reward_job:
                        task.reward_job.state = 'closed'
                        task.reward_job.review_note = 'Not completed in its interval.'
        if commit:
            db.session.commit()

    @staticmethod
    def get_list(list_id):
        CalendarService.require_access()
        return family_get_or_404(TaskList, list_id)

    @staticmethod
    def get_task(task_id):
        CalendarService.require_access()
        task = family_get_or_404(HouseholdTask, task_id)
        TaskService.get_list(task.list_id)
        return task

    @staticmethod
    def can_manage_list(task_list):
        membership = CalendarService.require_access()
        if task_list.family_id != membership.family_id:
            return False
        if task_list.visibility == 'personal':
            return task_list.creator_membership_id == membership.id
        return not current_user.is_managed_child

    @staticmethod
    def can_complete(task):
        membership = CalendarService.require_access()
        if task.family_id != membership.family_id:
            return False
        if task.task_list.visibility == 'personal':
            return task.task_list.creator_membership_id == membership.id
        return not current_user.is_managed_child or task.assigned_membership_id == membership.id

    @staticmethod
    def _list_values(data, existing=None):
        title = (data.get('title') or '').strip()
        visibility = data.get('visibility', existing.visibility if existing else 'personal')
        icon = data.get('icon', 'list-check')
        colour = data.get('colour', 'primary')
        if not title or len(title) > 128:
            raise ValueError('Enter a list name of up to 128 characters.')
        if visibility not in ('personal', 'shared'):
            raise ValueError('Choose a personal or shared list.')
        if existing and visibility != existing.visibility:
            raise ValueError('List privacy cannot be changed. Create a separate list instead.')
        if visibility == 'shared' and current_user.is_managed_child:
            abort(403)
        if icon not in ICONS or colour not in COLOURS:
            raise ValueError('Choose an icon and colour from the list.')
        return dict(title=title, visibility=visibility, icon=icon, colour=colour)

    @staticmethod
    def create_list(data):
        from services.household.reward_service import RewardService
        membership = RewardService._lock()
        task_list = TaskList(
            family_id=membership.family_id, creator_membership_id=membership.id,
            **TaskService._list_values(data),
        )
        db.session.add(task_list)
        db.session.commit()
        return task_list

    @staticmethod
    def update_list(list_id, data):
        from services.household.reward_service import RewardService
        RewardService._lock()
        task_list = TaskService.get_list(list_id)
        if not TaskService.can_manage_list(task_list):
            abort(403)
        values = TaskService._list_values(data, task_list)
        for key, value in values.items():
            setattr(task_list, key, value)
        db.session.commit()
        return task_list

    @staticmethod
    def delete_list(list_id):
        from services.household.reward_service import RewardService
        RewardService._lock()
        task_list = TaskService.get_list(list_id)
        if not TaskService.can_manage_list(task_list):
            abort(403)
        RewardService.detach_tasks(task_list.tasks)
        db.session.delete(task_list)
        db.session.commit()

    @staticmethod
    def parse_date(value):
        try:
            selected = date.fromisoformat(value)
        except (ValueError, TypeError) as error:
            raise ValueError('Choose a valid task due date.') from error
        if not 1900 <= selected.year <= 2100:
            raise ValueError('Choose a task due date between 1900 and 2100.')
        return selected

    @staticmethod
    def _task_values(data, task_list):
        title = (data.get('title') or '').strip()
        notes = (data.get('notes') or '').strip()
        priority = data.get('priority') or 'medium'
        if not title or len(title) > 256:
            raise ValueError('Enter a task title of up to 256 characters.')
        if len(notes) > 5000:
            raise ValueError('Use up to 5,000 characters for task notes.')
        if priority not in PRIORITIES:
            raise ValueError('Choose a supported task priority.')
        due_date = TaskService.parse_date(data['due_date']) if data.get('due_date') else None
        due_time = None
        if data.get('due_time'):
            if due_date is None:
                raise ValueError('Choose a due date before adding a due time.')
            instant = CalendarService._local_datetime(f'{due_date.isoformat()}T{data["due_time"]}', 'due')
            due_time = CalendarService.local_time(instant).time().replace(tzinfo=None)
        assigned_id = data.get('assigned_membership_id')
        assignee = None
        if assigned_id not in ('', None):
            try:
                assignee = family_get(HouseholdMembership, assigned_id)
            except (TypeError, ValueError) as error:
                raise ValueError('Choose an active assignee from this household.') from error
            if assignee is None or not assignee.user.is_active:
                raise ValueError('Choose an active assignee from this household.')
            if task_list.visibility == 'personal' and assignee.id != task_list.creator_membership_id:
                raise ValueError('Personal tasks can only be assigned to their list creator.')
        return dict(
            title=title, notes=notes, priority=priority, due_date=due_date,
            due_time=due_time, assigned_membership_id=assignee.id if assignee else None,
        )

    @staticmethod
    def create_task(data):
        from services.household.reward_service import RewardService
        membership = RewardService._lock()
        try:
            task_list = family_get(TaskList, data.get('list_id'))
        except (TypeError, ValueError) as error:
            raise ValueError('Choose a visible task list in this household.') from error
        if task_list is None:
            raise ValueError('Choose a visible task list in this household.')
        if not TaskService.can_manage_list(task_list):
            abort(403)
        task = HouseholdTask(
            family_id=membership.family_id, task_list=task_list,
            creator_membership_id=membership.id, **TaskService._task_values(data, task_list),
        )
        db.session.add(task)
        RewardService.configure_task(task, data)
        TaskService.configure_recurrence(task, data)
        db.session.commit()
        return task

    @staticmethod
    def update_task(task_id, data):
        from services.household.reward_service import RewardService
        RewardService._lock()
        TaskService.refresh_recurring(commit=False)
        task = TaskService.get_task(task_id)
        if not TaskService.can_manage_list(task.task_list):
            abort(403)
        if 'list_id' in data and str(data['list_id']) != str(task.list_id):
            raise ValueError('Tasks cannot be moved between lists. Create a separate task instead.')
        if task.recurrence != 'none':
            if 'title' in data:
                values = TaskService._task_values(data, task.task_list)
                if any(value != getattr(task, key) for key, value in values.items()):
                    raise ValueError('A repeating series keeps its original details. Stop it and create a new task to change them.')
            if data.get('reward_points') not in (None, '', str(task.reward_job.points) if task.reward_job else ''):
                raise ValueError('A repeating series keeps its original points. Stop it and create a new task to change them.')
            TaskService.configure_recurrence(task, data)
            db.session.commit()
            return task
        values = TaskService._task_values(data, task.task_list)
        if task.period_start and values['due_date'] != task.due_date:
            raise ValueError('A recurring occurrence keeps its original interval date.')
        for key, value in values.items():
            setattr(task, key, value)
        RewardService.configure_task(task, data)
        TaskService.configure_recurrence(task, data)
        db.session.commit()
        return task

    @staticmethod
    def set_completion(task_id, data):
        from services.household.reward_service import RewardService
        RewardService._lock()
        TaskService.refresh_recurring(commit=False)
        task = TaskService.get_task(task_id)
        if not TaskService.can_complete(task):
            abort(403)
        if task.expired:
            raise ValueError('This interval was not completed in time. Choose the current occurrence instead.')
        root = task.series or task
        if task.period_start and root.missed_policy == 'skip' and task.due_date < datetime.now(LONDON).date():
            raise ValueError('Past intervals cannot be completed or reopened. Choose the current occurrence.')
        if task.period_start and task.period_start > datetime.now(LONDON).date():
            raise ValueError('This repeat interval has not started yet.')
        if task.claim_required and task.claimed_at is None:
            raise ValueError('Claim this job in Rewards before completing it.')
        action = data.get('action')
        if action not in ('complete', 'reopen'):
            raise ValueError('Choose complete or reopen.')
        completed = action == 'complete'
        if task.completed != completed:
            task.completed = completed
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None) if completed else None
            task.completed_by_membership_id = CalendarService.require_access().id if completed else None
            RewardService.completion_changed(task, completed)
        db.session.commit()
        return task

    @staticmethod
    def delete_task(task_id):
        from services.household.reward_service import RewardService
        RewardService._lock()
        task = TaskService.get_task(task_id)
        if not TaskService.can_manage_list(task.task_list):
            abort(403)
        list_id = task.list_id
        if task.period_start:
            raise ValueError('Stop this repeating task instead of deleting its occurrence history.')
        RewardService.detach_tasks([task])
        db.session.delete(task)
        db.session.commit()
        return list_id

    @staticmethod
    def hub(data):
        membership = CalendarService.require_access()
        TaskService.refresh_recurring()
        lists = family_query(TaskList).order_by(TaskList.id).all()
        selected = TaskService.get_list(data['list_id']) if data.get('list_id') else (lists[0] if lists else None)
        filt = data.get('filter') or 'active'
        if filt not in FILTERS:
            raise ValueError('Choose a supported task filter.')
        today = datetime.now(LONDON).date()
        all_tasks = family_query(HouseholdTask).filter_by(expired=False).all()
        query = family_query(HouseholdTask).filter_by(list_id=selected.id) if selected else None
        tasks = []
        if query is not None:
            if filt in ('active', 'today', 'overdue', 'mine'):
                query = query.filter(HouseholdTask.completed.is_(False), HouseholdTask.expired.is_(False))
            if filt == 'completed':
                query = query.filter(HouseholdTask.completed.is_(True))
            elif filt == 'today':
                query = query.filter(or_(
                    HouseholdTask.due_date == today,
                    (HouseholdTask.period_start <= today) & (HouseholdTask.due_date >= today),
                ))
            elif filt == 'overdue':
                query = query.filter(HouseholdTask.due_date < today)
            elif filt == 'mine':
                query = query.filter(HouseholdTask.assigned_membership_id == membership.id)
            tasks = query.options(joinedload(HouseholdTask.assignee), joinedload(HouseholdTask.completer)).order_by(
                HouseholdTask.completed,
                case({'urgent': 0, 'high': 1, 'medium': 2, 'low': 3}, value=HouseholdTask.priority),
                HouseholdTask.due_date.asc().nullslast(), HouseholdTask.due_time.asc().nullslast(), HouseholdTask.id,
            ).all()
        return dict(
            lists=lists, active_list=selected, tasks=tasks, filt=filt, today=today,
            stats={
                'total': len(all_tasks), 'done': sum(row.completed for row in all_tasks),
                'overdue': sum(not row.completed and row.due_date is not None and row.due_date < today for row in all_tasks),
                'today': sum(not row.completed and (
                    row.due_date == today or row.period_start is not None and row.period_start <= today <= row.due_date
                ) for row in all_tasks),
                'upcoming': sum(not row.completed and row.due_date is not None and today < row.due_date <= today + timedelta(days=7) for row in all_tasks),
            },
            task_service=TaskService, filters=FILTERS,
        )

    @staticmethod
    def form_data(task=None):
        CalendarService.require_access()
        lists = family_query(TaskList).order_by(TaskList.title, TaskList.id).all()
        return dict(
            task=task, lists=[row for row in lists if TaskService.can_manage_list(row)],
            members=CalendarService.members(), priorities=PRIORITIES, task_service=TaskService,
            can_manage=task is None or TaskService.can_manage_list(task.task_list),
        )

    @staticmethod
    def between(first, last):
        CalendarService.require_access()
        TaskService.refresh_recurring()
        return family_query(HouseholdTask).filter(
            HouseholdTask.completed.is_(False), HouseholdTask.expired.is_(False),
            HouseholdTask.due_date >= first, HouseholdTask.due_date <= last,
        ).order_by(HouseholdTask.due_date, HouseholdTask.due_time, HouseholdTask.id).all()

    @staticmethod
    def detach_membership(membership):
        for root in family_query(HouseholdTask, include_private=True).filter(
            HouseholdTask.recurrence != 'none',
            HouseholdTask.assigned_membership_id == membership.id,
            HouseholdTask.reward_job.has(),
        ).all():
            root.repeat_active = False
        lists = family_query(TaskList, include_private=True).filter_by(
            creator_membership_id=membership.id, visibility='personal',
        ).all()
        for task_list in lists:
            db.session.delete(task_list)
        db.session.flush()
        family_query(TaskList, include_private=True).filter_by(
            creator_membership_id=membership.id,
        ).update({'creator_membership_id': None}, synchronize_session=False)
        for key in ('creator_membership_id', 'assigned_membership_id', 'completed_by_membership_id'):
            family_query(HouseholdTask, include_private=True).filter(
                getattr(HouseholdTask, key) == membership.id,
            ).update({key: None}, synchronize_session=False)
