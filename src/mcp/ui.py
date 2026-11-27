"""UI/UX search pack for the coding committee. Read-only. No cloud model."""

from __future__ import annotations

from typing import Any

import logger
from coding import ui_skill


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name

    def ui_guide(**kw: Any) -> dict[str, Any]:
        result = ui_skill.lookup(
            str(kw.get("query") or ""),
            str(kw.get("mode") or "system"),
            str(kw.get("domain") or ""),
        )
        summary = "missing" if not result.get("ok") else f"mode={result.get('mode')} chars={len(str(result.get('guide') or ''))}"
        return logger.finish(
            event="tool",
            tool="ui_guide",
            run_id=run.run_id,
            agent_name=aid,
            result=result,
            level=run.level,
            stakes=run.stakes,
            mail_cal=run.mail_cal,
            summary=summary,
        )

    return {"ui_guide": ui_guide}
