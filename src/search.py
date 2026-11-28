"""Private search backends. Agents never import this file.

Parent webSearch chains CSE, then SerpAPI, then ScraperAPI, then HTML search.
HTML search is DuckDuckGo's HTML page (not google.com): HTTP GET first,
Chromium only if that page is empty or blocked. Fetch of result URLs stays get_url.
"""

from __future__ import annotations

import re
import socket
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

import config

CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"
SERP_ENDPOINT = "https://serpapi.com/search.json"
SCRAPER_ENDPOINT = "https://api.scraperapi.com/structured/google/search"
HTML_ENDPOINT = "https://html.duckduckgo.com/html/"
_TIMEOUT = 30
_PROBE_HOSTS = (("1.1.1.1", 443), ("8.8.8.8", 53))
_HTML_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_CAPTCHA_MARKERS = (
    "unusual traffic",
    "captcha",
    "verify you are human",
    "attention required",
    "cf-challenge",
    "anomaly-modal",
    "bots use duckduckgo",
)
_SKIP_HOSTS = frozenset(
    {
        "google.com",
        "www.google.com",
        "duckduckgo.com",
        "www.duckduckgo.com",
        "html.duckduckgo.com",
        "lite.duckduckgo.com",
    }
)


def search_configured() -> bool:
    """True when a paid/API backend has credentials. HTML search does not need this."""
    key = (config.GOOGLE_CLOUD_API_KEY or "").strip()
    cx = (config.GOOGLE_CSE_ID or "").strip()
    serp = (config.SERPAPI_API_KEY or "").strip()
    scraper = (config.SCRAPERAPI_API_KEY or "").strip()
    return bool((key and cx) or serp or scraper)


def net_ok() -> bool:
    for host, port in _PROBE_HOSTS:
        try:
            sock = socket.create_connection((host, port), timeout=2)
            sock.close()
            return True
        except OSError:
            continue
    return False


def status() -> dict[str, Any]:
    """Whether the operator Web control can run. Never includes keys."""
    keys = search_configured()
    online = net_ok()
    reason = ""
    if not online:
        reason = "offline"
    return {
        "ok": True,
        "configured": keys or online,
        "online": online,
        "available": online,
        "reason": reason,
    }


def webSearch(query: str, *, num: int = 10, start: int = 1) -> dict[str, Any]:
    """CSE, then SerpAPI, then ScraperAPI, then HTML search. Stop on the first hit list."""
    q = str(query or "").strip()[:200]
    if not q:
        return {"ok": False, "error": "empty_query"}
    try:
        count = max(1, min(int(num or 10), 10))
        index = max(1, int(start or 1))
    except (TypeError, ValueError):
        count, index = 10, 1
    last: dict[str, Any] = {"ok": False, "error": "not_configured"}
    empty: dict[str, Any] | None = None
    for backend in (cse_search, serp_search, scraper_search, html_search):
        result = backend(q, num=count, start=index)
        if str(result.get("error") or "") == "not_configured":
            continue
        last = result
        if result.get("ok") and result.get("items"):
            return result
        if result.get("ok"):
            empty = result
    return empty or last


def cse_search(query: str, *, num: int = 10, start: int = 1) -> dict[str, Any]:
    key = (config.GOOGLE_CLOUD_API_KEY or "").strip()
    cx = (config.GOOGLE_CSE_ID or "").strip()
    if not (key and cx):
        return {"ok": False, "error": "not_configured"}
    try:
        resp = requests.get(
            CSE_ENDPOINT,
            params={"key": key, "cx": cx, "q": query, "num": num, "start": start},
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
    return {"ok": True, "items": _organic_items(blob.get("items"), num)}


def serp_search(query: str, *, num: int = 10, start: int = 1) -> dict[str, Any]:
    serp_key = (config.SERPAPI_API_KEY or "").strip()
    if not serp_key:
        return {"ok": False, "error": "not_configured"}
    try:
        resp = requests.get(
            SERP_ENDPOINT,
            params={
                "engine": "google",
                "q": query,
                "api_key": serp_key,
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


def scraper_search(query: str, *, num: int = 10, start: int = 1) -> dict[str, Any]:
    scraper_key = (config.SCRAPERAPI_API_KEY or "").strip()
    if not scraper_key:
        return {"ok": False, "error": "not_configured"}
    try:
        resp = requests.get(
            SCRAPER_ENDPOINT,
            params={"api_key": scraper_key, "query": query, "tld": "com"},
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
    items = _organic_items(rows, num + max(0, start - 1))
    offset = max(0, start - 1)
    return {"ok": True, "items": items[offset : offset + num]}


def html_search(query: str, *, num: int = 10, start: int = 1) -> dict[str, Any]:
    """DuckDuckGo HTML. HTTP GET first; Chromium only if that page is empty or blocked."""
    http = _html_http(query, num=num, start=start)
    if http.get("ok") and http.get("items"):
        return http
    chrome = _html_chromium(query, num=num, start=start)
    if chrome.get("ok") and chrome.get("items"):
        return chrome
    if str(chrome.get("error") or "") == "chromium_unavailable":
        return http
    if _blocked_result(http):
        return chrome
    return http


def _html_http(query: str, *, num: int, start: int) -> dict[str, Any]:
    headers = {"User-Agent": _HTML_UA, "Accept": "text/html"}
    try:
        resp = requests.get(
            HTML_ENDPOINT,
            params={"q": query},
            headers=headers,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    err = _http_error(resp)
    if err:
        return err
    body = resp.text or ""
    if _blocked_html(resp.status_code, body):
        return {"ok": False, "error": "captcha"}
    items = _parse_html_results(body, num=num, start=start)
    if items:
        return {"ok": True, "items": items}
    try:
        resp = requests.post(
            HTML_ENDPOINT,
            data={"q": query},
            headers=headers,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__}
    err = _http_error(resp)
    if err:
        return err
    body = resp.text or ""
    if _blocked_html(resp.status_code, body):
        return {"ok": False, "error": "captcha"}
    return {"ok": True, "items": _parse_html_results(body, num=num, start=start)}


def _html_chromium(query: str, *, num: int, start: int) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {"ok": False, "error": "chromium_unavailable"}
    url = HTML_ENDPOINT + "?q=" + quote_plus(query)
    browser = None
    body = ""
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(user_agent=_HTML_UA)
            page.goto(url, wait_until="domcontentloaded", timeout=_TIMEOUT * 1000)
            body = page.content() or ""
            browser.close()
            browser = None
    except Exception as exc:
        name = type(exc).__name__
        lowered = str(exc).lower()
        if "executable doesn't exist" in lowered or "playwright install" in lowered:
            return {"ok": False, "error": "chromium_unavailable"}
        return {"ok": False, "error": name}
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
    if _blocked_html(200, body):
        return {"ok": False, "error": "captcha"}
    return {"ok": True, "items": _parse_html_results(body, num=num, start=start)}


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


def _parse_html_results(body: str, *, num: int, start: int) -> list[dict[str, str]]:
    parser = _HTMLResults()
    try:
        parser.feed(body or "")
        parser.close()
    except Exception:
        pass
    offset = max(0, start - 1)
    return parser.items[offset : offset + num]


def _blocked_html(status_code: int, text: str) -> bool:
    if status_code in {403, 429}:
        return True
    lower = (text or "").lower()
    return any(marker in lower for marker in _CAPTCHA_MARKERS)


def _blocked_result(result: dict[str, Any]) -> bool:
    err = str(result.get("error") or "")
    return err in {"captcha", "quota", "http_403", "http_429"}


def _skip_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host in _SKIP_HOSTS:
        return True
    return host.endswith(".google.com")


def _resolve_result_url(href: str) -> str:
    raw = str(href or "").strip()
    if not raw or raw.startswith("#") or raw.lower().startswith("javascript:"):
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if "duckduckgo.com" in host:
        qs = parse_qs(parsed.query)
        target = (qs.get("uddg") or [""])[0]
        if target:
            return unquote(target).strip()
        return ""
    return raw


def _short_error(message: str) -> str:
    lowered = message.lower()
    if "invalid api key" in lowered or "unauthorized" in lowered:
        return "http_401"
    if "quota" in lowered or "limit" in lowered:
        return "quota"
    token = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in message)[:40].strip("_")
    return token.lower() or "fail"


class _HTMLResults(HTMLParser):
    """Pull {title, url, snippet} from DuckDuckGo HTML (result__a / uddg links)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[dict[str, str]] = []
        self._href = ""
        self._title: list[str] = []
        self._snippet: list[str] = []
        self._in_title = False
        self._in_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        info = {key: str(value or "") for key, value in attrs}
        cls = info.get("class") or ""
        href = info.get("href") or ""
        if tag == "a" and ("result__a" in cls.split() or "uddg=" in href):
            url = _resolve_result_url(href)
            if url and not _skip_url(url):
                self._href = url
                self._title = []
                self._in_title = True
            return
        if tag in {"a", "div"} and "result__snippet" in cls.split():
            self._snippet = []
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            title = re.sub(r"\s+", " ", "".join(self._title)).strip()[:200]
            if self._href:
                self.items.append({"title": title, "url": self._href, "snippet": ""})
            self._in_title = False
            self._href = ""
            return
        if tag in {"a", "div"} and self._in_snippet:
            snippet = re.sub(r"\s+", " ", "".join(self._snippet)).strip()[:400]
            if self.items and not self.items[-1]["snippet"]:
                self.items[-1]["snippet"] = snippet
            self._in_snippet = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
        elif self._in_snippet:
            self._snippet.append(data)
