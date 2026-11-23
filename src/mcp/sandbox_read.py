"""Sandbox read pack."""

from __future__ import annotations

from typing import Any

import sandbox
from mcp._util import as_int

NAME = "sandbox.read"
TOOLS = ("openSandbox", "sandbox_read", "getResultsFromSandbox")


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {
        "openSandbox": lambda **kw: sandbox.openSandbox(agent_id=aid),
        "sandbox_read": lambda **kw: sandbox.sandbox_read(
            path=str(kw.get("path") or kw.get("file") or ""),
            start=as_int(kw.get("start", 1), 1),
            end=as_int(kw.get("end", 1), 1),
            agent_id=aid,
        ),
        "getResultsFromSandbox": lambda **kw: sandbox.getResultsFromSandbox(
            start=as_int(kw.get("start", 1), 1),
            end=as_int(kw.get("end", 1), 1),
            agent_id=aid,
        ),
    }
