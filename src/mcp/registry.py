"""Host pack catalog. Agents never import this file.

Selectors decide which packs exist on a run. Role tables decide which of those
packs a worker sees. Factory workers bind packs in-process; they do not speak MCP.
"""

from __future__ import annotations

from typing import Any, Callable

from mcp._util import mail_manager, ops_needed, writers_open
from store import Agent, Run

PACKS = (
    "web",
    "files.read",
    "files.write",
    "sandbox.read",
    "sandbox.write",
    "sandbox.exec",
    "profile",
    "mail",
    "calendar",
    "git",
    "board.live",
    "board.committee",
)

# Stdio may mount these without a live factory run. Jail/board stay factory-only.
STDIO_PACKS = ("web", "files.read", "files.write", "profile")

BINDERS: dict[str, str] = {
    "web": "mcp.web:bind",
    "files.read": "mcp.files:bind_read",
    "files.write": "mcp.files:bind_write",
    "sandbox.read": "mcp.sandbox_read:bind",
    "sandbox.write": "mcp.sandbox_write:bind",
    "sandbox.exec": "mcp.sandbox_exec:bind",
    "profile": "mcp.profile:bind",
    "mail": "mcp.mail:bind",
    "calendar": "mcp.calendar:bind",
    "git": "mcp.git:bind",
    "board.live": "mcp.board:bind_live",
    "board.committee": "mcp.board:bind_committee",
}


def run_packs(run: Run) -> set[str]:
    out: set[str] = set()
    if ops_needed(run.file_ops):
        out.add("files.read")
        if writers_open(run) and not run.summarize_keep:
            out.add("files.write")
    if run.web:
        out.add("web")
    if run.level in {"medium", "large"}:
        out.add("board.live")
    if run.coding and not run.summarize_keep:
        out.update({"sandbox.read", "sandbox.write", "sandbox.exec"})
    if run.committee is not None:
        out.add("board.committee")
    if run.git_remote:
        out.add("git")
    if run.gmail:
        out.add("mail")
    if run.calendar:
        out.add("calendar")
    if getattr(run, "job", False) or getattr(run, "update_profile", False) or str(run.shape or "") in {"job", "profile"}:
        out.add("profile")
    return out


def packs_for(run: Run, agent: Agent) -> list[str]:
    available = run_packs(run)
    if run.committee is not None:
        from coding.roster import ROLE_PACKS

        wanted = ROLE_PACKS.get(agent.role, tuple(sorted(available)))
        return [name for name in wanted if name in available]
    chosen: list[str] = []
    for name in sorted(available):
        if name == "sandbox.write" and agent.role not in {"builder", "coder"}:
            continue
        if name == "sandbox.exec" and agent.role not in {"executor", "tester"}:
            continue
        if name in {"mail", "calendar"} and not mail_manager(run, agent):
            continue
        if name == "git":
            continue
        chosen.append(name)
    return chosen


def tools_for(run: Run, agent: Agent) -> dict[str, Callable[..., Any]]:
    return bind_named(packs_for(run, agent), run, agent)


def bind_named(names: list[str] | tuple[str, ...], run: Run, agent: Agent) -> dict[str, Callable[..., Any]]:
    tools: dict[str, Callable[..., Any]] = {}
    for name in names:
        bind = _binder(name)
        if bind is None:
            continue
        tools.update(bind(run, agent))
    return tools


def _binder(name: str):
    spec = BINDERS.get(name)
    if not spec:
        return None
    mod_name, func_name = spec.split(":")
    import importlib

    mod = importlib.import_module(mod_name)
    return getattr(mod, func_name)
