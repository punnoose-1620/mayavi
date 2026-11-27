"""Code-map pack for the coder and the critique. Read-only. No cloud model."""

from __future__ import annotations

from typing import Any

import config
import logger
from coding import code_graph as graph


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name

    def code_graph(**kw: Any) -> dict[str, Any]:
        cache = config.DATA_DIR / "code-graph" / run.run_id
        result = graph.ask(str(kw.get("query") or ""), run.sandbox_path, cache)
        summary = "missing" if not result.get("ok") else f"chars={len(str(result.get('answer') or ''))}"
        return logger.finish(
            event="tool",
            tool="code_graph",
            run_id=run.run_id,
            agent_name=aid,
            result=result,
            level=run.level,
            stakes=run.stakes,
            mail_cal=run.mail_cal,
            summary=summary,
        )

    return {"code_graph": code_graph}
