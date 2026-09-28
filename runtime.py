"""Committee/runtime tools. Agents never see executor.py."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

import blackboard
import config
import logger
import paging
import store

FETCH_METHODS = {"GET", "POST"}


def viewSessionDetails(agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    if run is None:
        return _done("viewSessionDetails", run, agent_id, {"ok": False, "error": "no_run"})
    if run.session_path is None or not run.session_path.is_file():
        return _done("viewSessionDetails", run, agent_id, {"ok": False, "error": "no_session"})
    data = json.loads(run.session_path.read_text(encoding="utf-8"))
    data.pop("session_ids", None)
    data.pop("tokens", None)
    data["ok"] = True
    return _done("viewSessionDetails", run, agent_id, data)


def sendMessageToBlackboard(body: str, kind: str, agent_id: str | None = None, factory: bool = False) -> dict[str, Any]:
    return blackboard.send_message(body, kind, agent_id=agent_id, factory=factory)


def viewBlackboardMessages(n: int = 20, agent_id: str | None = None) -> dict[str, Any]:
    return blackboard.view_messages(n=n, agent_id=agent_id)


def openSandbox(agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    if run is None or run.level != "large" or run.sandbox_path is None:
        return _done("openSandbox", run, agent_id, {"ok": False, "error": "no_sandbox"})
    run.agents[agent_id].sandbox_bound = True
    return _done("openSandbox", run, agent_id, {"ok": True, "sandbox": str(run.sandbox_path)})


def sandbox_write(path: str, content: str, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    denied = _sandbox_ready(run, agent_id, write=True)
    if denied:
        return _done("sandbox_write", run, agent_id, denied)
    if not paging.char_chunk_ok(content):
        return _done("sandbox_write", run, agent_id, {"ok": False, "error": "chunk_too_large"})
    target = _inside(run.sandbox_path, path)
    if target is None:
        return _done("sandbox_write", run, agent_id, {"ok": False, "error": "path_denied"})
    if target.suffix.lower() not in config.SANDBOX_EXTENSIONS:
        return _done("sandbox_write", run, agent_id, {"ok": False, "error": "ext_denied"})
    busy = _lock(run, agent_id)
    if busy:
        return _done("sandbox_write", run, agent_id, busy)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)
        return _done("sandbox_write", run, agent_id, {"ok": True, "path": str(target)})
    except Exception as exc:
        return _done("sandbox_write", run, agent_id, {"ok": False, "error": type(exc).__name__})
    finally:
        _unlock(run, agent_id)


def sandbox_read(path: str, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    denied = _sandbox_ready(run, agent_id, write=False)
    if denied:
        return _done("sandbox_read", run, agent_id, denied)
    target = _inside(run.sandbox_path, path)
    if target is None or not target.is_file():
        return _done("sandbox_read", run, agent_id, {"ok": False, "error": "not_found"})
    text = target.read_text(encoding="utf-8", errors="replace")
    chunk, s, e, total = paging.slice_chars(text, start, end)
    return _done("sandbox_read", run, agent_id, {"ok": True, "text": chunk, "start": s, "end": e, "total_pages": total})


def executeScriptInSandbox(path: str, timeout: int | None = None, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    denied = _sandbox_ready(run, agent_id, write=False)
    if denied:
        return _done("executeScriptInSandbox", run, agent_id, denied)
    if run.agents[agent_id].role not in _exec_roles(run):
        return _done("executeScriptInSandbox", run, agent_id, {"ok": False, "error": "role_denied"})
    target = _inside(run.sandbox_path, path)
    if target is None or target.suffix.lower() != ".py":
        return _done("executeScriptInSandbox", run, agent_id, {"ok": False, "error": "not_python"})
    busy = _lock(run, agent_id)
    if busy:
        return _done("executeScriptInSandbox", run, agent_id, busy)
    try:
        _kill_sandbox_proc(run)
        env = _sandbox_env(run.sandbox_path)
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
        return _done(
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
        return _done("executeScriptInSandbox", run, agent_id, {"ok": False, "error": type(exc).__name__})
    finally:
        # The committee must see every run, including one that never started.
        sendMessageToBlackboard(_debug_body(run.sandbox_results), "debug", agent_id=agent_id)
        _unlock(run, agent_id)


def sandbox_fetch(url: str, method: str = "GET", body: str | None = None, start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    denied = _sandbox_ready(run, agent_id, write=False)
    if denied:
        return _done("sandbox_fetch", run, agent_id, denied)
    if run.agents[agent_id].role not in _exec_roles(run):
        return _done("sandbox_fetch", run, agent_id, {"ok": False, "error": "role_denied"})
    verb = str(method or "GET").strip().upper()
    if verb not in FETCH_METHODS:
        return _done("sandbox_fetch", run, agent_id, {"ok": False, "error": "method_denied"})
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost"}:
        return _done("sandbox_fetch", run, agent_id, {"ok": False, "error": "not_loopback"})
    busy = _lock(run, agent_id)
    if busy:
        return _done("sandbox_fetch", run, agent_id, busy)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
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
        return _done(
            "sandbox_fetch",
            run,
            agent_id,
            result,
            summary=f"host={host} port={port} status={resp.status_code}",
        )
    except Exception as exc:
        return _done(
            "sandbox_fetch",
            run,
            agent_id,
            {"ok": False, "error": type(exc).__name__, "host": host, "port": port},
            summary=f"host={host} port={port} fail",
        )
    finally:
        _unlock(run, agent_id)


def getResultsFromSandbox(start: int = 1, end: int = 1, agent_id: str | None = None) -> dict[str, Any]:
    run, agent_id = _need(agent_id)
    denied = _sandbox_ready(run, agent_id, write=False)
    if denied:
        return _done("getResultsFromSandbox", run, agent_id, denied)
    if not run.sandbox_executed:
        return _done("getResultsFromSandbox", run, agent_id, {"ok": False, "error": "not_run"})
    blob = run.sandbox_results or {}
    stdout = blob.get("stdout") or ""
    stderr = blob.get("stderr") or ""
    text = f"exit_code={blob.get('exit_code')}\nrunning={blob.get('running')}\n-- stdout --\n{stdout}\n-- stderr --\n{stderr}"
    chunk, s, e, total = paging.slice_chars(text, start, end)
    return _done(
        "getResultsFromSandbox",
        run,
        agent_id,
        {
            "ok": True,
            "exit_code": blob.get("exit_code"),
            "running": blob.get("running"),
            "text": chunk,
            "start": s,
            "end": e,
            "total_pages": total,
        },
    )


def _need(agent_id: str | None) -> tuple[Any, str | None]:
    if not agent_id:
        return None, None
    return store.run_for_agent(agent_id), agent_id


def _sandbox_ready(run: Any, agent_id: str | None, *, write: bool) -> dict[str, Any] | None:
    if run is None or run.level != "large" or run.sandbox_path is None:
        return {"ok": False, "error": "no_sandbox"}
    if agent_id not in run.agents:
        return {"ok": False, "error": "no_agent"}
    if not run.agents[agent_id].sandbox_bound:
        return {"ok": False, "error": "not_bound"}
    if write and run.agents[agent_id].role not in _write_roles(run):
        return {"ok": False, "error": "role_denied"}
    return None


def _write_roles(run: Any) -> set[str]:
    if getattr(run, "committee", None) is not None:
        return {"coder"}
    return {"builder"}


def _exec_roles(run: Any) -> set[str]:
    if getattr(run, "committee", None) is not None:
        return {"tester"}
    return {"executor"}


def _inside(root: Path, rel: str) -> Path | None:
    rel = _sandbox_rel(rel)
    if not rel or ".." in Path(rel).parts:
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _sandbox_rel(rel: str) -> str:
    text = str(rel or "").strip().replace("\\", "/")
    if not text:
        return ""
    raw = Path(text)
    if raw.is_absolute() or (raw.parts and ":" in raw.parts[0]):
        text = raw.name
        raw = Path(text)
    skip = {"outputs", "output", "sandbox", "sandboxes"}
    parts = [part for part in raw.parts if part.lower() not in skip]
    name = "/".join(parts)
    suffix = Path(name).suffix.lower()
    if name and suffix not in config.SANDBOX_EXTENSIONS and suffix == "":
        name = f"{name}.py"
    return name


def _lock(run: Any, agent_id: str) -> dict[str, Any] | None:
    if not run.exclusive_lock.acquire(blocking=False):
        return {"ok": False, "busy": True, "agent_id": run.exclusive_holder}
    run.exclusive_holder = agent_id
    return None


def _unlock(run: Any, agent_id: str) -> None:
    if run.exclusive_holder == agent_id:
        run.exclusive_holder = None
        try:
            run.exclusive_lock.release()
        except RuntimeError:
            pass


def collect_sandbox_output(run: Any, wait: float = 2.0) -> None:
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


def _kill_sandbox_proc(run: Any) -> None:
    proc = run.sandbox_proc
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
    run.sandbox_proc = None


def _sandbox_env(root: Path) -> dict[str, str]:
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


def _debug_body(results: dict[str, Any]) -> str:
    stdout = (results.get("stdout") or "")[-400:]
    stderr = (results.get("stderr") or "")[-400:]
    return f"exit_code={results.get('exit_code')} running={results.get('running')}\n{stdout}\n{stderr}"


def _done(tool: str, run: Any, agent_id: str | None, result: dict[str, Any], summary: str = "") -> dict[str, Any]:
    return logger.finish(
        event="tool",
        tool=tool,
        run_id=None if run is None else run.run_id,
        agent_name=agent_id,
        result=result,
        level=None if run is None else run.level,
        stakes=None if run is None else run.stakes,
        mail_cal=None if run is None else run.mail_cal,
        summary=summary,
    )
