"""Calendar pack. Selector-gated."""

from __future__ import annotations

from typing import Any

import mailAndCalendar

NAME = "calendar"
TOOLS = (
    "listCalendars",
    "listCalendarEvents",
    "openCalendarEvent",
    "findFreeBusy",
    "createCalendarEvent",
    "updateCalendarEvent",
    "cancelCalendarEvent",
)


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {name: _wrap(name, aid) for name in TOOLS}


def _wrap(name: str, agent_name: str):
    def call(**kw: Any) -> dict[str, Any]:
        kw.pop("provider", None)
        kw.pop("agent_id", None)
        return getattr(mailAndCalendar, name)("google", agent_id=agent_name, **kw)

    return call
