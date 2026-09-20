"""Committee boards and durable threads. Agents never import this file.

The live board on a Run is ephemeral: create at session start, drop at teardown.
Durable notes live under state/threads/ as a context card (not votes). Only medium
creates a thread by default. Attaching a thread_id raises a mapped-small run to
medium; a large run may seed from and distill back to the same card.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import logger
import store
from store import Blackboard, Run

ALLOWED_KINDS = {"draft", "critique", "debug", "vote", "rules", "memory"}
FACTORY_ONLY_KINDS = {"rules", "memory"}
CARD_DIGEST = 800


def create_board(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        return _factory("createBlackBoard", None, "script", {"ok": False, "error": "no_run"})
    run.blackboard = Blackboard(
        run_id=run_id,
        max_len=config.BLACKBOARD_MAX_LEN,
        max_count=config.BLACKBOARD_MAX_COUNT,
    )
    return _factory("createBlackBoard", run, run.router_agent or "script", {"ok": True})


def set_rules(run_id: str, *, pin_coding_rules: bool = False) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None or run.blackboard is None:
        return _factory("setBlackBoardRules", None, "script", {"ok": False, "error": "no_blackboard"})
    if run.blackboard.frozen:
        return _factory("setBlackBoardRules", run, run.router_agent or "script", {"ok": False, "error": "frozen"})
    run.blackboard.frozen = True
    run.rules_frozen = True
    if pin_coding_rules:
        send_message(
            "Coding rules are in force for this run. Full text is in session details via viewSessionDetails. Agents cannot overwrite rules.",
            "rules",
            agent_id=run.router_agent or "script",
            factory=True,
        )
    return _factory("setBlackBoardRules", run, run.router_agent or "script", {"ok": True})


def view_board(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None or run.blackboard is None:
        return _factory("viewBlackBoard", run, "script", {"ok": False, "error": "no_blackboard"})
    return _factory(
        "viewBlackBoard",
        run,
        run.router_agent or "script",
        {"ok": True, "messages": run.blackboard.messages},
    )


def send_message(
    body: str,
    kind: str,
    agent_id: str | None = None,
    factory: bool = False,
) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    if run is None or run.blackboard is None:
        return _tool("sendMessageToBlackboard", run, agent_id, {"ok": False, "error": "no_blackboard"})
    board = run.blackboard
    if kind not in ALLOWED_KINDS:
        return _tool("sendMessageToBlackboard", run, agent_id, {"ok": False, "error": "unknown_kind"})
    if kind in FACTORY_ONLY_KINDS and not factory:
        return _tool(
            "sendMessageToBlackboard",
            run,
            agent_id,
            {"ok": False, "error": "rules_locked" if kind == "rules" else "memory_locked"},
        )
    if len(body) > board.max_len:
        return _tool("sendMessageToBlackboard", run, agent_id, {"ok": False, "error": "too_long"})
    if len(board.messages) >= board.max_count:
        return _tool("sendMessageToBlackboard", run, agent_id, {"ok": False, "error": "cap"})
    role = run.agents[agent_id].role if agent_id in run.agents else "factory"
    msg = {
        "agent_id": agent_id,
        "role": role,
        "kind": kind,
        "body": body,
        "time": datetime.now(timezone.utc).isoformat(),
    }
    board.messages.append(msg)
    return _tool("sendMessageToBlackboard", run, agent_id, {"ok": True, "count": len(board.messages)})


def view_messages(n: int = 20, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    if run is None or run.blackboard is None:
        return _tool("viewBlackboardMessages", run, agent_id, {"ok": False, "error": "no_blackboard"})
    n = max(1, min(int(n), 50))
    items = run.blackboard.messages[-n:]
    return _tool("viewBlackboardMessages", run, agent_id, {"ok": True, "messages": items})


def pin_context_card(run: Run) -> dict[str, Any] | None:
    """Factory-only memory post. select_vote ignores this kind."""
    if not run.thread_id:
        return None
    card = context_card(run.thread or {})
    if not card.strip():
        return None
    return send_message(card[: config.BLACKBOARD_MAX_LEN], "memory", agent_id=run.router_agent or "script", factory=True)


def bind_thread(run: Run, thread_id: str | None) -> None:
    """Apply the CLI thread id after mapRoute. Small never creates a thread on its own."""
    wanted = (thread_id or "").strip() or None
    if wanted:
        loaded = load_thread(wanted)
        if loaded is None:
            run.notices.append(f"thread_not_found:{wanted}")
        else:
            run.thread_id = loaded["id"]
            run.thread = loaded
            if run.level == "small":
                run.level = "medium"
    if run.level in {"medium", "large"} and not run.thread_id:
        created = create_thread(title=_title(run.intent or run.user_prompt), goal=run.intent, prompt=run.user_prompt)
        run.thread_id = created["id"]
        run.thread = created
    if run.thread_id and run.thread is None:
        run.thread = load_thread(run.thread_id)


def distill(run: Run, answer: str | None) -> None:
    """Write a context card back to the selected thread. Never copies votes or debug."""
    if not run.thread_id or run.level == "small":
        return
    thread = run.thread or load_thread(run.thread_id) or create_thread(
        title=_title(run.intent or run.user_prompt),
        goal=run.intent,
        prompt=run.user_prompt,
        thread_id=run.thread_id,
    )
    thread["goal"] = (run.intent or thread.get("goal") or "")[:200]
    thread["title"] = thread.get("title") or _title(run.intent or run.user_prompt)
    thread["last_prompt"] = (run.user_prompt or "")[:300]
    thread["last_answer"] = (answer or "")[:CARD_DIGEST]
    thread["last_run_id"] = run.run_id
    thread["last_level"] = run.level
    thread["updated"] = _now()
    artifacts = list(thread.get("artifacts") or [])
    if run.keep_path is not None:
        note = str(run.keep_path)
        if run.ship_unlocked:
            artifacts = _uniq(artifacts + [f"shipped:{note}"])
        else:
            artifacts = _uniq(artifacts + [f"keep:{note}"])
    thread["artifacts"] = artifacts[-8:]
    if run.ship_unlocked and run.keep_path is not None and run.keep_path.is_dir():
        sources = list(thread.get("sources") or [])
        for path in sorted(run.keep_path.rglob("*")):
            if path.is_file():
                sources = _uniq(sources + [path.name])
        thread["sources"] = sources[-12:]
    open_items = list(thread.get("open") or [])
    if run.level == "large" and not run.ship_unlocked:
        open_items = _uniq(open_items + ["committee did not ship"])
    elif run.level == "large" and run.ship_unlocked:
        open_items = [item for item in open_items if item != "committee did not ship"]
    thread["open"] = open_items[-8:]
    decisions = list(thread.get("decisions") or [])
    if run.level == "large":
        decisions = _uniq(decisions + ["coding rules in force on large runs"])
    thread["decisions"] = decisions[-8:]
    save_thread(thread)
    run.thread = thread


def shipped_keep_paths(thread: dict[str, Any] | None) -> list[str]:
    """Keep folders recorded on a durable thread after a ship."""
    out: list[str] = []
    for item in (thread or {}).get("artifacts") or []:
        text = str(item)
        if text.startswith("shipped:"):
            out.append(text[8:])
    return out


def context_card(thread: dict[str, Any]) -> str:
    """The only text copied onto a live committee board from a durable thread."""
    lines = [
        f"thread: {thread.get('id') or ''}",
        f"title: {thread.get('title') or ''}",
        f"goal: {thread.get('goal') or ''}",
    ]
    if thread.get("last_prompt"):
        lines.append(f"last_prompt: {thread['last_prompt']}")
    sources = thread.get("sources") or []
    if sources:
        lines.append("sources:")
        for src in sources[:6]:
            lines.append(f"- {src}")
    artifacts = thread.get("artifacts") or []
    if artifacts:
        lines.append("artifacts:")
        for item in artifacts[:6]:
            lines.append(f"- {item}")
    decisions = thread.get("decisions") or []
    if decisions:
        lines.append("decisions:")
        for item in decisions[:6]:
            lines.append(f"- {item}")
    open_items = thread.get("open") or []
    if open_items:
        lines.append("open:")
        for item in open_items[:6]:
            lines.append(f"- {item}")
    digest = (thread.get("last_answer") or "").strip()
    if digest:
        lines.append("digest:")
        lines.append(digest[:CARD_DIGEST])
    return "\n".join(lines).strip()


def create_thread(
    *,
    title: str,
    goal: str = "",
    prompt: str = "",
    thread_id: str | None = None,
) -> dict[str, Any]:
    tid = thread_id or f"thr_{uuid.uuid4().hex[:12]}"
    now = _now()
    thread = {
        "id": tid,
        "title": _title(title),
        "goal": (goal or "")[:200],
        "last_prompt": (prompt or "")[:300],
        "last_answer": "",
        "last_run_id": None,
        "last_level": None,
        "sources": [],
        "artifacts": [],
        "decisions": [],
        "open": [],
        "created": now,
        "updated": now,
    }
    save_thread(thread)
    return thread


def list_threads() -> list[dict[str, Any]]:
    """Durable notebooks (medium and large). Live committee boards are not listed."""
    if not config.THREADS_DIR.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    paths = sorted(config.THREADS_DIR.glob("thr_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        blob = load_thread(path.stem)
        if blob is None or blob["id"] in seen:
            continue
        seen.add(blob["id"])
        rows.append(
            {
                "id": blob["id"],
                "title": blob.get("title") or blob["id"],
                "updated": blob.get("updated"),
                "last_level": blob.get("last_level"),
            }
        )
    return rows


def load_thread(thread_id: str) -> dict[str, Any] | None:
    path = _thread_path(thread_id)
    if path is None or not path.is_file():
        return None
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(blob, dict) or blob.get("id") != thread_id:
        return None
    return blob


def save_thread(thread: dict[str, Any]) -> Path:
    config.THREADS_DIR.mkdir(parents=True, exist_ok=True)
    path = _thread_path(str(thread["id"]))
    if path is None:
        raise ValueError("bad_thread_id")
    path.write_text(json.dumps(thread, indent=2), encoding="utf-8")
    return path


def vote_side(body: str | None) -> str | None:
    text = str(body or "").strip().lower()
    if not text:
        return None
    token = text.split()[0].strip(".,:;!")
    if token in {"ship", "accept", "approve"}:
        return "ship"
    if token in {"reject", "deny"}:
        return "reject"
    return None


def last_ship_votes(run: Run) -> dict[str, str]:
    last: dict[str, str] = {}
    if run.blackboard is None:
        return last
    for msg in run.blackboard.messages:
        if msg.get("kind") != "vote":
            continue
        side = vote_side(msg.get("body"))
        agent_id = msg.get("agent_id")
        if side and agent_id:
            last[str(agent_id)] = side
    return last


def protocol_bodies(run: Run, kind: str) -> list[str]:
    if run.blackboard is None:
        return []
    return [
        str(m.get("body") or "")
        for m in run.blackboard.messages
        if m.get("kind") == kind
    ]


def _thread_path(thread_id: str) -> Path | None:
    name = (thread_id or "").strip()
    if not name.startswith("thr_") or "/" in name or "\\" in name or ".." in name:
        return None
    if not name[4:].replace("_", "").isalnum():
        return None
    return config.THREADS_DIR / f"{name}.json"


def _title(text: str) -> str:
    clean = " ".join(str(text or "").split())
    return (clean or "untitled")[:80]


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _need(agent_id: str | None) -> tuple[Any, str | None]:
    if not agent_id:
        return None, None
    return store.run_for_agent(agent_id), agent_id


def _factory(tool: str, run: Run | None, agent_name: str, result: dict[str, Any]) -> dict[str, Any]:
    return logger.finish(
        event="factory",
        tool=tool,
        run_id=None if run is None else run.run_id,
        agent_name=agent_name,
        result=result,
        level=None if run is None else run.level,
        stakes=None if run is None else run.stakes,
        mail_cal=None if run is None else run.mail_cal,
    )


def _tool(tool: str, run: Any, agent_id: str | None, result: dict[str, Any], summary: str = "") -> dict[str, Any]:
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
