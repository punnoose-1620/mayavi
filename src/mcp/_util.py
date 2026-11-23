"""Tiny helpers for pack bind functions. Agents never import this file."""

from __future__ import annotations

from typing import Any

import config


def as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def exec_timeout(value: Any) -> int:
    limit = int(config.EXECUTE_TIMEOUT)
    if value is None:
        return limit
    return max(1, min(as_int(value, limit), limit))


def ops_needed(value: str | None) -> bool:
    return str(value or "0").strip() not in {"", "0", "no", "off"}


def writers_open(run: Any) -> bool:
    if run.level != "large":
        return True
    if not run.coding:
        return True
    return bool(run.ship_unlocked)


def mail_manager(run: Any, agent: Any) -> bool:
    if run.committee is not None:
        return agent.role == "manager"
    if run.level == "large":
        return agent.role == "executor"
    return agent.role == "drafter"
