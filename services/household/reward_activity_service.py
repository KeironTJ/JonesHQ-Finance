from datetime import date, datetime, timedelta

from flask import abort
from flask_login import current_user

from models.rewards import Reward, RewardAchievementUnlock, RewardJob, RewardPointEntry, RewardRequest
from services.household.calendar_service import CalendarService, LONDON
from utils.db_helpers import family_query


ACTIVITY_TYPES = {
    'chores': 'Chores', 'rewards': 'Rewards', 'bonuses': 'Bonuses', 'deductions': 'Deductions',
    'achievements': 'Achievements',
}
PAGE_SIZE = 50
_LEDGER = {
    'earned': ('chores', 'check2-circle', 'Chore approved'),
    'reserved': ('rewards', 'gift', 'Asked for a reward'),
    'returned': ('rewards', 'arrow-counterclockwise', 'Points returned'),
    'bonus': ('bonuses', 'award', 'Bonus'),
    'deduction': ('deductions', 'dash-circle', 'Deduction'),
    'milestone': ('achievements', 'trophy', 'Achievement bonus'),
}


def _parse_day(value, label):
    if value in ('', None):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f'Choose a valid {label} date.') from error


class RewardActivityService:
    @staticmethod
    def events():
        """Every reward event the current user can see, newest first, with running balances."""
        from services.household.reward_service import RECOGNITION_CATEGORIES, local_date
        events = []
        running = {}
        ledger_unlocks = set()
        for entry in family_query(RewardPointEntry).order_by(RewardPointEntry.created_at, RewardPointEntry.id).all():
            kind, icon, label = _LEDGER[entry.kind]
            balance = None
            if entry.membership_id:
                running[entry.membership_id] = running.get(entry.membership_id, 0) + entry.points
                balance = running[entry.membership_id]
            if entry.unlock_id:
                ledger_unlocks.add(entry.unlock_id)
            detail = RECOGNITION_CATEGORIES.get(entry.category, '') if entry.category else ''
            if entry.actor and entry.actor_membership_id != entry.membership_id:
                detail = f'{detail} · by {entry.actor.user.name}' if detail else f'By {entry.actor.user.name}'
            events.append(dict(
                at=entry.created_at, type=kind, icon=icon, label=label, title=entry.description,
                member_id=entry.membership_id, member=entry.member, points=entry.points, balance=balance,
                detail=detail, order=(entry.created_at, 1, entry.id),
            ))
        for job in family_query(RewardJob).filter(RewardJob.state.in_(('submitted', 'closed'))).all():
            if job.state == 'submitted' and job.submitted_at:
                events.append(dict(
                    at=job.submitted_at, type='chores', icon='hourglass-split', label='Done, waiting for approval',
                    title=job.title, member_id=job.membership_id, member=job.member, points=None, balance=None,
                    detail=f'{job.points} points after approval', order=(job.submitted_at, 0, job.id),
                ))
            elif job.state == 'closed' and job.reviewed_at:
                events.append(dict(
                    at=job.reviewed_at, type='chores', icon='x-circle', label='Closed without points',
                    title=job.title, member_id=job.membership_id, member=job.member, points=None, balance=None,
                    detail=job.review_note, order=(job.reviewed_at, 0, job.id),
                ))
        for item in family_query(RewardRequest).filter_by(state='approved').all():
            if item.reviewed_at:
                events.append(dict(
                    at=item.reviewed_at, type='rewards', icon='check2-all', label='Reward approved',
                    title=item.title, member_id=item.membership_id, member=item.member, points=None, balance=None,
                    detail=item.review_note, order=(item.reviewed_at, 2, item.id),
                ))
            if item.fulfilled_at:
                events.append(dict(
                    at=item.fulfilled_at, type='rewards', icon='bag-check', label='Reward given',
                    title=item.title, member_id=item.membership_id, member=item.member, points=None, balance=None,
                    detail='', order=(item.fulfilled_at, 3, item.id),
                ))
        for unlock in family_query(RewardAchievementUnlock).all():
            if unlock.id not in ledger_unlocks:
                events.append(dict(
                    at=unlock.unlocked_at, type='achievements', icon=unlock.icon, label='Achievement unlocked',
                    title=unlock.title, member_id=unlock.membership_id, member=unlock.member, points=None,
                    balance=None, detail='', order=(unlock.unlocked_at, 4, unlock.id),
                ))
        for event in events:
            event['day'] = local_date(event['at'])
        events.sort(key=lambda event: event['order'], reverse=True)
        return events

    @staticmethod
    def timeline(member_id=None, kind=None, start=None, end=None, limit=None):
        events = RewardActivityService.events()
        if member_id is not None:
            events = [event for event in events if event['member_id'] == member_id]
        if kind:
            events = [event for event in events if event['type'] == kind]
        if start:
            events = [event for event in events if event['day'] >= start]
        if end:
            events = [event for event in events if event['day'] <= end]
        return events[:limit] if limit else events

    @staticmethod
    def page_data(args):
        from services.household.reward_service import RewardService
        membership = CalendarService.require_access()
        RewardService.refresh()
        context = RewardService.common(membership)
        people = RewardService.participants() if context['is_adult'] else []
        member_id = None
        if not context['is_adult']:
            member_id = membership.id
        elif args.get('member'):
            try:
                member_id = int(args.get('member'))
            except (TypeError, ValueError) as error:
                raise ValueError('Choose someone from the list.') from error
        kind = args.get('type') or None
        if kind and kind not in ACTIVITY_TYPES:
            raise ValueError('Choose an activity type from the list.')
        start, end = _parse_day(args.get('from'), 'start'), _parse_day(args.get('to'), 'end')
        if start and end and start > end:
            raise ValueError('Choose a start date on or before the end date.')
        try:
            page = max(int(args.get('page') or 1), 1)
        except (TypeError, ValueError):
            page = 1
        events = RewardActivityService.timeline(member_id, kind, start, end)
        points = [event['points'] for event in events if event['points']]
        pages = max((len(events) + PAGE_SIZE - 1) // PAGE_SIZE, 1)
        page = min(page, pages)
        context.update(
            people=people, filters=dict(member=member_id, type=kind, start=start, end=end),
            activity_types=ACTIVITY_TYPES, events=events[(page - 1) * PAGE_SIZE:page * PAGE_SIZE],
            total=len(events), page=page, pages=pages,
            totals=dict(gained=sum(p for p in points if p > 0), spent=-sum(p for p in points if p < 0)),
            chart=RewardActivityService.chart([member_id] if member_id else None),
        )
        context['totals']['net'] = context['totals']['gained'] - context['totals']['spent']
        return context

    @staticmethod
    def chart(member_ids=None, weeks=12):
        """Weekly points earned (chores, bonuses, achievements) against points spent or deducted."""
        from services.household.reward_service import local_date
        today = datetime.now(LONDON).date()
        first = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks - 1)
        starts = [first + timedelta(weeks=index) for index in range(weeks)]
        earned, spent = [0] * weeks, [0] * weeks
        declined = {
            row.id for row in family_query(RewardRequest).filter_by(state='declined').all()
        }
        query = family_query(RewardPointEntry)
        if member_ids:
            query = query.filter(RewardPointEntry.membership_id.in_(member_ids))
        for entry in query.all():
            index = (local_date(entry.created_at) - first).days // 7
            if not 0 <= index < weeks:
                continue
            if entry.kind in ('earned', 'bonus', 'milestone'):
                earned[index] += entry.points
            elif entry.kind == 'deduction' or entry.kind == 'reserved' and entry.request_id not in declined:
                spent[index] -= entry.points
        return dict(labels=[day.strftime('%d %b') for day in starts], earned=earned, spent=spent)

    @staticmethod
    def member_summary(member, recent=10):
        from services.household.reward_achievement_service import RewardAchievementService
        from services.household.reward_service import RewardService, utc_start
        today = datetime.now(LONDON).date()
        week, month = utc_start(today - timedelta(days=today.weekday())), utc_start(today.replace(day=1))
        entries = family_query(RewardPointEntry).filter_by(membership_id=member.id).all()
        gains = [row for row in entries if row.kind in ('earned', 'bonus', 'milestone')]
        jobs = family_query(RewardJob).filter(
            RewardJob.membership_id == member.id, RewardJob.state.in_(('open', 'submitted')),
            RewardJob.task_id.isnot(None),
        ).all()
        requests = family_query(RewardRequest).filter(
            RewardRequest.membership_id == member.id,
            RewardRequest.state.in_(('pending', 'approved')),
        ).all()
        values = RewardAchievementService.metrics([member.id])[member.id]
        balance = sum(row.points for row in entries)
        goals = RewardService.goals(member.id)
        achievements = RewardAchievementService.for_member(member.id, values) if recent else []
        return dict(
            member=member, name=member.user.name, balance=balance,
            held=sum(row.points_cost for row in requests if row.state == 'pending'),
            week=sum(row.points for row in gains if row.created_at >= week),
            month=sum(row.points for row in gains if row.created_at >= month),
            lifetime=sum(row.points for row in gains), chores=values['chores'],
            bonuses=values['recognition'], streak=values['current_streak'], best_streak=values['streak'],
            open_chores=sum(1 for job in jobs if job.state == 'open'),
            waiting_chores=sum(1 for job in jobs if job.state == 'submitted'),
            owed=[row for row in requests if row.state == 'approved' and row.fulfilled_at is None],
            goals=[dict(reward=goal, progress=min(balance, goal.points_cost)) for goal in goals],
            achievements=achievements,
            unlocked=sum(1 for card in achievements if card['unlocked_at']),
            recent=RewardActivityService.timeline(member.id, limit=recent) if recent else [],
        )

    @staticmethod
    def member_data(membership_id):
        from services.household.reward_service import RewardService
        membership = CalendarService.require_access()
        if current_user.is_managed_child and membership_id != membership.id:
            abort(403)
        RewardService.refresh()
        member = RewardService._member(membership_id)
        if not RewardService.is_participant(member):
            abort(404)
        context = RewardService.common(membership)
        context.update(
            profile=RewardActivityService.member_summary(member),
            chart=RewardActivityService.chart([member.id]),
            people=RewardService.participants() if context['is_adult'] else [],
            rewards=family_query(Reward).filter_by(available=True).order_by(Reward.points_cost).all()
            if context['is_adult'] else [],
        )
        return context
