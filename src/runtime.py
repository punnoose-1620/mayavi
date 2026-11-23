"""Live board and session tools. Agents never see executor.py.

Sandbox primitives live in the sandbox package. This module re-exports them
so existing factory call sites keep working.
"""

from __future__ import annotations

import json
from typing import Any

import blackboard
import logger
import store
from sandbox import (
    _kill_sandbox_proc,
    collect_sandbox_output,
    executeScriptInSandbox,
    getResultsFromSandbox,
    openSandbox,
    sandbox_fetch,
    sandbox_read,
    sandbox_write,
)

FETCH_METHODS = {"GET", "POST"}


def viewSessionDetails(agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    if run is None:
        return _done("viewSessionDetails", run, agent_id, {"ok": False, "error": "no_run"})
    if run.session_path is None or not run.session_path.is_file():
        return _done("viewSessionDetails", run, agent_id, {"ok": False, "error": "no_session"})
    data = json.loads(run.session_path.read_text(encoding="utf-8"))
    data.pop("session_ids", None)
    data.pop("tokens", None)
    data["ok"] = True
    return _done("viewSessionDetails", run, agent_id, data)


def sendMessageToBlackboard(body: str, kind: str, agent_id: str | None = None, factory: bool = False) -> dict[str, Any]:
    return blackboard.send_message(body, kind, agent_id=agent_id, factory=factory)


def viewBlackboardMessages(n: int = 20, agent_id: str | None = None) -> dict[str, Any]:
    return blackboard.view_messages(n=n, agent_id=agent_id)


def _need(agent_id: str | None) -> tuple[Any, str | None]:
    if not agent_id:
        return None, None
    return store.run_for_agent(agent_id), agent_id


def _done(tool: str, run: Any, agent_id: str | None, result: dict[str, Any], summary: str = "") -> dict[str, Any]:
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
