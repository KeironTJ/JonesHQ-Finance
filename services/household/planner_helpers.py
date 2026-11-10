import calendar
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def planner_view(data):
    view = data.get('view') or 'week'
    if view not in ('week', 'month'):
        raise ValueError('Choose week or month planner view.')
    return view


def planner_values(selected, view):
    return {'view': view, 'month': selected.strftime('%Y-%m')} if view == 'month' else {'week': selected.isoformat()}


def planner_period(data, parse_date):
    today = datetime.now(ZoneInfo('Europe/London')).date()
    view = planner_view(data)
    if view == 'month':
        selected = parse_date((data.get('month') or today.strftime('%Y-%m')) + '-01')
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(selected.year, selected.month)
        first, last = weeks[0][0], weeks[-1][-1]
        previous = selected - timedelta(days=1) if selected > date(1900, 1, 1) else None
        following = selected.replace(day=calendar.monthrange(selected.year, selected.month)[1]) + timedelta(days=1)
        if following > date(2100, 12, 31):
            following = None
    else:
        selected = parse_date(data.get('week') or today.isoformat())
        first = selected - timedelta(days=selected.weekday())
        last = first + timedelta(days=6)
        weeks = [[first + timedelta(days=index) for index in range(7)]]
        previous = first - timedelta(days=7) if first - timedelta(days=7) >= date(1900, 1, 1) else None
        following = first + timedelta(days=7) if first + timedelta(days=7) <= date(2100, 12, 31) else None
    return dict(
        today=today, view=view, selected=selected, first=first, last=last,
        weeks=weeks, days=[day for week in weeks for day in week],
        previous=previous, following=following,
    )
