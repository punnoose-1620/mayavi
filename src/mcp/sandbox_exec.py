"""Sandbox execute pack. Tester / executor only — host still enforces role_denied."""

from __future__ import annotations

from typing import Any

import sandbox
from mcp._util import as_int, exec_timeout

NAME = "sandbox.exec"
TOOLS = ("executeScriptInSandbox", "sandbox_fetch")


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {
        "executeScriptInSandbox": lambda **kw: sandbox.executeScriptInSandbox(
            path=str(kw.get("path") or kw.get("file") or ""),
            timeout=exec_timeout(kw.get("timeout")),
            agent_id=aid,
        ),
        "sandbox_fetch": lambda **kw: sandbox.sandbox_fetch(
            url=str(kw.get("url") or ""),
            method=str(kw.get("method") or "GET"),
            body=kw.get("body"),
            start=as_int(kw.get("start", 1), 1),
            end=as_int(kw.get("end", 1), 1),
            agent_id=aid,
        ),
    }
