"""Shared jail helpers. Agents never import this file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import config
import logger
import store

FETCH_METHODS = {"GET", "POST"}


def need(agent_id: str | None) -> tuple[Any, str | None]:
    if not agent_id:
        return None, None
    return store.run_for_agent(agent_id), agent_id


def done(tool: str, run: Any, agent_id: str | None, result: dict[str, Any], summary: str = "") -> dict[str, Any]:
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


def factory(tool: str, run: Any, agent_name: str, result: dict[str, Any]) -> dict[str, Any]:
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


def ready(run: Any, agent_id: str | None, *, write: bool) -> dict[str, Any] | None:
    if run is None or run.sandbox_path is None:
        return {"ok": False, "error": "no_sandbox"}
    if agent_id not in run.agents:
        return {"ok": False, "error": "no_agent"}
    if not run.agents[agent_id].sandbox_bound:
        return {"ok": False, "error": "not_bound"}
    if write and run.agents[agent_id].role not in write_roles(run):
        return {"ok": False, "error": "role_denied"}
    return None


def write_roles(run: Any) -> set[str]:
    if getattr(run, "committee", None) is not None:
        return {"coder"}
    return {"builder"}


def exec_roles(run: Any) -> set[str]:
    if getattr(run, "committee", None) is not None:
        return {"tester"}
    return {"executor"}


def inside(root: Path, rel: str) -> Path | None:
    rel = sandbox_rel(rel)
    if not rel or ".." in Path(rel).parts:
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def sandbox_rel(rel: str) -> str:
    text = str(rel or "").strip().replace("\\", "/")
    if not text:
        return ""
    raw = Path(text)
    if raw.is_absolute() or (raw.parts and ":" in raw.parts[0]):
        text = raw.name
        raw = Path(text)
    skip = {"outputs", "output", "sandbox", "sandboxes", "runtime", "input"}
    parts = [part for part in raw.parts if part.lower() not in skip]
    name = "/".join(parts)
    suffix = Path(name).suffix.lower()
    if name and suffix not in config.SANDBOX_EXTENSIONS and suffix == "":
        name = f"{name}.py"
    return name


def lock(run: Any, agent_id: str) -> dict[str, Any] | None:
    if not run.exclusive_lock.acquire(blocking=False):
        return {"ok": False, "busy": True, "agent_id": run.exclusive_holder}
    run.exclusive_holder = agent_id
    return None


def unlock(run: Any, agent_id: str) -> None:
    if run.exclusive_holder == agent_id:
        run.exclusive_holder = None
        try:
            run.exclusive_lock.release()
        except RuntimeError:
            pass
