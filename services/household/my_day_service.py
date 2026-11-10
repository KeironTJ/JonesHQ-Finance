from flask import abort
from flask_login import current_user
from sqlalchemy import and_, or_

from models.calendar_event import CalendarEvent
from models.household_tasks import HouseholdTask, TaskList
from services.household.activity_service import ActivityService
from services.household.calendar_service import CalendarService
from services.household.reward_service import RewardService
from utils.db_helpers import family_query


class MyDayService:
    @staticmethod
    def page_data():
        membership = CalendarService.require_access()
        if not current_user.is_managed_child:
            abort(403)
        rewards = RewardService.page_data('jobs')
        today = rewards['today']
        tasks = family_query(HouseholdTask).join(TaskList).filter(
            HouseholdTask.completed.is_(False),
            ~HouseholdTask.reward_job.has(),
            or_(
                HouseholdTask.assigned_membership_id == membership.id,
                and_(TaskList.visibility == 'personal', TaskList.creator_membership_id == membership.id),
            ),
        ).order_by(HouseholdTask.due_date.asc().nullsfirst(), HouseholdTask.id).all()
        return dict(
            today=today, activities=ActivityService.between(today, today),
            events=family_query(CalendarEvent).filter(
                CalendarEvent.starts_on <= today, CalendarEvent.ends_on >= today,
            ).order_by(CalendarEvent.starts_at, CalendarEvent.id).all(),
            tasks=[task for task in tasks if task.due_date is None or task.due_date == today],
            earlier_tasks=[task for task in tasks if task.due_date is not None and task.due_date < today],
            later_tasks=[task for task in tasks if task.due_date is not None and task.due_date > today],
            reward_jobs=[job for job in rewards['jobs'] if job.task.due_date is None or job.task.due_date == today],
            later_jobs=[job for job in rewards['jobs'] if job.task.due_date is not None and job.task.due_date > today],
            earlier_jobs=rewards['earlier_jobs'], submitted_jobs=rewards['submitted_jobs'],
            balance=rewards['balance'], goal=rewards['goal'],
            pending_points=sum(row.points_cost for row in rewards['pending']),
            calendar_service=CalendarService, child_view=True,
        )
