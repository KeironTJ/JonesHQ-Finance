from datetime import date, datetime, timedelta, timezone

from flask import abort
from flask_login import current_user
from sqlalchemy import case
from sqlalchemy.orm import joinedload

from extensions import db
from models.family import HouseholdMembership
from models.household_tasks import HouseholdTask, TaskList
from services.household.calendar_service import CalendarService, LONDON
from utils.db_helpers import family_get, family_get_or_404, family_query


PRIORITIES = {'low': 'Low', 'medium': 'Medium', 'high': 'High', 'urgent': 'Urgent'}
FILTERS = {'active': 'Active', 'all': 'All', 'today': 'Today', 'overdue': 'Overdue', 'completed': 'Completed', 'mine': 'Assigned to me'}
ICONS = {'list-check': 'Checklist', 'house': 'Home', 'cart': 'Shopping', 'book': 'School', 'heart': 'Personal', 'star': 'Starred', 'airplane': 'Travel'}
COLOURS = {'primary': 'Primary', 'success': 'Green', 'warning': 'Amber', 'danger': 'Red', 'info': 'Blue', 'secondary': 'Grey'}


class TaskService:
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
        membership = CalendarService.require_access()
        task_list = TaskList(
            family_id=membership.family_id, creator_membership_id=membership.id,
            **TaskService._list_values(data),
        )
        db.session.add(task_list)
        db.session.commit()
        return task_list

    @staticmethod
    def update_list(list_id, data):
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
        task_list = TaskService.get_list(list_id)
        if not TaskService.can_manage_list(task_list):
            abort(403)
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
        membership = CalendarService.require_access()
        try:
            task_list = family_get(TaskList, data.get('list_id'))
        except (TypeError, ValueError) as error:
            raise ValueError('Choose a visible task list in this household.') from error
        if task_list is None:
            raise ValueError('Choose a visible task list in this household.')
        if not TaskService.can_manage_list(task_list):
            abort(403)
        task = HouseholdTask(
            family_id=membership.family_id, list_id=task_list.id,
            creator_membership_id=membership.id, **TaskService._task_values(data, task_list),
        )
        db.session.add(task)
        db.session.commit()
        return task

    @staticmethod
    def update_task(task_id, data):
        task = TaskService.get_task(task_id)
        if not TaskService.can_manage_list(task.task_list):
            abort(403)
        if 'list_id' in data and str(data['list_id']) != str(task.list_id):
            raise ValueError('Tasks cannot be moved between lists. Create a separate task instead.')
        values = TaskService._task_values(data, task.task_list)
        for key, value in values.items():
            setattr(task, key, value)
        db.session.commit()
        return task

    @staticmethod
    def set_completion(task_id, data):
        task = TaskService.get_task(task_id)
        if not TaskService.can_complete(task):
            abort(403)
        action = data.get('action')
        if action not in ('complete', 'reopen'):
            raise ValueError('Choose complete or reopen.')
        completed = action == 'complete'
        if task.completed != completed:
            task.completed = completed
            task.completed_at = datetime.now(timezone.utc).replace(tzinfo=None) if completed else None
            task.completed_by_membership_id = CalendarService.require_access().id if completed else None
        db.session.commit()
        return task

    @staticmethod
    def delete_task(task_id):
        task = TaskService.get_task(task_id)
        if not TaskService.can_manage_list(task.task_list):
            abort(403)
        list_id = task.list_id
        db.session.delete(task)
        db.session.commit()
        return list_id

    @staticmethod
    def hub(data):
        membership = CalendarService.require_access()
        lists = family_query(TaskList).order_by(TaskList.id).all()
        selected = TaskService.get_list(data['list_id']) if data.get('list_id') else (lists[0] if lists else None)
        filt = data.get('filter') or 'active'
        if filt not in FILTERS:
            raise ValueError('Choose a supported task filter.')
        today = datetime.now(LONDON).date()
        all_tasks = family_query(HouseholdTask).all()
        query = family_query(HouseholdTask).filter_by(list_id=selected.id) if selected else None
        tasks = []
        if query is not None:
            if filt in ('active', 'today', 'overdue', 'mine'):
                query = query.filter(HouseholdTask.completed.is_(False))
            if filt == 'completed':
                query = query.filter(HouseholdTask.completed.is_(True))
            elif filt == 'today':
                query = query.filter(HouseholdTask.due_date == today)
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
                'today': sum(not row.completed and row.due_date == today for row in all_tasks),
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
        return family_query(HouseholdTask).filter(
            HouseholdTask.completed.is_(False), HouseholdTask.due_date >= first, HouseholdTask.due_date <= last,
        ).order_by(HouseholdTask.due_date, HouseholdTask.due_time, HouseholdTask.id).all()

    @staticmethod
    def detach_membership(membership):
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
