"""Durable operator profile board. Agents never import this file."""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

KEYS = ("name", "role", "skills", "education", "links")
LIST_KEYS = frozenset({"skills", "education", "links"})
_MAX_STR = {"name": 80, "role": 120}
_MAX_ITEM = 80
_MAX_LINK = 200
_MAX_LIST = 12
_LOCK = threading.Lock()


def profile_path() -> Path:
    return config.DATA_DIR / "profile.json"


def empty_board() -> dict[str, Any]:
    return {
        "name": "",
        "role": "",
        "skills": [],
        "education": [],
        "links": [],
        "updated": "",
        "applied_runs": [],
    }


def load() -> dict[str, Any]:
    path = profile_path()
    if not path.is_file():
        return empty_board()
    try:
        blob = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return empty_board()
    if not isinstance(blob, dict):
        return empty_board()
    board = empty_board()
    board["name"] = str(blob.get("name") or "")[: _MAX_STR["name"]]
    board["role"] = str(blob.get("role") or "")[: _MAX_STR["role"]]
    for key in LIST_KEYS:
        board[key] = _as_list(blob.get(key), link=(key == "links"))
    runs = blob.get("applied_runs") or []
    if isinstance(runs, list):
        board["applied_runs"] = [str(item) for item in runs if str(item).strip()][-200:]
    board["updated"] = str(blob.get("updated") or "")
    return board


def save(board: dict[str, Any]) -> None:
    path = profile_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": str(board.get("name") or "")[: _MAX_STR["name"]],
        "role": str(board.get("role") or "")[: _MAX_STR["role"]],
        "skills": _as_list(board.get("skills")),
        "education": _as_list(board.get("education")),
        "links": _as_list(board.get("links"), link=True),
        "updated": str(board.get("updated") or ""),
        "applied_runs": [str(item) for item in (board.get("applied_runs") or []) if str(item).strip()][-200:],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize(raw: Any) -> dict[str, Any] | None:
    """Closed schema. Empty or unknown keys are dropped. Never guesses from prose."""
    if not isinstance(raw, dict):
        return None
    out: dict[str, Any] = {}
    name = str(raw.get("name") or "").strip()[: _MAX_STR["name"]]
    if name:
        out["name"] = name
    role = str(raw.get("role") or raw.get("title") or raw.get("job") or "").strip()[: _MAX_STR["role"]]
    if role:
        out["role"] = role
    skills = _as_list(raw.get("skills") or raw.get("capabilities"))
    if skills:
        out["skills"] = skills
    education = _as_list(raw.get("education"))
    if education:
        out["education"] = education
    links = _as_list(raw.get("links") or raw.get("urls"), link=True)
    if links:
        out["links"] = links
    return out or None


def collect(run: Any, parsed: dict[str, Any] | None) -> None:
    if parsed is None:
        return
    item = normalize(parsed.get("profile_update") or parsed.get("profile"))
    if not item:
        return
    bucket = getattr(run, "profile_updates", None)
    if bucket is None:
        run.profile_updates = [item]
    else:
        bucket.append(item)


def merge(updates: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    acc: dict[str, Any] = {}
    for item in updates or []:
        norm = normalize(item)
        if not norm:
            continue
        if "name" in norm:
            acc["name"] = norm["name"]
        if "role" in norm:
            acc["role"] = norm["role"]
        for key in LIST_KEYS:
            if key not in norm:
                continue
            acc[key] = _uniq((acc.get(key) or []) + list(norm[key]))
    return acc or None


def apply_update(update: dict[str, Any] | None, run_id: str) -> dict[str, Any]:
    item = normalize(update)
    rid = str(run_id or "").strip()
    if not item or not rid:
        return {"ok": False, "error": "empty_update"}
    with _LOCK:
        board = load()
        if rid in board["applied_runs"]:
            return {"ok": True, "already": True, "board": public_board(board)}
        if "name" in item:
            board["name"] = item["name"]
        if "role" in item:
            board["role"] = item["role"]
        for key in LIST_KEYS:
            if key in item:
                board[key] = _uniq(list(board.get(key) or []) + list(item[key]))
        board["applied_runs"] = _uniq(list(board["applied_runs"]) + [rid])
        board["updated"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        save(board)
        return {"ok": True, "already": False, "board": public_board(board)}


def public_board(board: dict[str, Any] | None = None) -> dict[str, Any]:
    blob = board if board is not None else load()
    return {
        "name": blob.get("name") or "",
        "role": blob.get("role") or "",
        "skills": list(blob.get("skills") or []),
        "education": list(blob.get("education") or []),
        "links": list(blob.get("links") or []),
        "updated": blob.get("updated") or "",
        "applied_runs": list(blob.get("applied_runs") or []),
    }


def _as_list(value: Any, *, link: bool = False) -> list[str]:
    items: list[str] = []
    if value is None:
        return items
    if isinstance(value, str):
        parts = re.split(r"[\n,;]+", value)
        items.extend(parts)
    elif isinstance(value, (list, tuple)):
        for entry in value:
            items.append(str(entry))
    else:
        items.append(str(value))
    cap = _MAX_LINK if link else _MAX_ITEM
    out: list[str] = []
    for item in items:
        text = item.strip()[:cap]
        if text:
            out.append(text)
        if len(out) >= _MAX_LIST:
            break
    return out


def _uniq(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out[:_MAX_LIST]
