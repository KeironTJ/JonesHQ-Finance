from datetime import datetime, timedelta

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from extensions import db
from models.family import Family
from models.rewards import RewardAchievement, RewardAchievementUnlock, RewardJob, RewardPointEntry
from services.household.calendar_service import CalendarService, LONDON
from utils.db_helpers import family_get_or_404, family_query


ACHIEVEMENT_ICONS = {
    'star': 'Star', 'hand-thumbs-up': 'Thumbs up', 'people': 'Team', 'trophy': 'Trophy', 'fire': 'Fire',
    'lightning': 'Lightning', 'award': 'Award', 'heart': 'Heart', 'rocket': 'Rocket', 'gem': 'Gem',
    'book': 'Book', 'music-note': 'Music', 'emoji-smile': 'Smile', 'flag': 'Flag',
}
ACHIEVEMENT_METRICS = {
    'chores': 'Approved chores',
    'points': 'Points earned (chores and bonuses)',
    'streak': 'Days in a row with an approved chore',
    'recognition': 'Bonus awards received',
}
DEFAULT_ACHIEVEMENTS = (
    ('First step', 'Your first approved chore', 'star', 'chores', 1),
    ('Helping hand', '5 approved chores', 'hand-thumbs-up', 'chores', 5),
    ('Team player', '10 approved chores', 'people', 'chores', 10),
    ('100-point milestone', '100 points earned in total', 'trophy', 'points', 100),
    ('On a roll', 'Chores done 3 days in a row', 'fire', 'streak', 3),
    ('Week-long streak', 'Chores done 7 days in a row', 'lightning', 'streak', 7),
    ('Proud moment', 'Recognised with a bonus', 'award', 'recognition', 1),
)


def _now():
    from services.household.reward_service import _now as now
    return now()


class RewardAchievementService:
    @staticmethod
    def ensure_defaults(family):
        """Seed starter achievements once per household. Callers hold the reward lock."""
        if family.rewards_defaults_seeded:
            return
        for title, description, icon, metric, threshold in DEFAULT_ACHIEVEMENTS:
            db.session.add(RewardAchievement(
                family_id=family.id, title=title, description=description, icon=icon,
                metric=metric, threshold=threshold, bonus_points=0, active=True,
            ))
        family.rewards_defaults_seeded = True
        db.session.flush()

    @staticmethod
    def all():
        return family_query(RewardAchievement).order_by(
            RewardAchievement.metric, RewardAchievement.threshold, RewardAchievement.id,
        ).all()

    @staticmethod
    def streaks(member_ids):
        """Current and best runs of consecutive London days with an approved chore."""
        from services.household.reward_service import local_date
        if not member_ids:
            return {}
        rows = family_query(RewardPointEntry, include_private=True).outerjoin(
            RewardJob, RewardPointEntry.job_id == RewardJob.id,
        ).filter(
            RewardPointEntry.membership_id.in_(member_ids), RewardPointEntry.kind == 'earned',
        ).with_entities(RewardPointEntry.membership_id, RewardJob.submitted_at, RewardPointEntry.created_at).all()
        days = {member_id: set() for member_id in member_ids}
        for member_id, submitted_at, created_at in rows:
            days[member_id].add(local_date(submitted_at or created_at))
        today = datetime.now(LONDON).date()
        result = {}
        for member_id, dates in days.items():
            best = run = 0
            previous = None
            for day in sorted(dates):
                run = run + 1 if previous and day - previous == timedelta(days=1) else 1
                best = max(best, run)
                previous = day
            current = run if previous and (today - previous).days <= 1 else 0
            result[member_id] = (current, best)
        return result

    @staticmethod
    def metrics(member_ids):
        if not member_ids:
            return {}
        rows = family_query(RewardPointEntry, include_private=True).filter(
            RewardPointEntry.membership_id.in_(member_ids),
            RewardPointEntry.kind.in_(('earned', 'bonus')),
        ).with_entities(
            RewardPointEntry.membership_id, RewardPointEntry.kind,
            db.func.count(RewardPointEntry.id), db.func.sum(RewardPointEntry.points),
        ).group_by(RewardPointEntry.membership_id, RewardPointEntry.kind).all()
        streaks = RewardAchievementService.streaks(member_ids)
        result = {
            member_id: dict(
                chores=0, points=0, recognition=0, streak=streaks[member_id][1],
                current_streak=streaks[member_id][0],
            ) for member_id in member_ids
        }
        for member_id, kind, count, points in rows:
            result[member_id]['points'] += int(points or 0)
            result[member_id]['chores' if kind == 'earned' else 'recognition'] += count
        return result

    @staticmethod
    def _due(member_ids):
        achievements = family_query(RewardAchievement).filter_by(active=True).all()
        if not achievements or not member_ids:
            return []
        values = RewardAchievementService.metrics(member_ids)
        unlocked = {
            (row.achievement_id, row.membership_id)
            for row in family_query(RewardAchievementUnlock, include_private=True).filter(
                RewardAchievementUnlock.membership_id.in_(member_ids),
            ).all()
        }
        return [
            (achievement, member_id)
            for member_id in member_ids for achievement in achievements
            if (achievement.id, member_id) not in unlocked and values[member_id][achievement.metric] >= achievement.threshold
        ]

    @staticmethod
    def evaluate(member_ids):
        """Unlock achievements newly reached by *member_ids*. Callers hold the reward lock and commit."""
        member_ids = [member_id for member_id in member_ids if member_id]
        if not member_ids:
            return []
        membership = CalendarService.require_access()
        RewardAchievementService.ensure_defaults(db.session.get(Family, membership.family_id))
        unlocks = []
        for achievement, member_id in RewardAchievementService._due(member_ids):
            unlock = RewardAchievementUnlock(
                family_id=achievement.family_id, achievement_id=achievement.id, membership_id=member_id,
                title=achievement.title, icon=achievement.icon, unlocked_at=_now(),
            )
            db.session.add(unlock)
            db.session.flush()
            if achievement.bonus_points:
                db.session.add(RewardPointEntry(
                    family_id=achievement.family_id, membership_id=member_id, unlock_id=unlock.id,
                    kind='milestone', points=achievement.bonus_points,
                    description=f'Achievement: {achievement.title}'[:256], created_at=_now(),
                ))
            unlocks.append(unlock)
        return unlocks

    @staticmethod
    def refresh():
        """Seed defaults and catch up unlocks, taking the lock only when something changes."""
        from services.household.reward_service import RewardService
        membership = CalendarService.require_access()
        ids = [member.id for member in RewardService.participants()]
        if membership.family.rewards_defaults_seeded and not RewardAchievementService._due(ids):
            return
        try:
            RewardService._lock()
            RewardAchievementService.ensure_defaults(db.session.get(Family, membership.family_id))
            RewardAchievementService.evaluate(ids)
            db.session.commit()
        except SQLAlchemyError:
            # Housekeeping only: the page still renders and the next visit retries.
            db.session.rollback()
            current_app.logger.exception('Unable to refresh household reward achievements')

    @staticmethod
    def save_achievement(data, achievement_id=None):
        from services.household.reward_service import RewardService
        membership = RewardService.require_adult()
        RewardService._lock()
        achievement = family_get_or_404(RewardAchievement, achievement_id) if achievement_id else RewardAchievement(
            family_id=membership.family_id,
        )
        title = (data.get('title') or '').strip()
        description = (data.get('description') or '').strip()
        if not title or len(title) > 64 or len(description) > 256:
            raise ValueError('Enter an achievement name up to 64 characters and description up to 256 characters.')
        icon = data.get('icon') or 'trophy'
        if icon not in ACHIEVEMENT_ICONS:
            raise ValueError('Choose an achievement icon from the list.')
        metric = data.get('metric')
        if metric not in ACHIEVEMENT_METRICS:
            raise ValueError('Choose what this achievement counts.')
        active = data.get('active', 'yes')
        if active not in ('yes', 'no'):
            raise ValueError('Choose whether this achievement is active.')
        achievement.title = title
        achievement.description = description
        achievement.icon = icon
        achievement.metric = metric
        achievement.threshold = RewardService._integer(data.get('threshold'), 'target', 100000)
        achievement.bonus_points = RewardService._integer(data.get('bonus_points') or 0, 'bonus points', 1000, minimum=0)
        achievement.active = active == 'yes'
        db.session.add(achievement)
        db.session.flush()
        RewardAchievementService.evaluate([member.id for member in RewardService.participants()])
        db.session.commit()
        return achievement

    @staticmethod
    def for_member(member_id, values=None):
        """Every active achievement plus earned ones that were later paused, with progress."""
        values = values or RewardAchievementService.metrics([member_id])[member_id]
        unlocks = {
            row.achievement_id: row for row in family_query(RewardAchievementUnlock).filter_by(
                membership_id=member_id,
            ).all()
        }
        cards = []
        for achievement in RewardAchievementService.all():
            unlock = unlocks.pop(achievement.id, None)
            if not achievement.active and unlock is None:
                continue
            value = values[achievement.metric]
            cards.append(dict(
                title=achievement.title, description=achievement.description, icon=achievement.icon,
                unlocked_at=unlock.unlocked_at if unlock else None, bonus=achievement.bonus_points,
                progress=min(value, achievement.threshold), threshold=achievement.threshold,
            ))
        for unlock in unlocks.values():
            cards.append(dict(
                title=unlock.title, description='', icon=unlock.icon, unlocked_at=unlock.unlocked_at,
                bonus=0, progress=1, threshold=1,
            ))
        cards.sort(key=lambda card: (card['unlocked_at'] is None, -(card['progress'] / card['threshold'])))
        return cards
