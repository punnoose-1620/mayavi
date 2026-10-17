"""Generic HTTP client plus web search. Agents never import search.py or google_backend."""

from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests

import logger
import search
import paging
import store

_SESSION: requests.Session | None = None
_TIMEOUT = 20
_CAPTCHA_MARKERS = (
    "unusual traffic",
    "captcha",
    "verify you are human",
    "attention required",
    "cf-challenge",
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self._skip = False
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._chunks.append(data)

    def text(self) -> str:
        return "".join(self._chunks)


def get_url(url: str, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    return _request("GET", url, start=start, end=end, agent_id=agent_id)


def search_web(
    query: str,
    max_n: int = 10,
    start: int = 1,
    end: int = 1,
    agent_id: str | None = None,
) -> dict[str, Any]:
    run, agent_id = _run_agent(agent_id)
    q = str(query or "").strip()
    if not q:
        return _search_done(run, agent_id, {"ok": False, "error": "empty_query"}, q)
    try:
        count = max(1, min(int(max_n or 10), 10))
    except (TypeError, ValueError):
        count = 10
    raw = search.webSearch(q, num=count, start=1)
    if not raw.get("ok"):
        return _search_done(run, agent_id, {"ok": False, "error": raw.get("error") or "fail"}, q)
    items = list(raw.get("items") or [])
    chunk, s, e, total = paging.slice_rows(items, start, end)
    return _search_done(
        run,
        agent_id,
        {"ok": True, "items": chunk, "start": s, "end": e, "total_pages": total},
        q,
    )


def post_url(
    url: str,
    body: str | bytes | None = None,
    content_type: str = "application/x-www-form-urlencoded",
    start: int = 1,
    end: int = 1,
    agent_id: str | None = None,
) -> dict[str, Any]:
    return _request(
        "POST",
        url,
        start=start,
        end=end,
        agent_id=agent_id,
        body=body,
        content_type=content_type,
    )


def resetSession(agent_id: str | None = None) -> dict[str, Any]:
    global _SESSION
    run, agent_id = _run_agent(agent_id)
    _SESSION = _new_session()
    return logger.finish(
        event="tool",
        tool="resetSession",
        run_id=None if run is None else run.run_id,
        agent_name=agent_id,
        result={"ok": True},
        level=None if run is None else run.level,
        stakes=None if run is None else run.stakes,
        mail_cal=None if run is None else run.mail_cal,
    )


def _request(
    method: str,
    url: str,
    *,
    start: int,
    end: int,
    agent_id: str | None,
    body: str | bytes | None = None,
    content_type: str | None = None,
) -> dict[str, Any]:
    run, agent_id = _run_agent(agent_id)
    session = _session()
    current = url
    status_code = 0
    bot = False
    text = ""
    host = ""
    try:
        for _ in range(6):
            check = _check_url(current)
            if not check["ok"]:
                return _done(method, run, agent_id, check, host=host)
            host = check["host"]
            headers = {}
            if method == "POST" and content_type:
                headers["Content-Type"] = content_type
            resp = session.request(
                method if current == url else "GET",
                current,
                data=body if current == url else None,
                headers=headers,
                timeout=_TIMEOUT,
                allow_redirects=False,
            )
            status_code = resp.status_code
            if status_code in {301, 302, 303, 307, 308} and resp.headers.get("Location"):
                current = _absolute(current, resp.headers["Location"])
                body = None
                continue
            text = _as_text(resp)
            bot = _bot_detected(status_code, text)
            break
        else:
            return _done(
                method,
                run,
                agent_id,
                {"ok": False, "error": "too_many_redirects", "host": host},
                host=host,
            )
    except Exception as exc:
        return _done(
            method,
            run,
            agent_id,
            {"ok": False, "error": type(exc).__name__, "host": host},
            host=host,
        )
    chunk, s, e, total = paging.slice_chars(text, start, end)
    result = {
        "ok": True,
        "status_code": status_code,
        "text": chunk,
        "start": s,
        "end": e,
        "total_pages": total,
        "bot_detected": bot,
        "host": host,
    }
    return _done(method, run, agent_id, result, host=host, status_code=status_code, bot=bot)


def _done(
    method: str,
    run: Any,
    agent_id: str | None,
    result: dict[str, Any],
    *,
    host: str = "",
    status_code: int | None = None,
    bot: bool = False,
) -> dict[str, Any]:
    tool = "get_url" if method == "GET" else "post_url"
    summary = f"method={method} host={host} status={status_code or result.get('status_code', '')} bot_detected={bot or result.get('bot_detected', False)}"
    return logger.finish(
        event="tool",
        tool=tool,
        run_id=None if run is None else run.run_id,
        agent_name=agent_id,
        result=result,
        level=None if run is None else run.level,
        stakes=None if run is None else run.stakes,
        mail_cal=None if run is None else run.mail_cal,
        summary=summary,
    )


def _search_done(run: Any, agent_id: str | None, result: dict[str, Any], query: str) -> dict[str, Any]:
    q = re.sub(r"\s+", " ", query).strip()[:80]
    hits = len(result.get("items") or [])
    err = result.get("error") or ""
    summary = f"q={q} hits={hits}" if result.get("ok") else f"q={q} error={err}"
    return logger.finish(
        event="tool",
        tool="search_web",
        run_id=None if run is None else run.run_id,
        agent_name=agent_id,
        result=result,
        level=None if run is None else run.level,
        stakes=None if run is None else run.stakes,
        mail_cal=None if run is None else run.mail_cal,
        summary=summary,
    )


def _run_agent(agent_id: str | None) -> tuple[Any, str | None]:
    if not agent_id:
        return None, None
    return store.run_for_agent(agent_id), agent_id


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _new_session()
    return _SESSION


def _new_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = "mayavi/1.0"
    return session


def _check_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return {"ok": False, "error": "scheme_denied"}
    host = parsed.hostname
    if not host:
        return {"ok": False, "error": "no_host"}
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror:
        return {"ok": False, "error": "dns_failed", "host": host}
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return {"ok": False, "error": "ssrf_denied", "host": host}
    return {"ok": True, "host": host}


def _absolute(current: str, location: str) -> str:
    if location.startswith("http://") or location.startswith("https://"):
        return location
    parsed = urlparse(current)
    if location.startswith("/"):
        return f"{parsed.scheme}://{parsed.netloc}{location}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rsplit('/', 1)[0]}/{location}"


def _as_text(resp: requests.Response) -> str:
    ctype = (resp.headers.get("Content-Type") or "").lower()
    body = resp.content.decode(resp.encoding or "utf-8", errors="replace")
    if "html" in ctype or body.lstrip()[:15].lower().startswith("<!doctype") or "<html" in body[:200].lower():
        parser = _TextExtractor()
        try:
            parser.feed(body)
            return parser.text()
        except Exception:
            return body
    return body


def _bot_detected(status_code: int, text: str) -> bool:
    if status_code in {403, 429}:
        return True
    lower = text.lower()
    return any(marker in lower for marker in _CAPTCHA_MARKERS)
