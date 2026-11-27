"""Closed coding committee roster. Agents never import this file.

The host spawns these six roles. The manager does not invent roles or packs.
"""

from __future__ import annotations

from typing import Any

from store import Run

ROLES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("manager", "manage", ("builder_qwen", "builder_llama", "executor")),
    ("coder", "code", ("executor", "builder_coder", "builder_qwen")),
    ("tester", "test", ("router", "builder_llama", "executor")),
    ("critique", "critique", ("builder_gemma", "builder_llama", "builder_qwen")),
    ("evaluator", "evaluate", ("router", "builder_llama")),
    ("documenter", "document", ("builder_llama", "builder_qwen", "router")),
)

# Packs each role may see, intersected with what the run actually mounted.
ROLE_PACKS: dict[str, tuple[str, ...]] = {
    "manager": ("board.live", "board.committee", "ui", "git", "web", "mail", "calendar"),
    "coder": ("sandbox.read", "sandbox.write", "board.live", "board.committee", "ui", "code_graph"),
    "tester": ("sandbox.read", "sandbox.exec", "board.live", "board.committee", "ui"),
    "critique": ("sandbox.read", "board.live", "board.committee", "ui", "code_graph"),
    "evaluator": ("board.live", "board.committee", "ui"),
    "documenter": ("sandbox.read", "board.live", "board.committee", "ui"),
}


def spawn(run: Run) -> dict[str, str]:
    import executor
    import models

    names: dict[str, str] = {}
    for role, use, fallbacks in ROLES:
        created = executor.createAgent(
            run.run_id,
            role,
            models.pick_role(use, fallbacks),
            parent_agent=run.router_agent,
        )
        names[role] = created["agent_name"]
    return names
