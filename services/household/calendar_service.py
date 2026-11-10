import calendar
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import abort
from flask_login import current_user
from sqlalchemy import select, update

from extensions import db
from models.calendar_event import CalendarEvent
from models.family import HouseholdMembership
from models.users import User
from services.household.membership_service import HouseholdMembershipService
from services.platform.module_access_service import ModuleAccessService
from utils.db_helpers import family_get_or_404, family_query


LONDON = ZoneInfo('Europe/London')
POLICIES = {'creator': 'Creator only', 'selected': 'Selected members', 'household': 'All household members'}


class CalendarService:
    @staticmethod
    def require_access():
        if not ModuleAccessService.can_access(current_user, 'household'):
            abort(403)
        return HouseholdMembershipService.get_membership(current_user)

    @staticmethod
    def members():
        return family_query(HouseholdMembership).join(User).filter(
            User.is_active.is_(True),
        ).order_by(User.name).all()

    @staticmethod
    def can_manage(event):
        membership = HouseholdMembershipService.get_membership(current_user)
        return bool(
            membership and membership.family_id == event.family_id
            and (
                membership.id == event.creator_membership_id
                or event.visibility == 'shared' and current_user.is_household_owner
            )
        )

    @staticmethod
    def can_act(event, action):
        if action not in ('edit', 'delete') or not ModuleAccessService.can_access(current_user, 'household'):
            return False
        membership = HouseholdMembershipService.get_membership(current_user)
        if membership.family_id != event.family_id:
            return False
        creator = event.creator_membership.user if event.creator_membership else None
        visible = (
            event.visibility == 'shared'
            or creator is not None and (
                creator.id == current_user.id
                or creator.is_managed_child and creator.guardian_id == current_user.id
            )
        )
        if not visible:
            return False
        if CalendarService.can_manage(event):
            return True
        policy = getattr(event, f'{action}_policy')
        return (
            policy == 'household'
            or policy == 'selected' and membership.id in getattr(event, f'{action}_members')
        )

    @staticmethod
    def get(event_id):
        CalendarService.require_access()
        return family_get_or_404(CalendarEvent, event_id)

    @staticmethod
    def _local_datetime(value, label):
        try:
            local = datetime.strptime(value, '%Y-%m-%dT%H:%M')
        except (ValueError, TypeError) as error:
            raise ValueError(f'Enter a valid {label} date and time.') from error
        candidates = {
            local.replace(tzinfo=LONDON, fold=fold).astimezone(timezone.utc)
            for fold in (0, 1)
            if local.replace(tzinfo=LONDON, fold=fold).astimezone(timezone.utc)
            .astimezone(LONDON).replace(tzinfo=None) == local
        }
        if not candidates:
            raise ValueError(f'The {label} time does not exist when London clocks go forward. Choose another time.')
        if len(candidates) != 1:
            raise ValueError(f'The {label} time occurs twice when London clocks go back. Choose an unambiguous time.')
        return candidates.pop().replace(tzinfo=None)

    @staticmethod
    def _content(data):
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        location = (data.get('location') or '').strip()
        if not title or len(title) > 200:
            raise ValueError('Enter an event title of up to 200 characters.')
        if len(description) > 5000 or len(location) > 200:
            raise ValueError('Use up to 5,000 characters for notes and 200 for the location.')
        all_day = data.get('all_day') == 'on'
        if all_day:
            try:
                starts_on = date.fromisoformat(data.get('starts_on') or '')
                ends_on = date.fromisoformat(data.get('ends_on') or '')
            except (TypeError, ValueError) as error:
                raise ValueError('Enter valid start and end dates.') from error
            starts_at = ends_at = None
            if ends_on < starts_on:
                raise ValueError('The end date must not be before the start date.')
        else:
            starts_at = CalendarService._local_datetime(data.get('starts_at'), 'start')
            ends_at = CalendarService._local_datetime(data.get('ends_at'), 'end')
            if ends_at <= starts_at:
                raise ValueError('The end time must be after the start time.')
            starts_on = CalendarService.local_time(starts_at).date()
            ends_on = CalendarService.local_time(ends_at - timedelta(microseconds=1)).date()
        if not (1900 <= starts_on.year <= 2100 and 1900 <= ends_on.year <= 2100):
            raise ValueError('Choose event dates between 1900 and 2100.')
        return dict(
            title=title, description=description, location=location, all_day=all_day,
            starts_on=starts_on, ends_on=ends_on, starts_at=starts_at, ends_at=ends_at,
        )

    @staticmethod
    def _permissions(data, event=None):
        visibility = data.get('visibility') or 'shared'
        if visibility not in ('shared', 'private'):
            raise ValueError('Choose shared or private visibility.')
        creator = event.creator_membership.user if event and event.creator_membership else current_user
        members = CalendarService.members()
        eligible = {member.id for member in members}
        if visibility == 'private':
            eligible = {
                member.id for member in members
                if member.user_id == creator.id
                or creator.is_managed_child and member.user_id == creator.guardian_id
            }
        values = {'visibility': visibility}
        for action in ('edit', 'delete'):
            policy = data.get(f'{action}_policy') or 'creator'
            if policy not in POLICIES:
                raise ValueError('Choose a supported permission policy.')
            if visibility == 'private' and policy == 'household':
                raise ValueError('Private events cannot grant permission to the whole household.')
            selected = data.get(f'{action}_members', [])
            if not isinstance(selected, list):
                raise ValueError('Choose household members from the list.')
            try:
                ids = sorted({int(value) for value in selected}) if policy == 'selected' else []
            except (ValueError, TypeError) as error:
                raise ValueError('Choose household members from the list.') from error
            if policy == 'selected' and (not ids or not set(ids) <= eligible):
                raise ValueError('Select active household members who can see this event.')
            values[f'{action}_policy'] = policy
            values[f'{action}_members'] = ids
        if event and event.creator_membership_id is None and visibility == 'private':
            raise ValueError('An event without its creator must remain shared.')
        return values

    @staticmethod
    def create(data):
        membership = CalendarService.require_access()
        values = CalendarService._content(data)
        values.update(CalendarService._permissions(data))
        event = CalendarEvent(
            family_id=membership.family_id, creator_membership_id=membership.id, **values,
        )
        db.session.add(event)
        db.session.commit()
        return event

    @staticmethod
    def update(event_id, data):
        event = CalendarService.get(event_id)
        if not CalendarService.can_act(event, 'edit'):
            abort(403)
        values = CalendarService._content(data)
        if CalendarService.can_manage(event):
            values.update(CalendarService._permissions(data, event))
        elif any(key in data for key in ('visibility', 'edit_policy', 'delete_policy', 'edit_members', 'delete_members')):
            raise ValueError('Only the creator or an owner of a shared event can change permissions.')
        for key, value in values.items():
            setattr(event, key, value)
        db.session.commit()
        return event

    @staticmethod
    def delete(event_id):
        event = CalendarService.get(event_id)
        if not CalendarService.can_act(event, 'delete'):
            abort(403)
        db.session.delete(event)
        db.session.commit()

    @staticmethod
    def detach_membership(membership):
        events = family_query(CalendarEvent, include_private=True).filter_by(
            creator_membership_id=membership.id,
        )
        events.filter_by(visibility='private').delete(synchronize_session=False)
        events.filter_by(visibility='shared').update(
            {'creator_membership_id': None}, synchronize_session=False,
        )
        CalendarService.remove_membership_grants({membership.id: membership.family_id})

    @staticmethod
    def remove_membership_grants(memberships):
        # Deletion can span an account's households; never expose these internal rows.
        table = CalendarEvent.__table__
        for family_id in set(memberships.values()):
            removed = {key for key, value in memberships.items() if value == family_id}
            rows = db.session.execute(select(
                table.c.id, table.c.edit_members, table.c.delete_members,
            ).where(table.c.family_id == family_id)).mappings().all()
            for row in rows:
                values = {
                    key: [member_id for member_id in row[key] if member_id not in removed]
                    for key in ('edit_members', 'delete_members')
                    if any(member_id in removed for member_id in row[key])
                }
                if values:
                    db.session.execute(update(table).where(
                        table.c.id == row['id'], table.c.family_id == family_id,
                    ).values(**values))

    @staticmethod
    def local_time(value):
        return value.replace(tzinfo=timezone.utc).astimezone(LONDON) if value else None

    @staticmethod
    def privacy_label(event):
        creator = event.creator_membership.user if event.creator_membership else None
        if event.visibility == 'shared':
            return 'Shared with household'
        if creator and creator.is_managed_child:
            return 'Private: child and designated guardian'
        return 'Private: creator only'

    @staticmethod
    def _month_data(data):
        CalendarService.require_access()
        today = datetime.now(LONDON).date()
        try:
            selected = date.fromisoformat((data.get('month') or today.strftime('%Y-%m')) + '-01')
        except (TypeError, ValueError) as error:
            raise ValueError('Choose a valid calendar month.') from error
        if not 1900 <= selected.year <= 2100:
            raise ValueError('Choose a month between 1900 and 2100.')
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(selected.year, selected.month)
        return dict(
            month=selected, weeks=weeks, today=today,
            previous=(selected - timedelta(days=1)).strftime('%Y-%m') if selected.year > 1900 or selected.month > 1 else None,
            following=(selected.replace(day=calendar.monthrange(selected.year, selected.month)[1]) + timedelta(days=1)).strftime('%Y-%m')
            if selected.year < 2100 or selected.month < 12 else None,
            calendar_service=CalendarService,
        )

    @staticmethod
    def events_data(data):
        context = CalendarService._month_data(data)
        first = context['month']
        last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
        context['events'] = family_query(CalendarEvent).filter(
            CalendarEvent.starts_on <= last, CalendarEvent.ends_on >= first,
        ).order_by(CalendarEvent.starts_on, CalendarEvent.starts_at, CalendarEvent.title, CalendarEvent.id).all()
        return context

    @staticmethod
    def page_data(data):
        context = CalendarService._month_data(data)
        selected, weeks = context['month'], context['weeks']
        view = data.get('view') or 'month'
        if view not in ('month', 'agenda'):
            raise ValueError('Choose month or agenda view.')
        selected_day = None
        if data.get('day'):
            try:
                selected_day = date.fromisoformat(data.get('day'))
            except (TypeError, ValueError) as error:
                raise ValueError('Choose a valid calendar day.') from error
            if selected_day.replace(day=1) != selected:
                raise ValueError('Choose a day in the selected month.')
        first, last = weeks[0][0], weeks[-1][-1]
        events = family_query(CalendarEvent).filter(
            CalendarEvent.starts_on <= last, CalendarEvent.ends_on >= first,
        ).order_by(CalendarEvent.starts_on, CalendarEvent.starts_at, CalendarEvent.title).all()
        days = {
            day: [event for event in events if event.starts_on <= day <= event.ends_on]
            for week in weeks for day in week
        }
        from services.household.meal_service import MealService, SLOTS
        planned_meals = MealService.plans_between(first, last)
        from services.household.activity_service import ActivityService
        activities = ActivityService.between(first, last)
        from services.household.task_service import TaskService
        tasks = TaskService.between(first, last)
        context.update(
            days=days, view=view, selected_day=selected_day,
            meal_days={
                day: [plan for plan in planned_meals if plan.date == day]
                for week in weeks for day in week
            },
            meal_slots=SLOTS,
            activity_days={
                day: [row for row in activities if row.starts_on <= day <= row.ends_on]
                for week in weeks for day in week
            },
            task_days={
                day: [task for task in tasks if task.due_date == day]
                for week in weeks for day in week
            },
        )
        return context

    @staticmethod
    def form_data(event=None):
        CalendarService.require_access()
        return dict(
            event=event, members=CalendarService.members(), policies=POLICIES,
            calendar_service=CalendarService, today=datetime.now(LONDON).date(),
            can_manage=event is None or CalendarService.can_manage(event),
        )
