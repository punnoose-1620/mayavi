"""Read jail files and last execute output. Agents never import this file."""

from __future__ import annotations

from typing import Any

import paging
from sandbox._support import done, inside, need, ready


def sandbox_read(path: str, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = need(agent_id)
    denied = ready(run, agent_id, write=False)
    if denied:
        return done("sandbox_read", run, agent_id, denied)
    target = inside(run.sandbox_path, path)
    if target is None or not target.is_file():
        return done("sandbox_read", run, agent_id, {"ok": False, "error": "not_found"})
    text = target.read_text(encoding="utf-8", errors="replace")
    chunk, s, e, total = paging.slice_chars(text, start, end)
    return done("sandbox_read", run, agent_id, {"ok": True, "text": chunk, "start": s, "end": e, "total_pages": total})


def getResultsFromSandbox(start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = need(agent_id)
    denied = ready(run, agent_id, write=False)
    if denied:
        return done("getResultsFromSandbox", run, agent_id, denied)
    if not run.sandbox_executed:
        return done("getResultsFromSandbox", run, agent_id, {"ok": False, "error": "not_run"})
    blob = run.sandbox_results or {}
    stdout = blob.get("stdout") or ""
    stderr = blob.get("stderr") or ""
    text = f"exit_code={blob.get('exit_code')}\nrunning={blob.get('running')}\n-- stdout --\n{stdout}\n-- stderr --\n{stderr}"
    chunk, s, e, total = paging.slice_chars(text, start, end)
    return done(
        "getResultsFromSandbox",
        run,
        agent_id,
        {
            "ok": True,
            "exit_code": blob.get("exit_code"),
            "running": blob.get("running"),
            "text": chunk,
            "start": s,
            "end": e,
            "total_pages": total,
        },
    )
