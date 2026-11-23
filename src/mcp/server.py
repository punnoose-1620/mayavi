"""Stdio MCP door. Mounts memory plus optional skill packs. Host-only."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


def _src_root() -> str:
    return str(Path(__file__).resolve().parent.parent)


def _project_root() -> str:
    return str(Path(__file__).resolve().parent.parent.parent)


def _mcp_keys() -> list[str]:
    return [k for k in list(sys.modules) if k == "mcp" or k.startswith("mcp.")]


def _drop_repo_path() -> list[str]:
    dropped: list[str] = []
    for key in ("", ".", _src_root(), _project_root()):
        while key in sys.path:
            sys.path.remove(key)
            dropped.append(key)
    return dropped


def _restore_path(dropped: list[str]) -> None:
    for key in reversed(dropped):
        sys.path.insert(0, key)


def _snapshot(keys: list[str]) -> dict[str, Any]:
    return {k: sys.modules[k] for k in keys if k in sys.modules}


def _replace_mcp(incoming: dict[str, Any]) -> dict[str, Any]:
    outgoing = _snapshot(_mcp_keys())
    for key in _mcp_keys():
        sys.modules.pop(key, None)
    sys.modules.update(incoming)
    return outgoing


def _pypi_fastmcp() -> tuple[Any, dict[str, Any]]:
    """Load FastMCP from the installed mcp package, not this folder."""
    local = _snapshot(_mcp_keys())
    for key in _mcp_keys():
        sys.modules.pop(key, None)
    dropped = _drop_repo_path()
    try:
        from mcp.server.fastmcp import FastMCP

        pypi = _snapshot(_mcp_keys())
        return FastMCP, pypi
    finally:
        _restore_path(dropped)
        for key in _mcp_keys():
            sys.modules.pop(key, None)
        sys.modules.update(local)


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mcp_server",
        description="Stdio MCP door. Memory always; extra packs via --packs.",
    )
    parser.add_argument(
        "--packs",
        default="",
        help="Comma-separated extra packs (web,profile,files.read,files.write) or 'all'. Jail/board/mail/git stay factory-only.",
    )
    return parser.parse_args(argv)


def _wanted_packs(raw: str) -> tuple[list[str], list[str]]:
    from mcp.registry import STDIO_PACKS
    from mcp.stdio import FACTORY_ONLY

    text = str(raw or "").strip()
    if not text:
        return [], []
    if text.lower() == "all":
        return list(STDIO_PACKS), []
    names = [part.strip() for part in text.split(",") if part.strip()]
    extra = [n for n in names if n in STDIO_PACKS]
    skipped = [n for n in names if n in FACTORY_ONLY or (n not in STDIO_PACKS and n != "memory")]
    return extra, skipped


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    extra, skipped = _wanted_packs(args.packs)
    for name in skipped:
        print(f"skipping factory-only pack: {name}", file=sys.stderr, flush=True)
    try:
        FastMCP, pypi = _pypi_fastmcp()
    except ImportError:
        print("mcp is not installed. pip install mcp", flush=True)
        return 2
    from mcp import memory as memory_pack
    from mcp import stdio as stdio_pack

    local = _replace_mcp(pypi)
    try:
        server = FastMCP("mayavi")
        server.tool()(memory_pack.list_notebooks)
        server.tool()(memory_pack.get_notebook)
        server.tool()(memory_pack.search_memory)
        server.tool()(memory_pack.read_log_span)
        stdio_pack.register(server, extra)
        server.run(transport="stdio")
    finally:
        _replace_mcp(local)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
