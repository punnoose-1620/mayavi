"""Live blackboard + coding committee board packs."""

from __future__ import annotations

from typing import Any

import logger
import runtime
from mcp._util import as_int

LIVE_TOOLS = ("viewSessionDetails", "sendMessageToBlackboard", "viewBlackboardMessages")
COMMITTEE_TOOLS = ("updateBoard", "viewCommitteeBoard", "callVote")


def bind_live(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {
        "viewSessionDetails": lambda **kw: runtime.viewSessionDetails(agent_id=aid),
        "sendMessageToBlackboard": lambda **kw: runtime.sendMessageToBlackboard(
            str(kw.get("body") or kw.get("message") or kw.get("text") or kw.get("content") or ""),
            str(kw.get("kind") or "critique"),
            agent_id=aid,
        ),
        "viewBlackboardMessages": lambda **kw: runtime.viewBlackboardMessages(
            n=as_int(kw.get("n", kw.get("count", 20)), 20),
            agent_id=aid,
        ),
    }


def bind_committee(run: Any, agent: Any) -> dict[str, Any]:
    tools = {
        "updateBoard": lambda **kw: _update(run, agent, kw),
        "viewCommitteeBoard": lambda **kw: _view(run, agent, kw),
    }
    if agent.role == "manager":
        tools["callVote"] = lambda **kw: _vote(run, agent)
    return tools


def _update(run: Any, agent: Any, kw: dict[str, Any]) -> dict[str, Any]:
    from coding import board as coding_board

    if run.committee is None:
        return _tool("updateBoard", run, agent, {"ok": False, "error": "no_board"})
    section = str(kw.get("section") or kw.get("kind") or "")
    content = kw.get("content") if "content" in kw else kw.get("body") or kw.get("text")
    result = coding_board.apply_update(run.committee, agent.role, section, content)
    return _tool("updateBoard", run, agent, result)


def _view(run: Any, agent: Any, kw: dict[str, Any]) -> dict[str, Any]:
    from coding import board as coding_board

    if run.committee is None:
        return _tool("viewCommitteeBoard", run, agent, {"ok": False, "error": "no_board"})
    pages = coding_board.view_pages(agent.role, run.committee)
    total = len(pages) or 1
    chunk = max(1, min(as_int(kw.get("chunk", kw.get("n", 1)), 1), total))
    return _tool(
        "viewCommitteeBoard",
        run,
        agent,
        {"ok": True, "chunk": chunk, "total": len(pages), "view": pages[chunk - 1] if pages else ""},
    )


def _vote(run: Any, agent: Any) -> dict[str, Any]:
    if run.committee is None or agent.role != "manager":
        return _tool("callVote", run, agent, {"ok": False, "error": "role_denied"})
    run.committee.vote_open = True
    return _tool("callVote", run, agent, {"ok": True, "vote_open": True})


def _tool(name: str, run: Any, agent: Any, result: dict[str, Any]) -> dict[str, Any]:
    return logger.finish(
        event="tool",
        tool=name,
        run_id=run.run_id,
        agent_name=agent.agent_name,
        result=result,
        level=run.level,
        stakes=run.stakes,
        mail_cal=run.mail_cal,
    )
