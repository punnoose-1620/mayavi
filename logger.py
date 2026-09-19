"""Daily binary audit log. Agents never see these functions."""

from __future__ import annotations

import json
import struct
import threading
import warnings
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import config

MAGIC = b"ID10"
FORMAT_VERSION = 1
_HEADER = MAGIC + struct.pack(">H", FORMAT_VERSION)
_LOCK = threading.Lock()
_MAX_SUMMARY = 240
_LISTENERS: list[Callable[[dict[str, Any]], None]] = []


def add_listener(fn: Callable[[dict[str, Any]], None]) -> None:
    """Private UI/inspector hook. Agents never call this."""
    if fn not in _LISTENERS:
        _LISTENERS.append(fn)


def remove_listener(fn: Callable[[dict[str, Any]], None]) -> None:
    try:
        _LISTENERS.remove(fn)
    except ValueError:
        return


class LogResult:
    def __init__(self, written: bool, hard_fail: bool) -> None:
        self.written = written
        self.hard_fail = hard_fail


def checkLogExists(day: datetime | None = None) -> bool:
    return _path_for(day).is_file()


def createLog(day: datetime | None = None) -> Path:
    path = _path_for(day)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        with path.open("wb") as fh:
            fh.write(_HEADER)
    return path


def writeSpawnLog(
    *,
    run_id: str,
    agent_name: str,
    model: str,
    role: str,
    parent_agent: str | None,
    level: str,
    stakes: str,
    mail_cal: str,
) -> LogResult:
    record = {
        "format_version": FORMAT_VERSION,
        "event": "spawn",
        "time": _now(),
        "run_id": run_id,
        "agent_name": agent_name,
        "model": model,
        "role": role,
        "parent_agent": parent_agent,
        "level": level,
        "stakes": stakes,
        "mail_cal": mail_cal,
    }
    return _append(record, level=level, stakes=stakes, mail_cal=mail_cal)


def writeEventLog(
    *,
    event: str,
    run_id: str,
    agent_name: str,
    tool: str,
    status: str,
    level: str | None = None,
    stakes: str | None = None,
    mail_cal: str | None = None,
    summary: str = "",
) -> LogResult:
    record = {
        "format_version": FORMAT_VERSION,
        "event": event,
        "time": _now(),
        "run_id": run_id,
        "agent_name": agent_name,
        "tool": tool,
        "status": status,
        "level": level,
        "stakes": stakes,
        "mail_cal": mail_cal,
        "summary": _cap_summary(summary),
    }
    return _append(record, level=level, stakes=stakes, mail_cal=mail_cal)


def finish(
    *,
    event: str,
    tool: str,
    run_id: str | None,
    agent_name: str | None,
    result: dict[str, Any],
    level: str | None = None,
    stakes: str | None = None,
    mail_cal: str | None = None,
    summary: str = "",
) -> dict[str, Any]:
    status = "ok" if result.get("ok") else "fail"
    if not summary:
        summary = _result_summary(result, status)
    log = writeEventLog(
        event=event,
        run_id=run_id or "none",
        agent_name=agent_name or "script",
        tool=tool,
        status=status,
        level=level,
        stakes=stakes,
        mail_cal=mail_cal,
        summary=summary,
    )
    if not log.written and log.hard_fail:
        return {"ok": False, "error": "log_write_failed"}
    return result


def read_records(path: Path | None = None) -> list[dict[str, Any]]:
    """Test/inspector helper. Not exported to agents."""
    target = path or _path_for()
    if not target.is_file():
        return []
    records: list[dict[str, Any]] = []
    with target.open("rb") as fh:
        header = fh.read(len(_HEADER))
        if header != _HEADER:
            raise ValueError("invalid log header")
        while True:
            raw_len = fh.read(4)
            if not raw_len:
                break
            if len(raw_len) < 4:
                break
            (length,) = struct.unpack(">I", raw_len)
            payload = fh.read(length)
            if len(payload) < length:
                break
            records.append(json.loads(payload.decode("utf-8")))
    return records


def _notify(record: dict[str, Any]) -> None:
    for fn in list(_LISTENERS):
        try:
            fn(record)
        except Exception:
            continue


def _path_for(day: datetime | None = None) -> Path:
    when = day or datetime.now().astimezone()
    return config.LOG_DIR / f"{when.date().isoformat()}.id10t.log"


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _cap_summary(text: str) -> str:
    text = text or ""
    if len(text) <= _MAX_SUMMARY:
        return text
    return text[: _MAX_SUMMARY - 3] + "..."


def _result_summary(result: dict[str, Any], status: str) -> str:
    if status == "ok":
        parts = []
        for key in ("path", "provider", "host", "status_code", "agent_name", "role"):
            if result.get(key) not in (None, ""):
                parts.append(f"{key}={result[key]}")
        return " ".join(parts)
    err = result.get("error") or result.get("status") or "fail"
    return str(err)


def _hard_fail(level: str | None, stakes: str | None, mail_cal: str | None) -> bool:
    if level == "large":
        return True
    if stakes == "high":
        return True
    if mail_cal in {"read", "write"}:
        return True
    return False


def _append(record: dict[str, Any], *, level: str | None, stakes: str | None, mail_cal: str | None) -> LogResult:
    payload = json.dumps(record, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    try:
        with _LOCK:
            path = createLog()
            with path.open("ab") as fh:
                fh.write(struct.pack(">I", len(payload)))
                fh.write(payload)
        _notify(record)
        return LogResult(True, False)
    except Exception as exc:
        hard = _hard_fail(level, stakes, mail_cal)
        warnings.warn(f"log write failed: {type(exc).__name__}", stacklevel=2)
        return LogResult(False, hard)
