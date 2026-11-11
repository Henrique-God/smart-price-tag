"""Shared timezone for dates entered and displayed in the interface."""

from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    BRASILIA = ZoneInfo("America/Sao_Paulo")
except ZoneInfoNotFoundError:  # Windows without the tzdata package
    BRASILIA = timezone(timedelta(hours=-3), "BRT")
