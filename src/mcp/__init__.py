"""Capability packs. Factory workers bind packs in-process; stdio is the extra door."""

from mcp.registry import PACKS, STDIO_PACKS, bind_named, packs_for, tools_for

__all__ = ["PACKS", "STDIO_PACKS", "bind_named", "packs_for", "tools_for"]
