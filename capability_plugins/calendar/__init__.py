"""Proposal-only calendar capability adapter."""

from .plugin import (
    CALENDAR_CAPABILITIES,
    CalendarDelegate,
    CalendarPlugin,
    CalendarPluginError,
)

__all__ = [
    "CALENDAR_CAPABILITIES",
    "CalendarDelegate",
    "CalendarPlugin",
    "CalendarPluginError",
]
