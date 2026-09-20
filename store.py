"""Private run registry. Not in the agent tool schema."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


GenerateFn = Callable[..., str]


@dataclass
class Agent:
    agent_name: str
    role: str
    model_role: str
    model: str
    run_id: str
    parent_agent: str | None
    thread_state: str = "none"
    history: list[dict[str, str]] = field(default_factory=list)
    sandbox_bound: bool = False


@dataclass
class Blackboard:
    run_id: str
    frozen: bool = False
    max_len: int = 4000
    max_count: int = 200
    messages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Run:
    run_id: str
    level: str = "small"
    stakes: str = "low"
    mail_cal: str = "off"
    file_ops: str = "0"
    web_ops: str = "0"
    needs_code_exec: str = "no"
    intent: str = ""
    user_prompt: str = ""
    provider: str | None = None
    account_email: str | None = None
    timezone: str = "UTC"
    agents: dict[str, Agent] = field(default_factory=dict)
    blackboard: Blackboard | None = None
    sandbox_path: Path | None = None
    keep_path: Path | None = None
    sandbox_executed: bool = False
    ship_unlocked: bool = False
    summarize_keep: bool = False
    session_path: Path | None = None
    oauth: dict[str, Any] = field(default_factory=dict)
    exclusive_lock: threading.Lock = field(default_factory=threading.Lock)
    exclusive_holder: str | None = None
    notices: list[str] = field(default_factory=list)
    sandbox_results: dict[str, Any] = field(default_factory=dict)
    sandbox_proc: Any = None
    generate_fn: GenerateFn | None = None
    router_agent: str | None = None
    rules_frozen: bool = False
    session_frozen: bool = False
    used_model_root: str | None = None
    secondary_provider: str | None = None
    thread_id: str | None = None
    thread: dict[str, Any] | None = None


_RUNS: dict[str, Run] = {}
_AGENT_INDEX: dict[str, str] = {}
_LOCK = threading.Lock()


def reset() -> None:
    with _LOCK:
        _RUNS.clear()
        _AGENT_INDEX.clear()


def put_run(run: Run) -> None:
    with _LOCK:
        _RUNS[run.run_id] = run
        for name in run.agents:
            _AGENT_INDEX[name] = run.run_id


def get_run(run_id: str) -> Optional[Run]:
    return _RUNS.get(run_id)


def run_for_agent(agent_name: str) -> Optional[Run]:
    run_id = _AGENT_INDEX.get(agent_name)
    if not run_id:
        return None
    return _RUNS.get(run_id)


def register_agent(run: Run, agent: Agent) -> None:
    run.agents[agent.agent_name] = agent
    _AGENT_INDEX[agent.agent_name] = run.run_id


def drop_agent(agent_name: str) -> None:
    run_id = _AGENT_INDEX.pop(agent_name, None)
    if run_id and run_id in _RUNS:
        _RUNS[run_id].agents.pop(agent_name, None)


def drop_run(run_id: str) -> None:
    run = _RUNS.pop(run_id, None)
    if not run:
        return
    for name in list(run.agents):
        _AGENT_INDEX.pop(name, None)
