"""UTC compatible con las columnas DateTime actuales, sin migraciones."""
from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def iso_utc(value):
    return as_utc_naive(value).isoformat() + "Z" if value is not None else None
