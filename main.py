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
    args = parser.parse_args(argv)
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        parser.print_help()
        return 2
    generate_fn = stub_generate if args.no_model else None
    fields = _route_fields(prompt, args.no_model)
    if fields.get("level") == "large" and not args.json:
        print("working (large) — sequential models, this can take a while…", flush=True)
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
        + (f" thread_id={result.get('thread_id')}" if result.get("thread_id") else ""),
        flush=True,
    )
    for notice in result.get("notices") or []:
        print(NOTICE_TEXT.get(str(notice).split(":", 1)[0], str(notice)), flush=True)


NOTICE_TEXT = {
    "mail_connect_failed": "Mail/calendar consent did not complete, so this run had no inbox access.",
    "thread_not_found": "That thread id was not found under state/threads/, so this run did not attach a notebook.",
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


if __name__ == "__main__":
    raise SystemExit(main())
