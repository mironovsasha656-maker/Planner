"""Moscow time helpers. All dates and times in the app are Moscow time (UTC+3, no DST since 2014).

A fixed offset is used instead of zoneinfo so the app works on Windows without the tzdata package.
Datetimes are stored naive (implicitly Moscow time) in SQLite.
"""
from datetime import date, datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3), "MSK")


def now() -> datetime:
    return datetime.now(MSK).replace(tzinfo=None, microsecond=0)


def today() -> date:
    return now().date()
