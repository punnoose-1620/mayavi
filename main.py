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
    args = parser.parse_args(argv)
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        parser.print_help()
        return 2
    generate_fn = stub_generate if args.no_model else None
    fields = _route_fields(prompt, args.no_model)
    result = executor.run_session(prompt, fields, generate_fn=generate_fn, provider=args.provider)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(result.get("answer") or "", flush=True)
        print(f"\n[level={result.get('level')} stakes={result.get('stakes')} mail_cal={result.get('mail_cal')}]", file=sys.stderr)
    return 0 if result.get("ok") else 1


def _route_fields(prompt: str, no_model: bool) -> dict[str, Any]:
    if no_model:
        return router.heuristic_route(prompt)
    loaded = models.loadModel("router")
    if not loaded.get("ok"):
        return router.heuristic_route(prompt)
    try:
        out = models.generate("router", messages=[{"role": "system", "content": router.ROUTER_SYSTEM}, {"role": "user", "content": prompt}], max_tokens=128)
        text = out.get("text") or ""
        return router.parse_router_output(text)
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
