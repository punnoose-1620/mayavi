"""Private SerpAPI / ScraperAPI web search. Agents never import this file."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import requests

import config

SERP_ENDPOINT = "https://serpapi.com/search.json"
SCRAPER_ENDPOINT = "https://api.scraperapi.com/structured/google/search"
_TIMEOUT = 30


def webSearch(query: str, *, num: int = 10, start: int = 1) -> dict[str, Any]:
    """SerpAPI first, ScraperAPI if Serp is missing or fails. Never log the API key or request URL."""
    q = str(query or "").strip()[:200]
    if not q:
        return {"ok": False, "error": "empty_query"}
    try:
        count = max(1, min(int(num or 10), 10))
        index = max(1, int(start or 1))
    except (TypeError, ValueError):
        count, index = 10, 1
    serp_key = (config.SERPAPI_API_KEY or "").strip()
    scraper_key = (config.SCRAPERAPI_API_KEY or "").strip()
    if not serp_key and not scraper_key:
        return {"ok": False, "error": "not_configured"}
    last: dict[str, Any] = {"ok": False, "error": "not_configured"}
    if serp_key:
        last = _serp_search(q, key=serp_key, num=count, start=index)
        if last.get("ok"):
            return last
    if scraper_key:
        last = _scraper_search(q, key=scraper_key, num=count, start=index)
        if last.get("ok"):
            return last
    return last


def _serp_search(query: str, *, key: str, num: int, start: int) -> dict[str, Any]:
    try:
        resp = requests.get(
            SERP_ENDPOINT,
            params={
                "engine": "google",
                "q": query,
                "api_key": key,
                "num": num,
                "start": max(0, start - 1),
            },
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    err = _http_error(resp)
    if err:
        return err
    blob = _json_blob(resp)
    if blob is None:
        return {"ok": False, "error": "bad_json"}
    api_err = str(blob.get("error") or "").strip()
    if api_err:
        return {"ok": False, "error": _short_error(api_err)}
    return {"ok": True, "items": _organic_items(blob.get("organic_results"), num)}


def _scraper_search(query: str, *, key: str, num: int, start: int) -> dict[str, Any]:
    try:
        resp = requests.get(
            SCRAPER_ENDPOINT,
            params={"api_key": key, "query": query, "tld": "com"},
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    err = _http_error(resp)
    if err:
        return err
    blob = _json_blob(resp)
    if blob is None:
        return {"ok": False, "error": "bad_json"}
    rows = blob.get("organic_results") or blob.get("organic")
    items = _organic_items(rows, num)
    offset = max(0, start - 1)
    return {"ok": True, "items": items[offset : offset + num]}


def _http_error(resp: Any) -> dict[str, Any] | None:
    code = getattr(resp, "status_code", None)
    if code == 429:
        return {"ok": False, "error": "quota"}
    if isinstance(code, int) and code >= 400:
        return {"ok": False, "error": f"http_{code}"}
    return None


def _json_blob(resp: Any) -> dict[str, Any] | None:
    try:
        blob = resp.json()
    except ValueError:
        return None
    return blob if isinstance(blob, dict) else None


def _organic_items(rows: Any, num: int) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("link") or row.get("url") or "").strip()
        if not url or _skip_url(url):
            continue
        items.append(
            {
                "title": str(row.get("title") or "")[:200],
                "url": url,
                "snippet": str(row.get("snippet") or "")[:400],
            }
        )
        if len(items) >= num:
            break
    return items


def _skip_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "www.google.com" or host == "google.com"


def _short_error(message: str) -> str:
    lowered = message.lower()
    if "invalid api key" in lowered or "unauthorized" in lowered:
        return "http_401"
    if "quota" in lowered or "limit" in lowered:
        return "quota"
    token = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in message)[:40].strip("_")
    return token.lower() or "fail"
