"""Web search / fetch pack."""

from __future__ import annotations

from typing import Any

import web_scrape

NAME = "web"
TOOLS = ("search_web", "get_url", "post_url", "resetSession")


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {
        "search_web": lambda **kw: web_scrape.search_web(agent_id=aid, **kw),
        "get_url": lambda **kw: web_scrape.get_url(agent_id=aid, **kw),
        "post_url": lambda **kw: web_scrape.post_url(agent_id=aid, **kw),
        "resetSession": lambda **kw: web_scrape.resetSession(agent_id=aid, **kw),
    }
