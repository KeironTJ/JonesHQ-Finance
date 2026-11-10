from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from flask import abort
from flask_login import current_user
from sqlalchemy.orm import joinedload, selectinload

from extensions import db
from models.activities import Activity, ActivityAttendee
from models.family import HouseholdMembership
from services.household.calendar_service import CalendarService, LONDON
from services.household.planner_helpers import planner_period, planner_view
from utils.db_helpers import family_get, family_get_or_404, family_query


@dataclass(frozen=True)
class ActivityOccurrence:
    activity: Activity
    starts_on: date
    ends_on: date
    starts_at: datetime | None
    ends_at: datetime | None


class ActivityService:
    @staticmethod
    def require_manage():
        CalendarService.require_access()
        if current_user.is_managed_child:
            abort(403)

    @staticmethod
    def can_edit(activity):
        membership = CalendarService.require_access()
        return activity.family_id == membership.family_id and (
            not current_user.is_managed_child
            or activity.creator_membership_id == membership.id and activity.status != 'approved'
        )

    @staticmethod
    def parse_date(value):
        try:
            selected = date.fromisoformat(value)
        except (ValueError, TypeError) as error:
            raise ValueError('Choose a valid activity date.') from error
        if not 1900 <= selected.year <= 2100:
            raise ValueError('Choose activity dates between 1900 and 2100.')
        return selected

    @staticmethod
    def get(activity_id):
        CalendarService.require_access()
        return family_get_or_404(Activity, activity_id)

    @staticmethod
    def _values(data):
        values = CalendarService._content(data)
        comments = (data.get('comments') or '').strip()
        if len(comments) > 5000:
            raise ValueError('Use up to 5,000 characters for activity comments.')
        recurrence = data.get('recurrence') or 'none'
        if recurrence not in ('none', 'weekly'):
            raise ValueError('Choose no repeat or weekly recurrence.')
        repeat_until = ActivityService.parse_date(data.get('repeat_until')) if recurrence == 'weekly' else None
        if repeat_until and repeat_until < values['starts_on']:
            raise ValueError('The repeat end date must not be before the activity starts.')
        values.update(comments=comments, recurrence=recurrence, repeat_until=repeat_until)
        candidate = Activity(**values)
        # Validate every weekly wall time now, not only when its month is viewed.
        end = repeat_until or values['starts_on']
        ActivityService.occurrences(candidate, values['starts_on'], end)
        return values

    @staticmethod
    def _attendees(data):
        selected = data.get('attendee_ids', [])
        if not isinstance(selected, list):
            raise ValueError('Choose attendees from the household member list.')
        members = {}
        for value in selected:
            try:
                membership = family_get(HouseholdMembership, value)
            except (ValueError, TypeError) as error:
                raise ValueError('Choose active attendees from this household.') from error
            if membership is None or not membership.user.is_active:
                raise ValueError('Choose active attendees from this household.')
            members[membership.id] = membership
        return list(members.values())

    @staticmethod
    def _set_attendees(activity, members):
        selected = {member.id for member in members}
        activity.attendees[:] = [row for row in activity.attendees if row.membership_id in selected]
        existing = {row.membership_id for row in activity.attendees}
        for member in members:
            if member.id not in existing:
                activity.attendees.append(ActivityAttendee(
                    family_id=activity.family_id, membership_id=member.id,
                ))

    @staticmethod
    def create(data):
        membership = CalendarService.require_access()
        values = ActivityService._values(data)
        members = ActivityService._attendees(data)
        adult = not current_user.is_managed_child
        activity = Activity(
            family_id=membership.family_id, creator_membership_id=membership.id,
            status='approved' if adult else 'pending',
            reviewer_membership_id=membership.id if adult else None,
            reviewed_at=datetime.now(timezone.utc).replace(tzinfo=None) if adult else None,
            **values,
        )
        ActivityService._set_attendees(activity, members)
        db.session.add(activity)
        db.session.commit()
        return activity

    @staticmethod
    def update(activity_id, data):
        activity = ActivityService.get(activity_id)
        if not ActivityService.can_edit(activity):
            abort(403)
        values = ActivityService._values(data)
        members = ActivityService._attendees(data)
        for key, value in values.items():
            setattr(activity, key, value)
        ActivityService._set_attendees(activity, members)
        if current_user.is_managed_child:
            activity.status = 'pending'
            activity.reviewer_membership_id = None
            activity.reviewed_at = None
        db.session.commit()
        return activity

    @staticmethod
    def review(activity_id, data):
        ActivityService.require_manage()
        activity = ActivityService.get(activity_id)
        decision = data.get('decision')
        if decision not in ('approve', 'reject'):
            raise ValueError('Choose approve or reject.')
        if activity.status != 'pending':
            raise ValueError('Only pending suggestions can be reviewed.')
        activity.status = 'approved' if decision == 'approve' else 'rejected'
        activity.reviewer_membership_id = CalendarService.require_access().id
        activity.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.commit()
        return activity

    @staticmethod
    def delete(activity_id):
        activity = ActivityService.get(activity_id)
        if not ActivityService.can_edit(activity):
            abort(403)
        db.session.delete(activity)
        db.session.commit()
        return activity.starts_on

    @staticmethod
    def occurrences(activity, first, last):
        duration = activity.ends_on - activity.starts_on
        end = activity.repeat_until if activity.recurrence == 'weekly' else activity.starts_on
        index = max(0, (first - duration - activity.starts_on).days // 7) if activity.recurrence == 'weekly' else 0
        selected = activity.starts_on + timedelta(weeks=index)
        result = []
        while selected <= min(end, last):
            finish = selected + duration
            if finish.year > 2100:
                raise ValueError('A recurring activity must finish by the end of 2100.')
            starts_at = ends_at = None
            if not activity.all_day:
                offset = selected - activity.starts_on
                local_start = CalendarService.local_time(activity.starts_at).replace(tzinfo=None) + offset
                local_end = CalendarService.local_time(activity.ends_at).replace(tzinfo=None) + offset
                try:
                    starts_at = CalendarService._local_datetime(local_start.strftime('%Y-%m-%dT%H:%M'), 'start')
                    ends_at = CalendarService._local_datetime(local_end.strftime('%Y-%m-%dT%H:%M'), 'end')
                except ValueError as error:
                    raise ValueError(f'Activity on {selected.isoformat()}: {error}') from error
                if ends_at <= starts_at:
                    raise ValueError(f'Activity on {selected.isoformat()} must end after it starts.')
                finish = CalendarService.local_time(ends_at - timedelta(microseconds=1)).date()
                if CalendarService.local_time(ends_at).year > 2100:
                    raise ValueError('A recurring activity must finish by the end of 2100.')
            if finish >= first:
                result.append(ActivityOccurrence(activity, selected, finish, starts_at, ends_at))
            if activity.recurrence == 'none':
                break
            selected += timedelta(weeks=1)
        return result

    @staticmethod
    def between(first, last):
        CalendarService.require_access()
        activities = family_query(Activity).filter(
            Activity.status == 'approved', Activity.starts_on <= last,
        ).options(
            selectinload(Activity.attendees).joinedload(ActivityAttendee.membership),
        ).all()
        occurrences = [
            occurrence for activity in activities
            for occurrence in ActivityService.occurrences(activity, first, last)
        ]
        return sorted(occurrences, key=lambda row: (
            row.starts_on, row.starts_at or datetime.min, row.activity.id,
        ))

    @staticmethod
    def planner(data):
        CalendarService.require_access()
        context = planner_period(data, ActivityService.parse_date)
        occurrences = ActivityService.between(context['first'], context['last'])
        context.update(
            activity_days={
                day: [row for row in occurrences if row.starts_on <= day <= row.ends_on]
                for day in context['days']
            },
            suggestions=family_query(Activity).filter(Activity.status != 'approved')
            .options(joinedload(Activity.creator_membership)).order_by(Activity.starts_on, Activity.id).all(),
            can_manage=not current_user.is_managed_child,
            activity=None, submitted={}, members=CalendarService.members(),
            calendar_service=CalendarService,
        )
        return context

    @staticmethod
    def form_data(activity=None, data=None):
        CalendarService.require_access()
        data = data if data is not None else {}
        selected = ActivityService.parse_date(
            data.get('date') or (activity.starts_on.isoformat() if activity else datetime.now(LONDON).date().isoformat()),
        )
        return dict(
            activity=activity, members=CalendarService.members(),
            selected=selected, view=planner_view(data),
            can_manage=not current_user.is_managed_child,
            can_edit=activity is None or ActivityService.can_edit(activity),
            calendar_service=CalendarService,
        )

    @staticmethod
    def detach_membership(membership):
        family_query(ActivityAttendee, include_private=True).filter_by(
            membership_id=membership.id,
        ).delete(synchronize_session=False)
        for key in ('creator_membership_id', 'reviewer_membership_id'):
            family_query(Activity, include_private=True).filter(
                getattr(Activity, key) == membership.id,
            ).update({key: None}, synchronize_session=False)
