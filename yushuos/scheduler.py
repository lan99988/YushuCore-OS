"""Explicit-timezone trigger arithmetic; execution remains in CoreRuntime."""

from datetime import datetime, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def utc(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
        if not isinstance(result, datetime) or result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('A timezone-aware timestamp is required') from None


def stamp(value):
    return utc(value).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def next_due(trigger, after):
    """Return the next real instant, with DST gaps skipped and fold=0 only."""
    after = utc(after)
    kind = trigger.get('type')
    if kind == 'interval':
        seconds = trigger.get('seconds')
        if type(seconds) is not int or seconds < 1:
            raise ValueError('Interval seconds must be a positive integer')
        anchor = utc(trigger['anchor'])
        index = max(1, int((after - anchor).total_seconds() // seconds) + 1)
        return stamp(anchor + timedelta(seconds=index * seconds))
    if kind != 'cron':
        return None
    expression = trigger.get('expression', '')
    if (not isinstance(expression, str) or len(expression.split()) != 5
            or not re.fullmatch(r'[0-9A-Za-z*,/\- ]{1,200}', expression)):
        raise ValueError('Only traditional five-field cron is supported')
    for position,field in enumerate(expression.upper().split()):
        names=('JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC') if position==3 else (
            ('SUN','MON','TUE','WED','THU','FRI','SAT') if position==4 else ())
        for name in names:
            field=field.replace(name,'1')
        if not re.fullmatch(r'[0-9*,/\-]+',field):
            raise ValueError('Only traditional five-field cron is supported')
    try:
        from croniter import croniter
    except ImportError:
        raise ValueError('Install yushuos-core[automation] for time triggers') from None
    try:
        zone = ZoneInfo(trigger['timezone'])
        local = after.astimezone(zone).replace(tzinfo=None)
        iterator = croniter(expression, local, day_or=True, max_years_between_matches=5)
        for _ in range(1024):
            wall = iterator.get_next(datetime)
            instant = wall.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
            if instant <= after:
                continue
            if instant.astimezone(zone).replace(tzinfo=None) != wall:
                continue
            return stamp(instant)
    except (ValueError, KeyError, ZoneInfoNotFoundError, OverflowError):
        raise ValueError('Invalid or unreachable cron schedule') from None
    raise ValueError('Cron schedule exceeded search budget')


def occurrence_key(trigger, scheduled_at=None, *, event_id=None, invocation_id=None):
    if trigger['type'] == 'event':
        return 'event:' + event_id
    if trigger['type'] == 'manual':
        return 'manual:' + invocation_id
    if trigger['type'] == 'interval':
        index = int((utc(scheduled_at) - utc(trigger['anchor'])).total_seconds() // trigger['seconds'])
        return 'interval:' + stamp(trigger['anchor']) + ':' + str(index)
    return 'cron:' + stamp(scheduled_at)
