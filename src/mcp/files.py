"""Workspace file tools. Split into files.read and files.write at bind time."""

from __future__ import annotations

from typing import Any

import file_tools

READ_TOOLS = ("search_dir", "read_file")
WRITE_TOOLS = ("write_doc", "write_pdf", "write_json", "append_file", "mkdir", "write_file")


def bind_read(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {
        "search_dir": lambda **kw: file_tools.search_dir(agent_id=aid, **kw),
        "read_file": lambda **kw: file_tools.read_file(agent_id=aid, **kw),
    }


def bind_write(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    tools = {
        "write_doc": lambda **kw: file_tools.write_doc(agent_id=aid, **kw),
        "write_pdf": lambda **kw: file_tools.write_pdf(agent_id=aid, **kw),
        "write_json": lambda **kw: file_tools.write_json(agent_id=aid, **kw),
        "append_file": lambda **kw: file_tools.append_file(agent_id=aid, **kw),
        "mkdir": lambda **kw: file_tools.mkdir(agent_id=aid, **kw),
    }
    tools["write_file"] = tools["write_doc"]
    return tools
