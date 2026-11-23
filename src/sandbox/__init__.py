"""Sandbox jail. Agents never import this package.

Create / bind / read / write / exec live here so coding and other tasks can
mount the same primitives. The factory opens the jail; agents do not.
"""

from sandbox.execute import executeScriptInSandbox, sandbox_fetch
from sandbox.jail import (
    bind,
    collect_output,
    copy_out,
    create,
    delete,
    kill_proc,
    openSandbox,
)
from sandbox.read import getResultsFromSandbox, sandbox_read
from sandbox.write import sandbox_write

# Names the factory and MCP packs already use.
collect_sandbox_output = collect_output
_kill_sandbox_proc = kill_proc

__all__ = [
    "bind",
    "collect_output",
    "collect_sandbox_output",
    "copy_out",
    "create",
    "delete",
    "executeScriptInSandbox",
    "getResultsFromSandbox",
    "kill_proc",
    "openSandbox",
    "sandbox_fetch",
    "sandbox_read",
    "sandbox_write",
    "_kill_sandbox_proc",
]
