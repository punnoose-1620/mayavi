"""Keep-folder git pack. Manager + valid GitHub URL only."""

from __future__ import annotations

from typing import Any

import git_tools

NAME = "git"
TOOLS = ("git_login",)


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {
        "git_login": lambda **kw: git_tools.git_login(
            repo_url=kw.get("repo_url") or getattr(run, "git_remote", None),
            agent_id=aid,
        )
    }
