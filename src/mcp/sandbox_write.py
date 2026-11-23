"""Sandbox write pack. Coder / builder only — host still enforces role_denied."""

from __future__ import annotations

from typing import Any

import sandbox

NAME = "sandbox.write"
TOOLS = ("sandbox_write",)


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {
        "sandbox_write": lambda **kw: sandbox.sandbox_write(
            path=str(kw.get("path") or kw.get("file") or kw.get("filename") or ""),
            content=str(kw.get("content") or kw.get("text") or kw.get("code") or ""),
            agent_id=aid,
        )
    }
