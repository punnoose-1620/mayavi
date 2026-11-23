"""Run a jail script or fetch its loopback HTTP. Agents never import this file."""

from __future__ import annotations

import subprocess
import sys
from typing import Any
from urllib.parse import urlparse

import requests

import blackboard
import config
from sandbox._support import (
    FETCH_METHODS,
    done,
    exec_roles,
    inside,
    lock,
    need,
    ready,
    unlock,
)
from sandbox.jail import kill_proc, sandbox_env


def executeScriptInSandbox(path: str, timeout: int | None = None, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = need(agent_id)
    denied = ready(run, agent_id, write=False)
    if denied:
        return done("executeScriptInSandbox", run, agent_id, denied)
    if run.agents[agent_id].role not in exec_roles(run):
        return done("executeScriptInSandbox", run, agent_id, {"ok": False, "error": "role_denied"})
    target = inside(run.sandbox_path, path)
    if target is None or target.suffix.lower() != ".py":
        return done("executeScriptInSandbox", run, agent_id, {"ok": False, "error": "not_python"})
    busy = lock(run, agent_id)
    if busy:
        return done("executeScriptInSandbox", run, agent_id, busy)
    try:
        kill_proc(run)
        env = sandbox_env(run.sandbox_path)
        (run.sandbox_path / ".tmp").mkdir(exist_ok=True)
        proc = subprocess.Popen(
            [sys.executable, "-u", str(target)],
            cwd=str(run.sandbox_path),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        limit = timeout or config.EXECUTE_TIMEOUT
        startup = min(3.0, float(limit))
        try:
            stdout, stderr = proc.communicate(timeout=startup)
            running = False
        except subprocess.TimeoutExpired:
            if limit <= startup:
                proc.kill()
                stdout, stderr = proc.communicate()
                running = False
            else:
                run.sandbox_proc = proc
                stdout, stderr = "", ""
                running = True
        code = None if running else proc.returncode
        run.sandbox_results = {
            "exit_code": code,
            "stdout": stdout[-8000:],
            "stderr": stderr[-8000:],
            "running": running,
            "path": str(target),
        }
        run.sandbox_executed = True
        return done(
            "executeScriptInSandbox",
            run,
            agent_id,
            {"ok": True, "exit_code": code, "running": running},
            summary=f"exit={code} running={running}",
        )
    except Exception as exc:
        run.sandbox_results = {
            "exit_code": None,
            "stdout": "",
            "stderr": type(exc).__name__,
            "running": False,
            "path": str(target),
        }
        return done("executeScriptInSandbox", run, agent_id, {"ok": False, "error": type(exc).__name__})
    finally:
        blackboard.send_message(_debug_body(run.sandbox_results), "debug", agent_id=agent_id, factory=False)
        unlock(run, agent_id)


def sandbox_fetch(url: str, method: str = "GET", body: str | None = None, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = need(agent_id)
    denied = ready(run, agent_id, write=False)
    if denied:
        return done("sandbox_fetch", run, agent_id, denied)
    if run.agents[agent_id].role not in exec_roles(run):
        return done("sandbox_fetch", run, agent_id, {"ok": False, "error": "role_denied"})
    verb = str(method or "GET").strip().upper()
    if verb not in FETCH_METHODS:
        return done("sandbox_fetch", run, agent_id, {"ok": False, "error": "method_denied"})
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return done("sandbox_fetch", run, agent_id, {"ok": False, "error": "not_loopback"})
    busy = lock(run, agent_id)
    if busy:
        return done("sandbox_fetch", run, agent_id, busy)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        import paging

        resp = requests.request(
            verb,
            url,
            data=body,
            timeout=config.FETCH_TIMEOUT,
            allow_redirects=False,
        )
        text = resp.text
        chunk, s, e, total = paging.slice_chars(text, start, end)
        result = {
            "ok": True,
            "status_code": resp.status_code,
            "text": chunk,
            "start": s,
            "end": e,
            "total_pages": total,
            "host": host,
            "port": port,
        }
        return done(
            "sandbox_fetch",
            run,
            agent_id,
            result,
            summary=f"host={host} port={port} status={resp.status_code}",
        )
    except Exception as exc:
        return done(
            "sandbox_fetch",
            run,
            agent_id,
            {"ok": False, "error": type(exc).__name__, "host": host, "port": port},
            summary=f"host={host} port={port} fail",
        )
    finally:
        unlock(run, agent_id)


def _debug_body(results: dict[str, Any]) -> str:
    stdout = (results.get("stdout") or "")[-400:]
    stderr = (results.get("stderr") or "")[-400:]
    return f"exit_code={results.get('exit_code')} running={results.get('running')}\n{stdout}\n{stderr}"
