"""Private Microsoft Graph mail + calendar backend. Not in the agent schema."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

import config
import logger

try:
    import msal

    HAS_MSAL = True
except ImportError:
    msal = None  # type: ignore
    HAS_MSAL = False

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read", "Mail.Send", "Calendars.ReadWrite", "User.Read"]


def connectToMicrosoft(open_browser: bool = True) -> dict[str, Any]:
    if not HAS_MSAL:
        return _log_connect({"ok": False, "error": "msal_missing"})
    if not config.MS_CLIENT_ID:
        return _log_connect({"ok": False, "error": "not_configured"})
    cache_path = config.TOKEN_DIR / "token_ms.json"
    cache = msal.SerializableTokenCache()
    if cache_path.is_file():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        config.MS_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{config.MS_TENANT}",
        token_cache=cache,
    )
    result = None
    accounts = app.get_accounts(username=config.MS_LOGIN_HINT)
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result:
        if not open_browser:
            return _log_connect({"ok": False, "error": "browser_required"})
        try:
            result = app.acquire_token_interactive(SCOPES, login_hint=config.MS_LOGIN_HINT)
        except Exception as exc:
            return _log_connect({"ok": False, "error": type(exc).__name__})
    if not result or "access_token" not in result:
        return _log_connect({"ok": False, "error": "cancelled"})
    cache_path.write_text(cache.serialize(), encoding="utf-8")
    email = _me_email(result["access_token"])
    if config.MS_LOGIN_HINT and email and email.lower() != config.MS_LOGIN_HINT.lower():
        return _log_connect({"ok": False, "error": "wrong_account"})
    handle = {"provider": "microsoft", "token_path": str(cache_path), "email": email, "client_id": config.MS_CLIENT_ID}
    return _log_connect({"ok": True, "handle": handle, "email": email, "provider": "microsoft"})


def listMails(handle: dict[str, Any], time_min: str | None = None, max_n: int = 20, start: int = 1, end: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {"$top": min(max_n, 50), "$select": "id,subject,from,receivedDateTime"}
    if time_min:
        params["$filter"] = f"receivedDateTime ge {time_min}"
    data = _graph(handle, "GET", "/me/messages", params=params)
    return {"ok": True, "items": data.get("value") or [], "start": start, "end": end, "total_pages": 1}


def searchMails(handle: dict[str, Any], query: str, time_min: str | None = None, max_n: int = 20, start: int = 1, end: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {"$top": min(max_n, 50), "$search": json.dumps(query)}
    data = _graph(handle, "GET", "/me/messages", params=params)
    return {"ok": True, "items": data.get("value") or [], "start": start, "end": end, "total_pages": 1}


def openMail(handle: dict[str, Any], mail_id: str, start: int = 1, end: int = 1) -> dict[str, Any]:
    import paging

    data = _graph(handle, "GET", f"/me/messages/{mail_id}", params={"$select": "id,subject,body,from"})
    text = ((data.get("body") or {}).get("content")) or ""
    chunk, s, e, total = paging.slice_chars(text, start, end)
    return {"ok": True, "text": chunk, "start": s, "end": e, "total_pages": total, "id": mail_id}


def sendMail(handle: dict[str, Any], to: list[str], subject: str, body: str, cc: list[str] | None = None) -> dict[str, Any]:
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
            "ccRecipients": [{"emailAddress": {"address": a}} for a in (cc or [])],
        }
    }
    _graph(handle, "POST", "/me/sendMail", json_body=payload)
    return {"ok": True, "id": "sent"}


def replyMail(handle: dict[str, Any], thread_id: str, body: str, to: list[str] | None = None, subject: str = "") -> dict[str, Any]:
    _graph(handle, "POST", f"/me/messages/{thread_id}/reply", json_body={"comment": body})
    return {"ok": True, "id": thread_id}


def listCalendars(handle: dict[str, Any]) -> dict[str, Any]:
    data = _graph(handle, "GET", "/me/calendars")
    items = [{"id": c.get("id"), "summary": c.get("name")} for c in data.get("value") or []]
    return {"ok": True, "items": items}


def listCalendarEvents(handle: dict[str, Any], calendar_id: str, time_min: str | None = None, time_max: str | None = None, start: int = 1, end: int = 1) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if time_min:
        params["startDateTime"] = time_min
    if time_max:
        params["endDateTime"] = time_max
    data = _graph(handle, "GET", f"/me/calendars/{calendar_id}/calendarView", params=params or None)
    return {"ok": True, "items": data.get("value") or [], "start": start, "end": end, "total_pages": 1}


def openCalendarEvent(handle: dict[str, Any], calendar_id: str, event_id: str) -> dict[str, Any]:
    event = _graph(handle, "GET", f"/me/events/{event_id}")
    return {"ok": True, "event": {"id": event.get("id"), "summary": event.get("subject"), "start": event.get("start"), "end": event.get("end")}}


def createCalendarEvent(handle: dict[str, Any], calendar_id: str, summary: str, start: dict[str, Any], end: dict[str, Any], timezone: str, description: str = "", location: str = "", attendees: list[str] | None = None) -> dict[str, Any]:
    body = {
        "subject": summary,
        "body": {"contentType": "Text", "content": description},
        "start": {"dateTime": start.get("dateTime") or start.get("date"), "timeZone": timezone},
        "end": {"dateTime": end.get("dateTime") or end.get("date"), "timeZone": timezone},
        "location": {"displayName": location},
        "attendees": [{"emailAddress": {"address": a}, "type": "required"} for a in (attendees or [])],
    }
    event = _graph(handle, "POST", f"/me/calendars/{calendar_id}/events", json_body=body)
    return {"ok": True, "id": event.get("id")}


def updateCalendarEvent(handle: dict[str, Any], calendar_id: str, event_id: str, patch: dict[str, Any], scope: str = "this", etag: str | None = None) -> dict[str, Any]:
    headers = {}
    if etag:
        headers["If-Match"] = etag
    event = _graph(handle, "PATCH", f"/me/events/{event_id}", json_body=patch, headers=headers)
    return {"ok": True, "id": event.get("id")}


def cancelCalendarEvent(handle: dict[str, Any], calendar_id: str, event_id: str, scope: str = "this") -> dict[str, Any]:
    _graph(handle, "POST", f"/me/events/{event_id}/cancel", json_body={"comment": "cancelled"})
    return {"ok": True, "id": event_id}


def findFreeBusy(handle: dict[str, Any], time_min: str, time_max: str, items: list[str] | None = None) -> dict[str, Any]:
    body = {
        "schedules": items or [],
        "startTime": {"dateTime": time_min, "timeZone": "UTC"},
        "endTime": {"dateTime": time_max, "timeZone": "UTC"},
        "availabilityViewInterval": 30,
    }
    data = _graph(handle, "POST", "/me/calendar/getSchedule", json_body=body)
    return {"ok": True, "calendars": data.get("value") or []}


def _log_connect(result: dict[str, Any]) -> dict[str, Any]:
    logged = logger.finish(
        event="factory",
        tool="connectToMicrosoft",
        run_id=_run_id(),
        agent_name=_agent(),
        result={"ok": result.get("ok"), "error": result.get("error"), "email": result.get("email"), "provider": "microsoft"}
        if result.get("ok")
        else result,
        summary="provider=microsoft",
    )
    if result.get("handle"):
        logged["handle"] = result["handle"]
    return logged


def _run_id() -> str | None:
    import store

    for run in store._RUNS.values():  # noqa: SLF001
        return run.run_id
    return None


def _agent() -> str:
    import store

    for run in store._RUNS.values():  # noqa: SLF001
        return run.router_agent or "script"
    return "script"


def _token(handle: dict[str, Any]) -> str:
    if not HAS_MSAL:
        raise RuntimeError("msal_missing")
    cache_path = Path(handle["token_path"])
    cache = msal.SerializableTokenCache()
    if cache_path.is_file():
        cache.deserialize(cache_path.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        handle.get("client_id") or config.MS_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{config.MS_TENANT}",
        token_cache=cache,
    )
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError("no_session")
    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise RuntimeError("expired")
    cache_path.write_text(cache.serialize(), encoding="utf-8")
    return result["access_token"]


def _graph(handle: dict[str, Any], method: str, path: str, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    token = _token(handle)
    hdrs = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    resp = requests.request(method, GRAPH + path, params=params, json=json_body, headers=hdrs, timeout=20)
    if resp.status_code >= 400:
        raise RuntimeError(f"graph_{resp.status_code}")
    if not resp.content:
        return {}
    return resp.json()


def _me_email(token: str) -> str | None:
    try:
        resp = requests.get(GRAPH + "/me", headers={"Authorization": f"Bearer {token}"}, timeout=20)
        data = resp.json()
        return data.get("mail") or data.get("userPrincipalName")
    except Exception:
        return None
