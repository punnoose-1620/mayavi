"""Local code map for the coder and the critique. Agents never import this file.

The host runs Graphify on the sandbox with --code-only. Docs, images, and video
are not read, and no cloud model is called. The graph stays in Mayavi's cache.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

import skills.host as host

ANSWER_CAP = 1600
QUERY_CAP = 240
_CODE_SUFFIXES = {".py", ".js"}
_MARKER = (("graphify/__main__.py", "file"),)
_DROP = re.compile(r"app\.graphify\.com|Prefer a hosted|utm_", re.I)
_LLM_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_BASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "GRAPHIFY_BACKEND",
)
_PREFIX = (
    "Sandbox code map. Names and calls below were read from the Python and JavaScript files. "
    "Coding rules still win.\n\n"
)


def find_root() -> Path | None:
    return host.find_checkout(("MAYAVI_GRAPHIFY_ROOT",), "graphify", _MARKER)


def available() -> bool:
    return find_root() is not None and importlib.util.find_spec("graphify") is not None


def ask(query: str, sandbox: Path | None, cache: Path) -> dict[str, str | bool]:
    """Refresh the sandbox map when code changed, then answer one question."""
    text = " ".join(str(query or "").split())[:QUERY_CAP]
    if len(text) < 2:
        return {"ok": False, "error": "empty_query"}
    root = find_root()
    if root is None or importlib.util.find_spec("graphify") is None:
        return {"ok": False, "error": "code_graph_missing"}
    if sandbox is None or not sandbox.is_dir():
        return {"ok": False, "error": "no_sandbox"}
    files = code_files(sandbox)
    if not files:
        return {"ok": False, "error": "no_code"}
    cache.mkdir(parents=True, exist_ok=True)
    graph = cache / "graphify-out" / "graph.json"
    newest = max(path.stat().st_mtime for path in files)
    if not graph.is_file() or graph.stat().st_mtime < newest:
        built = _run(extract_argv(sandbox, cache), cache, root, timeout=120)
        if built is None or built.returncode != 0 or not graph.is_file():
            return {"ok": False, "error": "extract_failed" if built is not None else "timeout"}
    queried = _run(query_argv(text, graph), cache, root, timeout=30)
    if queried is None:
        return {"ok": False, "error": "timeout"}
    answer = trim_answer(queried.stdout or "")
    if queried.returncode not in {0, 3, 4} or len(answer) < 20:
        return {"ok": False, "error": "query_failed"}
    return {"ok": True, "answer": answer}


def code_files(sandbox: Path) -> list[Path]:
    found: list[Path] = []
    for path in sandbox.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _CODE_SUFFIXES:
            continue
        if "graphify-out" in path.parts or "__pycache__" in path.parts:
            continue
        found.append(path)
    return found


def extract_argv(sandbox: Path, cache: Path) -> list[str]:
    """Code-only extract. No cluster naming, no docs, no network model."""
    return [
        sys.executable,
        "-m",
        "graphify",
        "extract",
        str(sandbox),
        "--code-only",
        "--no-cluster",
        "--max-workers",
        "1",
        "--out",
        str(cache),
    ]


def query_argv(question: str, graph: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "graphify",
        "query",
        question,
        "--budget",
        "600",
        "--depth",
        "2",
        "--graph",
        str(graph),
    ]


def trim_answer(text: str) -> str:
    kept = [line for line in str(text or "").replace("\r\n", "\n").splitlines() if line.strip() and not _DROP.search(line)]
    body = _PREFIX + "\n".join(kept).strip()
    if len(body) <= ANSWER_CAP:
        return body
    return body[: ANSWER_CAP - 1] + "…"


def _run(argv: list[str], cache: Path, root: Path, timeout: int) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            cwd=str(cache),
            env=_child_env(root),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None


def _child_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(root) if not previous else str(root) + os.pathsep + previous
    env["PYTHONHASHSEED"] = "0"
    for key in _LLM_KEYS:
        env.pop(key, None)
    return env
