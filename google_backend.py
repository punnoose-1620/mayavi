"""Private Gmail, Calendar, and Custom Search backend. Not in the agent schema."""

from __future__ import annotations

import base64
import json
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import requests

import config
import logger

CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    HAS_GOOGLE = True
except ImportError:
    HAS_GOOGLE = False
    Request = Credentials = InstalledAppFlow = build = None  # type: ignore

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
]


def connectToGoogle(open_browser: bool = True) -> dict[str, Any]:
    if not HAS_GOOGLE:
        return _log_connect({"ok": False, "error": "google_libs_missing"})
    if not config.GOOGLE_CLIENT_ID or not config.GOOGLE_CLIENT_SECRET:
        return _log_connect({"ok": False, "error": "not_configured"})
    token_path = config.TOKEN_DIR / "token_google.json"
    creds = _load_creds(token_path)
    try:
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not open_browser:
                    return _log_connect({"ok": False, "error": "browser_required"})
                flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
                creds = flow.run_local_server(port=0, open_browser=True)
            token_path.write_text(creds.to_json(), encoding="utf-8")
        email = _account_email(creds)
        if config.GOOGLE_LOGIN_HINT and email and email.lower() != config.GOOGLE_LOGIN_HINT.lower():
            return _log_connect({"ok": False, "error": "wrong_account"})
        handle = {"provider": "google", "token_path": str(token_path), "email": email}
        return _log_connect({"ok": True, "handle": handle, "email": email, "provider": "google"})
    except Exception as exc:
        return _log_connect({"ok": False, "error": type(exc).__name__})


def listMails(handle: dict[str, Any], time_min: str | None = None, max_n: int = 20, start: int = 1, end: int = 1) -> dict[str, Any]:
    service = _gmail(handle)
    resp = service.users().messages().list(userId="me", maxResults=min(max_n, 50), q=_time_query(time_min)).execute()
    messages = resp.get("messages") or []
    return {"ok": True, "items": messages, "total_pages": 1, "start": start, "end": end}


def searchMails(handle: dict[str, Any], query: str, time_min: str | None = None, max_n: int = 20, start: int = 1, end: int = 1) -> dict[str, Any]:
    q = query
    extra = _time_query(time_min)
    if extra:
        q = f"{q} {extra}".strip()
    service = _gmail(handle)
    resp = service.users().messages().list(userId="me", maxResults=min(max_n, 50), q=q).execute()
    return {"ok": True, "items": resp.get("messages") or [], "start": start, "end": end, "total_pages": 1}


def openMail(handle: dict[str, Any], mail_id: str, start: int = 1, end: int = 1) -> dict[str, Any]:
    import paging

    service = _gmail(handle)
    msg = service.users().messages().get(userId="me", id=mail_id, format="full").execute()
    text = _message_text(msg)
    chunk, s, e, total = paging.slice_chars(text, start, end)
    return {"ok": True, "text": chunk, "start": s, "end": e, "total_pages": total, "id": mail_id}


def sendMail(handle: dict[str, Any], to: list[str], subject: str, body: str, cc: list[str] | None = None) -> dict[str, Any]:
    service = _gmail(handle)
    mime = MIMEText(body, "plain")
    mime["to"] = ", ".join(to)
    if cc:
        mime["cc"] = ", ".join(cc)
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"ok": True, "id": sent.get("id")}


def replyMail(handle: dict[str, Any], thread_id: str, body: str, to: list[str] | None = None, subject: str = "") -> dict[str, Any]:
    service = _gmail(handle)
    mime = MIMEText(body, "plain")
    if to:
        mime["to"] = ", ".join(to)
    if subject:
        mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
    sent = service.users().messages().send(userId="me", body={"raw": raw, "threadId": thread_id}).execute()
    return {"ok": True, "id": sent.get("id")}


def listCalendars(handle: dict[str, Any]) -> dict[str, Any]:
    service = _calendar(handle)
    resp = service.calendarList().list().execute()
    items = [{"id": c.get("id"), "summary": c.get("summary")} for c in resp.get("items") or []]
    return {"ok": True, "items": items}


def listCalendarEvents(handle: dict[str, Any], calendar_id: str, time_min: str | None = None, time_max: str | None = None, start: int = 1, end: int = 1) -> dict[str, Any]:
    service = _calendar(handle)
    kwargs: dict[str, Any] = {"calendarId": calendar_id, "maxResults": 50, "singleEvents": True, "orderBy": "startTime"}
    if time_min:
        kwargs["timeMin"] = time_min
    if time_max:
        kwargs["timeMax"] = time_max
    resp = service.events().list(**kwargs).execute()
    return {"ok": True, "items": resp.get("items") or [], "start": start, "end": end, "total_pages": 1}


def openCalendarEvent(handle: dict[str, Any], calendar_id: str, event_id: str) -> dict[str, Any]:
    service = _calendar(handle)
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    return {"ok": True, "event": _public_event(event)}


def createCalendarEvent(handle: dict[str, Any], calendar_id: str, summary: str, start: dict[str, Any], end: dict[str, Any], timezone: str, description: str = "", location: str = "", attendees: list[str] | None = None) -> dict[str, Any]:
    service = _calendar(handle)
    body: dict[str, Any] = {
        "summary": summary,
        "description": description,
        "location": location,
        "start": {**start, "timeZone": timezone},
        "end": {**end, "timeZone": timezone},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    event = service.events().insert(calendarId=calendar_id, body=body, sendUpdates="all").execute()
    return {"ok": True, "id": event.get("id")}


def updateCalendarEvent(handle: dict[str, Any], calendar_id: str, event_id: str, patch: dict[str, Any], scope: str = "this", etag: str | None = None) -> dict[str, Any]:
    service = _calendar(handle)
    kwargs: dict[str, Any] = {"calendarId": calendar_id, "eventId": event_id, "body": patch, "sendUpdates": "all"}
    if scope != "series":
        kwargs["body"] = patch
    event = service.events().patch(**kwargs).execute()
    return {"ok": True, "id": event.get("id")}


def cancelCalendarEvent(handle: dict[str, Any], calendar_id: str, event_id: str, scope: str = "this") -> dict[str, Any]:
    service = _calendar(handle)
    service.events().delete(calendarId=calendar_id, eventId=event_id, sendUpdates="all").execute()
    return {"ok": True, "id": event_id}


def findFreeBusy(handle: dict[str, Any], time_min: str, time_max: str, items: list[str] | None = None) -> dict[str, Any]:
    service = _calendar(handle)
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": i} for i in (items or ["primary"])],
    }
    resp = service.freebusy().query(body=body).execute()
    return {"ok": True, "calendars": resp.get("calendars") or {}}


def searchWeb(query: str, *, num: int = 10, start: int = 1) -> dict[str, Any]:
    """Custom Search JSON API. Never log the API key or the request URL."""
    key = (config.GOOGLE_CLOUD_API_KEY or "").strip()
    cx = (config.GOOGLE_CSE_ID or "").strip()
    q = str(query or "").strip()[:200]
    if not key or not cx:
        return {"ok": False, "error": "not_configured"}
    if not q:
        return {"ok": False, "error": "empty_query"}
    try:
        count = max(1, min(int(num or 10), 10))
        index = max(1, int(start or 1))
    except (TypeError, ValueError):
        count, index = 10, 1
    try:
        resp = requests.get(
            CSE_ENDPOINT,
            params={"key": key, "cx": cx, "q": q, "num": count, "start": index},
            timeout=20,
        )
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    if resp.status_code == 429:
        return {"ok": False, "error": "quota"}
    if resp.status_code >= 400:
        return {"ok": False, "error": _cse_error_code(resp)}
    try:
        blob = resp.json()
    except ValueError:
        return {"ok": False, "error": "bad_json"}
    if not isinstance(blob, dict):
        return {"ok": False, "error": "bad_json"}
    items: list[dict[str, str]] = []
    for row in blob.get("items") or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("link") or "").strip()
        if not url:
            continue
        items.append(
            {
                "title": str(row.get("title") or "")[:200],
                "url": url,
                "snippet": str(row.get("snippet") or "")[:400],
            }
        )
    return {"ok": True, "items": items}


def _cse_error_code(resp: Any) -> str:
    """Short Google reason only. Never the request URL or API key."""
    try:
        blob = resp.json()
        err = blob.get("error") if isinstance(blob, dict) else None
        if isinstance(err, dict):
            rows = err.get("errors") or []
            if rows and isinstance(rows[0], dict):
                reason = str(rows[0].get("reason") or "").strip()
                if reason and reason.replace("_", "").isalnum():
                    return reason
            status = str(err.get("status") or "").strip()
            if status and status.replace("_", "").isalnum():
                return status
    except Exception:
        pass
    code = getattr(resp, "status_code", None)
    return f"http_{code}" if code else "http_error"


def _log_connect(result: dict[str, Any]) -> dict[str, Any]:
    return logger.finish(
        event="factory",
        tool="connectToGoogle",
        run_id=_run_id(),
        agent_name=_agent(),
        result={"ok": result.get("ok"), "error": result.get("error"), "email": result.get("email"), "provider": "google"}
        if result.get("ok")
        else result,
        summary="provider=google",
    ) | ({"handle": result["handle"]} if result.get("handle") else {})


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


def _client_config() -> dict[str, Any]:
    return {
        "installed": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def _load_creds(path: Path) -> Any:
    if not HAS_GOOGLE or not path.is_file():
        return None
    info = json.loads(path.read_text(encoding="utf-8"))
    return Credentials.from_authorized_user_info(info, SCOPES)


def _account_email(creds: Any) -> str | None:
    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        return profile.get("emailAddress")
    except Exception:
        return None


def _gmail(handle: dict[str, Any]) -> Any:
    if not HAS_GOOGLE:
        raise RuntimeError("google_libs_missing")
    creds = _load_creds(Path(handle["token_path"]))
    if creds is None:
        raise RuntimeError("no_session")
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _calendar(handle: dict[str, Any]) -> Any:
    if not HAS_GOOGLE:
        raise RuntimeError("google_libs_missing")
    creds = _load_creds(Path(handle["token_path"]))
    if creds is None:
        raise RuntimeError("no_session")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _time_query(time_min: str | None) -> str:
    return f"after:{time_min}" if time_min else ""


def _message_text(msg: dict[str, Any]) -> str:
    payload = msg.get("payload") or {}
    parts = payload.get("parts") or [payload]
    chunks = []
    for part in parts:
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            chunks.append(base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace"))
    if not chunks and msg.get("snippet"):
        chunks.append(msg["snippet"])
    return "\n".join(chunks)


def _public_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "start": event.get("start"),
        "end": event.get("end"),
        "status": event.get("status"),
        "etag": event.get("etag"),
    }
