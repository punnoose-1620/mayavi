"""Agent-facing mail/calendar door. Backends are never imported by models."""

from __future__ import annotations

import re
from typing import Any, Callable

import google_backend
import logger
import microsoft as microsoft_backend
import store

READ_TOOLS = {"listMails", "searchMails", "openMail", "listCalendars", "listCalendarEvents", "openCalendarEvent", "findFreeBusy"}
WRITE_TOOLS = {"sendMail", "replyMail", "createCalendarEvent", "updateCalendarEvent", "cancelCalendarEvent"}
SCAN_TOOLS = WRITE_TOOLS
_BACKENDS = {"google": google_backend, "microsoft": microsoft_backend}

_JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
_GOOGLE_TOKEN = re.compile(r"ya29\.[A-Za-z0-9_-]+")
_SECRETISH = re.compile(r"(client_secret|refresh_token|access_token|BEGIN PRIVATE KEY)", re.I)


def listMails(provider: str, time_min: str | None = None, max_n: int = 20, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    return _call("listMails", provider, agent_id, time_min=time_min, max_n=max_n, start=start, end=end)


def searchMails(provider: str, query: str, time_min: str | None = None, max_n: int = 20, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    return _call("searchMails", provider, agent_id, query=query, time_min=time_min, max_n=max_n, start=start, end=end)


def openMail(provider: str, mail_id: str, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    return _call("openMail", provider, agent_id, mail_id=mail_id, start=start, end=end)


def sendMail(provider: str, to: list[str], subject: str, body: str, cc: list[str] | None = None, agent_id: str | None = None) -> dict[str, Any]:
    return _call("sendMail", provider, agent_id, to=to, subject=subject, body=body, cc=cc or [])


def replyMail(provider: str, thread_id: str, body: str, to: list[str] | None = None, subject: str = "", agent_id: str | None = None) -> dict[str, Any]:
    return _call("replyMail", provider, agent_id, thread_id=thread_id, body=body, to=to, subject=subject)


def listCalendars(provider: str, agent_id: str | None = None) -> dict[str, Any]:
    return _call("listCalendars", provider, agent_id)


def listCalendarEvents(provider: str, calendar_id: str, time_min: str | None = None, time_max: str | None = None, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    return _call("listCalendarEvents", provider, agent_id, calendar_id=calendar_id, time_min=time_min, time_max=time_max, start=start, end=end)


def openCalendarEvent(provider: str, calendar_id: str, event_id: str, agent_id: str | None = None) -> dict[str, Any]:
    return _call("openCalendarEvent", provider, agent_id, calendar_id=calendar_id, event_id=event_id)


def createCalendarEvent(
    provider: str,
    calendar_id: str,
    summary: str,
    start: dict[str, Any],
    end: dict[str, Any],
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    return _call(
        "createCalendarEvent",
        provider,
        agent_id,
        calendar_id=calendar_id,
        summary=summary,
        start=start,
        end=end,
        description=description,
        location=location,
        attendees=attendees or [],
    )


def updateCalendarEvent(provider: str, calendar_id: str, event_id: str, patch: dict[str, Any], scope: str = "this", etag: str | None = None, agent_id: str | None = None) -> dict[str, Any]:
    return _call("updateCalendarEvent", provider, agent_id, calendar_id=calendar_id, event_id=event_id, patch=patch, scope=scope, etag=etag)


def cancelCalendarEvent(provider: str, calendar_id: str, event_id: str, scope: str = "this", agent_id: str | None = None) -> dict[str, Any]:
    return _call("cancelCalendarEvent", provider, agent_id, calendar_id=calendar_id, event_id=event_id, scope=scope)


def findFreeBusy(provider: str, time_min: str, time_max: str, attendees: list[str] | None = None, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id, denied = _gate("findFreeBusy", provider if provider != "both" else "google", agent_id)
    if denied:
        return denied
    if provider == "both":
        merged = {"ok": True, "calendars": {}}
        for name in ("google", "microsoft"):
            if name not in (run.oauth if run else {}):
                continue
            part = _invoke(run, name, "findFreeBusy", time_min=time_min, time_max=time_max, items=attendees)
            if part.get("ok"):
                merged["calendars"][name] = part.get("calendars")
        return _finish("findFreeBusy", run, agent_id, merged, provider="both")
    return _call("findFreeBusy", provider, agent_id, time_min=time_min, time_max=time_max, items=attendees)


def _call(tool: str, provider: str, agent_id: str | None, **kwargs: Any) -> dict[str, Any]:
    run, agent_id, denied = _gate(tool, provider, agent_id)
    if denied:
        return denied
    if tool in SCAN_TOOLS and _looks_like_secret(kwargs):
        return _finish(tool, run, agent_id, {"ok": False, "error": "policy_deny"}, provider=provider)
    if tool in WRITE_TOOLS and provider == "both":
        return _finish(tool, run, agent_id, {"ok": False, "error": "both_not_allowed"}, provider=provider)
    if tool in {"sendMail", "replyMail"}:
        to = kwargs.get("to") or []
        cc = kwargs.get("cc") or []
        if len(to) + len(cc) > 10:
            return _finish(tool, run, agent_id, {"ok": False, "error": "recipient_cap"}, provider=provider)
    try:
        if tool in {"createCalendarEvent"} and run is not None:
            kwargs["timezone"] = run.timezone
        result = _invoke(run, provider, tool, **kwargs)
    except Exception as exc:
        result = {"ok": False, "error": type(exc).__name__}
    return _finish(tool, run, agent_id, result, provider=provider, extra=kwargs)


def _gate(tool: str, provider: str, agent_id: str | None) -> tuple[Any, str | None, dict[str, Any] | None]:
    run = store.run_for_agent(agent_id) if agent_id else None
    if run is None or run.mail_cal in {None, "off"}:
        return run, agent_id, _finish(tool, run, agent_id, {"ok": False, "error": "mail_cal_off"}, provider=provider)
    if run.mail_cal == "read" and tool in WRITE_TOOLS:
        return run, agent_id, _finish(tool, run, agent_id, {"ok": False, "error": "read_only"}, provider=provider)
    if not _is_manager(run, agent_id):
        return run, agent_id, _finish(tool, run, agent_id, {"ok": False, "error": "not_manager"}, provider=provider)
    if provider not in {"google", "microsoft", "both"}:
        return run, agent_id, _finish(tool, run, agent_id, {"ok": False, "error": "bad_provider"}, provider=provider)
    if provider != "both" and provider not in run.oauth:
        return run, agent_id, _finish(tool, run, agent_id, {"ok": False, "error": "no_session"}, provider=provider)
    return run, agent_id, None


def _invoke(run: Any, provider: str, tool: str, **kwargs: Any) -> dict[str, Any]:
    backend = _BACKENDS[provider]
    handle = run.oauth[provider]
    fn: Callable[..., dict[str, Any]] = getattr(backend, tool)
    return fn(handle, **kwargs)


def _is_manager(run: Any, agent_id: str | None) -> bool:
    if not agent_id or agent_id not in run.agents:
        return False
    role = run.agents[agent_id].role
    if run.level == "large":
        return role == "executor"
    return role == "drafter"


def _looks_like_secret(kwargs: dict[str, Any]) -> bool:
    blob = " ".join(_flatten(kwargs))
    if _JWT.search(blob) or _GOOGLE_TOKEN.search(blob) or _SECRETISH.search(blob):
        return True
    return False


def _flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_flatten(item))
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for item in value:
            out.extend(_flatten(item))
        return out
    return [str(value)]


def _finish(tool: str, run: Any, agent_id: str | None, result: dict[str, Any], *, provider: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = extra or {}
    bits = [f"provider={provider}", f"tool={tool}"]
    if extra.get("subject"):
        bits.append(f"subject={extra['subject']}")
    if result.get("id"):
        bits.append(f"id={result['id']}")
    if extra.get("event_id"):
        bits.append(f"event_id={extra['event_id']}")
    return logger.finish(
        event="tool",
        tool=tool,
        run_id=None if run is None else run.run_id,
        agent_name=agent_id or "script",
        result=result,
        level=None if run is None else run.level,
        stakes=None if run is None else run.stakes,
        mail_cal=None if run is None else run.mail_cal,
        summary=" ".join(bits),
    )
