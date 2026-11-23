"""Profile read / merge / claim-check pack. Host still schema-checks saves."""

from __future__ import annotations

from typing import Any

import logger

NAME = "profile"
TOOLS = ("read_profile", "save_profile", "check_claims")


def bind(run: Any, agent: Any) -> dict[str, Any]:
    aid = agent.agent_name
    return {
        "read_profile": lambda **kw: _read(run, aid),
        "save_profile": lambda **kw: _save(run, aid, kw),
        "check_claims": lambda **kw: _check(run, aid, kw),
    }


def _read(run: Any, agent_name: str) -> dict[str, Any]:
    import career

    did = str(getattr(run, "device_id", "") or "")
    if not did:
        return _tool("read_profile", run, agent_name, {"ok": False, "error": "missing_device"})
    try:
        text = career.profile_text(did)
    except ValueError as exc:
        return _tool("read_profile", run, agent_name, {"ok": False, "error": str(exc)})
    return _tool("read_profile", run, agent_name, {"ok": True, "text": text[:8000]})


def _save(run: Any, agent_name: str, kw: dict[str, Any]) -> dict[str, Any]:
    import career
    import profiledoc

    did = str(getattr(run, "device_id", "") or "")
    if not did:
        return _tool("save_profile", run, agent_name, {"ok": False, "error": "missing_device"})
    blob = kw.get("profile") if isinstance(kw.get("profile"), dict) else kw
    try:
        saved = career.save_resume(did, blob, merge=True)
    except Exception as exc:
        return _tool("save_profile", run, agent_name, {"ok": False, "error": type(exc).__name__})
    return _tool(
        "save_profile",
        run,
        agent_name,
        {"ok": True, "text": profiledoc.render_profile(saved)[:4000]},
    )


def _check(run: Any, agent_name: str, kw: dict[str, Any]) -> dict[str, Any]:
    import jobapp

    text = str(kw.get("text") or kw.get("body") or kw.get("content") or "")
    ratio, unsupported = jobapp.claim_ratio(text)
    passed = ratio <= jobapp.HALLUCINATION_LIMIT
    return _tool(
        "check_claims",
        run,
        agent_name,
        {
            "ok": True,
            "passed": passed,
            "ratio": ratio,
            "unsupported": unsupported[:20],
        },
    )


def _tool(name: str, run: Any, agent_name: str, result: dict[str, Any]) -> dict[str, Any]:
    return logger.finish(
        event="tool",
        tool=name,
        run_id=None if run is None else run.run_id,
        agent_name=agent_name,
        result=result,
        level=None if run is None else run.level,
        stakes=None if run is None else run.stakes,
        mail_cal=None if run is None else run.mail_cal,
    )
