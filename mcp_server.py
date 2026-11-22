"""Stdio MCP door for device-scoped memory. Host-only; agents never import this.

Tools: list_notebooks, get_notebook, search_memory, read_log_span.
Every call requires a device id. Job / coding / web skill packs are not here.
"""

from __future__ import annotations

import json
from typing import Any

import blackboard
import memory
import tenant


def _device(raw: str) -> str:
    did = tenant.parse_device_id(raw)
    if not did:
        raise ValueError("missing_device")
    return did


def list_notebooks(device: str) -> str:
    try:
        did = _device(device)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    rows = memory.list_notebooks(did)
    return json.dumps({"ok": True, "device": did, "notebooks": rows}, ensure_ascii=False)


def get_notebook(device: str, workbook: str) -> str:
    try:
        did = _device(device)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    blob = memory.get_notebook(did, workbook)
    if blob is None:
        return json.dumps({"ok": False, "error": "not_found", "device": did}, ensure_ascii=False)
    return json.dumps(
        {
            "ok": True,
            "device": did,
            "workbook": blob.get("id"),
            "card": blackboard.context_card(blob),
            "title": blob.get("title") or "",
            "updated": blob.get("updated") or "",
        },
        ensure_ascii=False,
    )


def search_memory(device: str, query: str, workbook: str = "") -> str:
    try:
        did = _device(device)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    hits = memory.search_memory(did, query, workbook=workbook)
    return json.dumps({"ok": True, "device": did, "hits": hits}, ensure_ascii=False)


def read_log_span(device: str, workbook: str = "", n: int = 20) -> str:
    try:
        did = _device(device)
    except ValueError as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    rows = memory.read_log_span(did, workbook=workbook, n=n)
    return json.dumps({"ok": True, "device": did, "turns": rows}, ensure_ascii=False)


def _mcp() -> Any:
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("mayavi-memory")
    server.tool()(list_notebooks)
    server.tool()(get_notebook)
    server.tool()(search_memory)
    server.tool()(read_log_span)
    return server


def main() -> int:
    try:
        server = _mcp()
    except ImportError:
        print("mcp is not installed. pip install mcp", flush=True)
        return 2
    server.run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
