"""
Core utility functions.
"""
from datetime import datetime, timezone


def utc_now() -> datetime:
    """
    Return current UTC time as a naive datetime (no timezone info).

    This is required because PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns
    don't accept timezone-aware Python datetimes with asyncpg driver.

    The returned datetime is semantically UTC but without tzinfo attached.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
