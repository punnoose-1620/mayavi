"""Factory live-search pipeline. Agents never import this file."""

from __future__ import annotations

import json
from typing import Any

import blackboard
import config
import logger
import search
import web_scrape
from store import Run

_MAX_URLS = 3
_CHUNK = 1800
_DIGEST_CAP = 12000
_QUERY_SYS = (
    "You write one web search query for the user request. Reply with a JSON object only: "
    '{"query": "short search string"}. No tools.'
)
_URL_SYS = (
    "Pick the most relevant result URLs for the user request. Reply with a JSON object only: "
    '{"urls": ["https://..."]}. At most 3 http(s) URLs from the list. No tools.'
)
_NOTE_SYS = (
    "Extract facts from this live-search excerpt that help answer the user. "
    'Reply with a JSON object only: {"notes": "bullet facts"}. Do not invent URLs. No tools.'
)
_ANSWER_SYS = (
    "Answer the user using only the live-search notes. Cite source URLs in the prose. "
    'Reply with a JSON object only: {"final": "the answer"}. No tools.'
)


def gather(run: Run) -> str:
    """Search, fetch pages, store a digest on the run. Empty string if search cannot run."""
    if not getattr(run, "web", False):
        return ""
    st = search.status()
    if not st.get("available"):
        reason = str(st.get("reason") or "not_configured")
        run.notices.append("web_not_configured" if reason == "not_configured" else "web_offline")
        return ""
    try:
        scout_name = _scout(run)
        run.web_stage = "query"
        query = _json_text(_ask(run, scout_name, _QUERY_SYS, run.user_prompt), "query") or (run.user_prompt or "")[:200]
        query = str(query).strip()[:200]
        logger.finish(
            event="factory",
            tool="search_web",
            run_id=run.run_id,
            agent_name=scout_name or run.router_agent or "script",
            result={"ok": True, "query": query[:80]},
            level=run.level,
            stakes=run.stakes,
            mail_cal=run.mail_cal,
            summary=f"query={query[:80]}",
        )
        raw = search.webSearch(query, num=8)
        if not raw.get("ok"):
            err = str(raw.get("error") or "fail")
            run.notices.append(f"web_search_failed:{err}")
            return ""
        items = [row for row in (raw.get("items") or []) if isinstance(row, dict)]
        run.web_hits = items
        run.web_stage = "urls"
        urls = _pick_urls(run, scout_name, items)
        pages: list[str] = []
        for url in urls:
            fetched = web_scrape.get_url(url, start=1, end=2, agent_id=scout_name)
            if not fetched.get("ok"):
                continue
            title = _title_for(url, items)
            body = str(fetched.get("text") or "").strip()
            if not body:
                continue
            pages.append(f"## {title}\n{url}\n{body}")
            if sum(len(p) for p in pages) >= _DIGEST_CAP:
                break
        digest = "\n\n".join(pages)[:_DIGEST_CAP]
        run.web_digest = digest
        if not digest:
            run.notices.append("web_fetch_empty")
        return digest
    finally:
        run.web_stage = ""


def pin(run: Run) -> None:
    digest = str(getattr(run, "web_digest", "") or "").strip()
    if not digest or run.blackboard is None:
        return
    body = ("Live-search digest:\n" + digest)[: config.BLACKBOARD_MAX_LEN]
    blackboard.send_message(
        body,
        "memory",
        agent_id=run.router_agent or "script",
        factory=True,
    )


def synthesize(run: Run) -> str:
    """Larger model reads the digest in chunks, then answers. Empty if there is no digest."""
    digest = str(getattr(run, "web_digest", "") or "").strip()
    if not digest:
        return ""
    import executor

    lead, _support = executor._committee_roles(run)
    created = executor.createAgent(run.run_id, "drafter", lead, parent_agent=run.router_agent)
    name = created.get("agent_name")
    if not created.get("ok") or not name:
        return ""
    notes: list[str] = []
    try:
        for chunk in _chunks(digest):
            run.web_stage = "notes"
            note = _json_text(
                _ask(
                    run,
                    name,
                    _NOTE_SYS,
                    f"User request:\n{run.user_prompt}\n\nExcerpt:\n{chunk}",
                ),
                "notes",
            )
            if note:
                notes.append(note)
        bundle = "\n".join(notes)[:_DIGEST_CAP] or digest[:4000]
        run.web_stage = "answer"
        final = _json_text(
            _ask(
                run,
                name,
                _ANSWER_SYS,
                f"User request:\n{run.user_prompt}\n\nNotes:\n{bundle}",
            ),
            "final",
        )
        return str(final or "").strip() or bundle[:2000]
    finally:
        run.web_stage = ""


def _scout(run: Run) -> str | None:
    import executor

    created = executor.createAgent(run.run_id, "scout", "router", parent_agent=run.router_agent)
    if created.get("ok"):
        return str(created.get("agent_name") or "") or None
    return run.router_agent


def _pick_urls(run: Run, agent_name: str | None, items: list[dict[str, Any]]) -> list[str]:
    listed = []
    for row in items:
        url = str(row.get("url") or "").strip()
        if url:
            listed.append(f"- {row.get('title') or ''} | {url}")
    blob = _ask(
        run,
        agent_name,
        _URL_SYS,
        f"User request:\n{run.user_prompt}\n\nResults:\n" + "\n".join(listed[:10]),
    )
    picked = _json_urls(blob)
    if not picked:
        picked = [str(row.get("url") or "") for row in items]
    out: list[str] = []
    seen: set[str] = set()
    allowed = {str(row.get("url") or "") for row in items}
    for url in picked:
        if url not in allowed or url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= _MAX_URLS:
            break
    return out


def _ask(run: Run, agent_name: str | None, system: str, user: str) -> str:
    import executor

    if not agent_name or agent_name not in run.agents:
        return ""
    agent = run.agents[agent_name]
    history = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    return executor._generate(run, agent, history)


def _json_text(raw: str, key: str) -> str:
    blob = _first_object(raw)
    if not isinstance(blob, dict):
        return ""
    return str(blob.get(key) or "").strip()


def _json_urls(raw: str) -> list[str]:
    blob = _first_object(raw)
    if not isinstance(blob, dict):
        return []
    rows = blob.get("urls")
    if not isinstance(rows, list):
        return []
    out: list[str] = []
    for item in rows:
        url = str(item or "").strip()
        if url.startswith("http://") or url.startswith("https://"):
            out.append(url)
    return out


def _first_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    try:
        blob = json.loads(text)
        return blob if isinstance(blob, dict) else None
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        blob = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return blob if isinstance(blob, dict) else None


def _chunks(text: str) -> list[str]:
    body = str(text or "")
    if not body:
        return []
    return [body[i : i + _CHUNK] for i in range(0, len(body), _CHUNK)][:8]


def _title_for(url: str, items: list[dict[str, Any]]) -> str:
    for row in items:
        if str(row.get("url") or "") == url:
            return str(row.get("title") or url)[:200]
    return url
