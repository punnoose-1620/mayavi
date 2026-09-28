"""CLI entry: route a prompt, run the factory, print one answer."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import executor
import models
import router


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="id10t local committee runtime")
    parser.add_argument("prompt", nargs="*", help="User request")
    parser.add_argument("--no-model", action="store_true", help="Heuristic route + stub reply (no GGUF load)")
    parser.add_argument("--provider", choices=["google", "microsoft"], default=None)
    parser.add_argument("--json", action="store_true", help="Print the full run record as JSON")
    parser.add_argument(
        "--thread",
        default=None,
        metavar="thr_id",
        help="Attach a durable thread (state/threads). Raises a mapped-small run to medium.",
    )
    parser.add_argument("--code", action="store_true", help="Run the sequential coding committee")
    parser.add_argument(
        "--repo",
        default=None,
        metavar="URL",
        help="GitHub repo https://github.com/owner/repo (coding only). Empty or invalid hides git tools.",
    )
    args = parser.parse_args(argv)
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        parser.print_help()
        return 2
    generate_fn = stub_generate if args.no_model else None
    fields = _route_fields(prompt, args.no_model)
    fields = router.apply_user_controls(fields, coding=args.code, git_remote=args.repo)
    if not args.json:
        if fields.get("coding"):
            print("working (coding committee) — sequential models, this can take a while…", flush=True)
        elif str(fields.get("stakes") or "") == "high":
            print("working (review committee) — sequential models, this can take a while…", flush=True)
    try:
        result = executor.run_session(
            prompt, fields, generate_fn=generate_fn, provider=args.provider, thread_id=args.thread
        )
    except Exception as exc:
        print(_failure_text(exc), file=sys.stderr, flush=True)
        return 1
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        _print_run(prompt, result)
    return 0 if result.get("ok") else 1


FAILURE_TEXT = {
    "sandbox_leak": "Could not delete this run's sandbox. Remove it under sandboxes/ before the next run.",
    "log_write_failed": "The audit log could not be written, so this run was stopped. Check state/logs/.",
}


def _failure_text(exc: BaseException) -> str:
    """Operators get a sentence, not a traceback."""
    key = str(exc).strip()
    known = FAILURE_TEXT.get(key)
    if known:
        return known
    return f"Run stopped: {type(exc).__name__}: {key or 'no detail'}"


def _print_run(prompt: str, result: dict[str, Any]) -> None:
    answer = str(result.get("answer") or "").strip()
    print("---------- Prompt ----------", flush=True)
    print(prompt, flush=True)
    print("---------- Response ----------", flush=True)
    if answer:
        print(answer, flush=True)
    else:
        print("(empty — the model produced no user-facing answer)", flush=True)
    print("---------- Meta ----------", flush=True)
    print(
        f"ok={result.get('ok')} level={result.get('level')} "
        f"stakes={result.get('stakes')} mail_cal={result.get('mail_cal')} "
        f"run_id={result.get('run_id')}"
        + (f" shape={result.get('shape')}" if result.get("shape") else "")
        + (f" git={result.get('git_remote')}" if result.get("git_remote") else "")
        + (f" thread_id={result.get('thread_id')}" if result.get("thread_id") else ""),
        flush=True,
    )
    board = result.get("committee")
    if isinstance(board, dict):
        vote = board.get("vote") or {}
        print(
            f"committee phase={board.get('phase')} round={board.get('round')} "
            f"shipped={board.get('shipped')} vote={vote}",
            flush=True,
        )
    for notice in result.get("notices") or []:
        print(NOTICE_TEXT.get(str(notice).split(":", 1)[0], str(notice)), flush=True)


NOTICE_TEXT = {
    "mail_connect_failed": "Mail/calendar consent did not complete, so this run had no inbox access.",
    "thread_not_found": "That thread id was not found under state/threads/, so this run did not attach a notebook.",
    "model_unavailable": "The worker GGUF did not load; the answer names the reason.",
}

GENERATE_TEXT = {
    "busy": "Another inference call holds the model lock; routing with the heuristic instead.",
    "ram_dropped": "Free RAM fell below the reserve mid-route; routing with the heuristic instead.",
}

ROUTER_FALLBACK_TEXT = {
    "low_ram": "Not enough free RAM for the router model; routing with the heuristic instead.",
    "not_found": "Router GGUF not found; routing with the heuristic instead. See README > Models to download it.",
    "llama_cpp_missing": "llama-cpp-python is not installed; routing with the heuristic instead.",
}


def _route_fields(prompt: str, no_model: bool) -> dict[str, Any]:
    if no_model:
        return router.heuristic_route(prompt)
    ram = models.checkRam("router")
    if not ram.get("ok"):
        print(ROUTER_FALLBACK_TEXT["low_ram"], file=sys.stderr, flush=True)
        return router.heuristic_route(prompt)
    loaded = models.loadModel("router")
    if not loaded.get("ok"):
        reason = str(loaded.get("error") or "")
        print(
            ROUTER_FALLBACK_TEXT.get(reason, f"Router model unavailable ({reason or 'unknown'}); routing with the heuristic instead."),
            file=sys.stderr,
            flush=True,
        )
        return router.heuristic_route(prompt)
    try:
        out = models.generate("router", messages=[{"role": "system", "content": router.ROUTER_SYSTEM}, {"role": "user", "content": prompt}], max_tokens=128)
        if not out.get("ok"):
            reason = str(out.get("error") or "unknown")
            print(GENERATE_TEXT.get(reason, f"Router did not answer ({reason}); routing with the heuristic instead."), file=sys.stderr, flush=True)
            return router.heuristic_route(prompt)
        return router.parse_router_output(out.get("text") or "")
    finally:
        models.unloadModel()


def stub_generate(run: Any, agent: Any, history: list[dict[str, str]]) -> str:
    if getattr(run, "committee", None) is not None:
        return _stub_committee(run, agent, history)
    tool_turns = sum(1 for m in history if m.get("role") == "tool")
    if run.level in {"medium", "large"}:
        body = f"{agent.role}: {run.intent}"
        if tool_turns == 0:
            kind = "draft" if agent.role in {"drafter", "builder"} else "critique"
            return json.dumps({"tool": "sendMessageToBlackboard", "args": {"kind": kind, "body": body}})
        if tool_turns == 1:
            return json.dumps({"tool": "sendMessageToBlackboard", "args": {"kind": "vote", "body": run.intent}})
        return json.dumps({"final": run.intent})
    return json.dumps({"final": f"(no local model) {run.intent}"})


def _stub_committee(run: Any, agent: Any, history: list[dict[str, str]]) -> str:
    stage = str(getattr(run, "committee_stage", "") or "")
    role = agent.role
    tools_done = sum(1 for m in history if m.get("role") == "tool")
    intent = str(run.intent or run.user_prompt or "hello").strip() or "hello"
    if stage == "vote":
        return json.dumps({"vote": "yes", "final": f"{role} yes"})
    if role == "manager" and stage == "phase0":
        return json.dumps(
            {
                "board_update": {
                    "features": f"{intent}; non-goals: network, secrets",
                    "architecture": "hello.py CLI",
                },
                "final": "phase 0 contract",
            }
        )
    if role == "coder":
        if tools_done == 0:
            return json.dumps(
                {
                    "tool": "sandbox_write",
                    "args": {"path": "hello.py", "content": "print('hello')\n"},
                }
            )
        return json.dumps({"board_update": {"code": "hello.py print hello"}, "final": "wrote hello.py"})
    if role == "tester":
        if tools_done == 0:
            return json.dumps({"tool": "executeScriptInSandbox", "args": {"path": "hello.py"}})
        return json.dumps(
            {
                "board_update": {"tests": [{"name": "hello", "feature": intent, "status": "pass"}]},
                "final": "tests pass",
            }
        )
    if role == "critique":
        return json.dumps({"board_update": {"critiques": ["none blocking"]}, "final": "no blockers"})
    if role == "evaluator":
        return json.dumps({"final": "bar met"})
    if role == "manager":
        return json.dumps({"call_vote": True, "final": "ready to vote"})
    if role == "documenter":
        return json.dumps({"board_update": {"docs": f"README: {intent}"}, "final": "documented"})
    return json.dumps({"final": "ok"})


if __name__ == "__main__":
    raise SystemExit(main())
