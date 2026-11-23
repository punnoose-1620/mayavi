"""Create, bind, wipe, and copy the jail. Agents never import this file."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import config
import store
from sandbox._support import factory, need, done

import file_tools


def create(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        return factory("createSandbox", None, "script", {"ok": False, "error": "no_run"})
    path = (config.SANDBOX_ROOT / run_id).resolve()
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    run.sandbox_path = path
    return factory("createSandbox", run, run.router_agent or "script", {"ok": True, "path": str(path)})


def delete(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        return factory("deleteSandbox", None, "script", {"ok": False, "error": "no_run"})
    kill_proc(run)
    path = run.sandbox_path
    try:
        if path is not None and path.exists():
            shutil.rmtree(path)
        run.sandbox_path = None
        return factory("deleteSandbox", run, run.router_agent or "script", {"ok": True})
    except Exception as exc:
        return factory("deleteSandbox", run, run.router_agent or "script", {"ok": False, "error": type(exc).__name__})


def bind(agent_id: str | None = None) -> dict[str, Any]:
    return openSandbox(agent_id)


def openSandbox(agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = need(agent_id)
    if run is None or run.sandbox_path is None:
        return done("openSandbox", run, agent_id, {"ok": False, "error": "no_sandbox"})
    run.agents[agent_id].sandbox_bound = True
    return done("openSandbox", run, agent_id, {"ok": True, "sandbox": str(run.sandbox_path)})


def collect_output(run: Any, wait: float = 2.0) -> None:
    """If a short script is about to exit, catch its stdout before copy-out.

    Leave long-running servers alone: a timeout here must not kill the process.
    """
    proc = getattr(run, "sandbox_proc", None)
    if proc is None:
        return
    try:
        stdout, stderr = proc.communicate(timeout=wait)
    except subprocess.TimeoutExpired:
        return
    blob = dict(getattr(run, "sandbox_results", None) or {})
    blob["stdout"] = str(blob.get("stdout") or "") + str(stdout or "")
    blob["stderr"] = str(blob.get("stderr") or "") + str(stderr or "")
    blob["exit_code"] = proc.returncode
    blob["running"] = False
    run.sandbox_results = blob
    run.sandbox_proc = None


def kill_proc(run: Any) -> None:
    proc = getattr(run, "sandbox_proc", None)
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
    run.sandbox_proc = None


def copy_out(run: Any, *, summary: str = "", agent_id: str | None = None) -> None:
    collect_output(run)
    keep = run.keep_path
    root = run.sandbox_path
    if keep is None or root is None or not root.is_dir():
        return
    keep.mkdir(parents=True, exist_ok=True)
    who = agent_id or run.router_agent
    for src in root.rglob("*"):
        if not src.is_file():
            continue
        if src.name.startswith(".") or src.suffix.lower() == ".tmp":
            continue
        if src.suffix.lower() not in config.SANDBOX_EXTENSIONS:
            continue
        rel = src.relative_to(root)
        dest = keep / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        file_tools.keep_copy(dest, src.read_bytes(), agent_id=who)
    stdout = str((run.sandbox_results or {}).get("stdout") or "")
    if stdout.strip():
        file_tools.keep_copy(keep / "result.txt", stdout.encode("utf-8"), agent_id=who)
    if summary:
        file_tools.keep_copy(keep / "SUMMARY.md", summary.encode("utf-8"), agent_id=who)


def sandbox_env(root: Path) -> dict[str, str]:
    keep = {}
    for key in ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "SYSTEMDRIVE"):
        if key in os.environ:
            keep[key] = os.environ[key]
    keep["PATH"] = os.environ.get("PATH", "")
    keep["PYTHONIOENCODING"] = "utf-8"
    keep["PYTHONDONTWRITEBYTECODE"] = "1"
    keep["TEMP"] = str(root / ".tmp")
    keep["TMP"] = str(root / ".tmp")
    keep["TMPDIR"] = str(root / ".tmp")
    return keep
