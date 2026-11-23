"""Write files inside the jail. Agents never import this file."""

from __future__ import annotations

from typing import Any

import config
import paging
from sandbox._support import done, inside, lock, need, ready, unlock


def sandbox_write(path: str, content: str, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = need(agent_id)
    denied = ready(run, agent_id, write=True)
    if denied:
        return done("sandbox_write", run, agent_id, denied)
    if not paging.char_chunk_ok(content):
        return done("sandbox_write", run, agent_id, {"ok": False, "error": "chunk_too_large"})
    target = inside(run.sandbox_path, path)
    if target is None:
        return done("sandbox_write", run, agent_id, {"ok": False, "error": "path_denied"})
    if target.suffix.lower() not in config.SANDBOX_EXTENSIONS:
        return done("sandbox_write", run, agent_id, {"ok": False, "error": "ext_denied"})
    busy = lock(run, agent_id)
    if busy:
        return done("sandbox_write", run, agent_id, busy)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)
        return done("sandbox_write", run, agent_id, {"ok": True, "path": str(target)})
    except Exception as exc:
        return done("sandbox_write", run, agent_id, {"ok": False, "error": type(exc).__name__})
    finally:
        unlock(run, agent_id)
