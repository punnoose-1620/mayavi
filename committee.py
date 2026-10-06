"""Sequential coding/review committee for USB chat. One GGUF. No factory imports."""

from __future__ import annotations

import ast
import csv
import io
import json
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

YES_FOR_COMMIT = 4
MAX_ROUNDS = 4
MAX_TOOL_STEPS = 5
TESTER_INNER_MAX = 3
CODER_INNER_MAX = 3
SMOKE_TIMEOUT = 15
MAIN_FILE = "main.py"
WRITE_CONTENT_PLACEHOLDER = "<FULL_SOURCE>"
VIEW_CHARS = 2600
LOG_RAW_CHARS = 8000
LOG_CONTENT_HEAD = 400
EXECUTE_TIMEOUT = 30
EXECUTE_TIMEOUT_MAX = 1200
CLONE_TIMEOUT = 120
WRITE_EXT = {".py", ".txt", ".md", ".html", ".css", ".js", ".json", ".csv"}
SEED_MAX_FILES = 80
SEED_MAX_BYTES = 2 * 1024 * 1024
SEED_MAX_FILE_BYTES = 256 * 1024
SEED_PROMPT_CAP = 4000
SEED_PROMPT_NAMES = ("TASK.md", "PROMPT.md", "README.md")
DATA_DOC_EXT = {".csv", ".txt", ".json", ".md"}
DATA_CARD_CAP = 1800
DATA_CARD_UNIQUES = 8
DATA_CARD_SAMPLES = 2
SEED_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        "node_modules",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".idea",
        ".vscode",
        "dist",
        "build",
        "_logs",
        "site-packages",
    }
)
SEED_SKIP_NAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.development",
        "credentials.json",
        "secrets.json",
        ".netrc",
        "id_rsa",
        "id_rsa.pub",
    }
)
SEED_SKIP_SUFFIX = frozenset({".pem", ".key", ".p12", ".pfx", ".der"})
VOTING_ROLES = ("manager", "coder", "tester", "critique", "evaluator")
TARGET_AGGS = frozenset({"mean", "min"})
TARGET_OPS = frozenset({">=", "<=", ">", "<", "=="})
_VACUOUS_METRIC = frozenset(
    {"works", "work", "ok", "okay", "correct", "pass", "passed", "passing", "success", "runs", "running", "valid", "good"}
)
_SCORES_LINE = re.compile(r"^SCORES\s+(.+)$", re.I | re.M)
_SCORES_PAIR = re.compile(r"([A-Za-z_][\w]*)\s*=\s*(\[[^\]]*\]|[^\s]+)")
_TEST_ABORT = re.compile(r"\bassert\b|\bsys\.exit\b|\braise\s+AssertionError\b")
_SCORES_PRINT = re.compile(r"SCORES\b", re.I)
_SCORES_LITERAL = re.compile(
    r"SCORES\s+[A-Za-z_]\w*\s*=\s*-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?)+\s*",
    re.I,
)
_TRACE_FILE = re.compile(r'File "([^"]+)", line (\d+)')
_ATTR_MODULE = re.compile(
    r"AttributeError: module ['\"]([\w.]+)['\"] has no attribute(?: ['\"](\w+)['\"])?"
)
_ABSENT_CLAIM = re.compile(
    r"\b(?:are missing|is missing|no function|no class|no test|does not exist|"
    r"not (?:found|defined|implemented)|lacks?)\b",
    re.I,
)
OWNERSHIP_RULES = (
    "Ownership (host, do not change): "
    "manager writes targets, features, and next_fix only (no sandbox files); "
    "at phase 0 the manager may also write test_plan cases from the host data card, then that plan is locked. "
    "coder writes implementation files and main.py only (never read, write, or execute test_*.py or *_test.py); "
    "coder only edits files already in the work folder or new non-test .py it creates; "
    "host compile+imports libs then runs main.py (must exit 0); after each impl write the host runs that file; quality is not the coder's job. "
    "main.py literals must appear on the host data card when one exists (same spelling and type). "
    "sandbox_write args.content is the full file text (replace <FULL_SOURCE>; never leave ...). "
    "Python '...' and \"...\" strings must stay on one physical line; use \\n, triple quotes, or a data file for more than one line. "
    "Do not give a field or variable the same name as a function or method it must call (self.store = {} hides def store). "
    "tester writes and executes test_*.py / *_test.py only; clone main.py calls with other literals that still appear on the data card; "
    "each SCORES value is computed (never a literal 1,1,1 list); never impl. "
    "critique and evaluator do not write sandbox files. "
    "Stdlib only. No pip. No secrets."
)
_FENCE = re.compile(
    r"```(?:([A-Za-z0-9_+-]+))?(?:[ \t]+([A-Za-z0-9._/-]+))?[ \t]*\n(.*?)(?:```|$)",
    re.S,
)
_HASH_FILE = re.compile(r"^#\s*(?:file(?:name)?\s*[:=]\s*)?([A-Za-z0-9._-]+\.[A-Za-z0-9]+)\s*$", re.I)
_PATH_KEYS = ("path", "file", "script", "filename")
_CONTENT_KEYS = ("content", "body", "text", "code", "source")
_TOOL_NAMES = frozenset(
    {"sandbox_write", "sandbox_read", "executeScriptInSandbox", "write_pdf", "write_doc"}
)

SECTION_ALIASES = {
    "baselines": "features",
    "contract": "features",
    "job": "features",
    "non_goals": "features",
    "nongoals": "features",
    "goal": "features",
    "modules": "architecture",
    "design": "architecture",
    "sketch": "architecture",
    "layout": "architecture",
    "readme": "docs",
    "notes": "docs",
    "diff": "code",
    "paths": "code",
    "cases": "tests",
    "plan": "test_plan",
    "fixes": "next_fix",
    "next": "next_fix",
}
SECTION_WRITERS = {
    "coding_rules": frozenset({"factory"}),
    "features": frozenset({"manager", "drafter"}),
    "architecture": frozenset({"manager", "drafter"}),
    "targets": frozenset({"manager"}),
    "code": frozenset({"coder"}),
    "tests": frozenset({"tester"}),
    "test_plan": frozenset({"manager", "tester"}),
    "critiques": frozenset({"critique", "critic"}),
    "critique_scores": frozenset({"evaluator"}),
    "critique_status": frozenset({"manager"}),
    "next_fix": frozenset({"manager"}),
    "docs": frozenset({"documenter", "drafter", "writer"}),
}

CODE_AGENT_MARKS = (
    "html",
    ".css",
    "stylesheet",
    ".js",
    "javascript",
    "typescript",
    "web page",
    "webpage",
    "landing page",
    "python script",
    "write a function",
    "write a class",
    "write a program",
    "code snippet",
    " python",
    "python ",
    "matrix",
    "todo",
    " cli",
    "```html",
    "```css",
    "```js",
    "```python",
)
EXECUTE_MARKS = (
    "sandbox",
    "run python",
    "run the code",
    "run this",
    "execute",
    "unit test",
    "test this",
    "in the jail",
)
HIGH_STAKES_MARKS = (
    "legal",
    "contract",
    "clause",
    "official",
    "policy",
    "government",
    "medical",
    "financial",
    "sign this",
    "review this document",
    "compliance",
)

UNTESTED = "This code is not tested; it was not executed because Coding is not selected."
CANNOT_TEST = "I cannot test or run this without Coding selected. Turn on Coding to use the sandbox."

_COMMIT_DUP = re.compile(r"\s+")
_GH = re.compile(
    r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)/"
    r"([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\.git)?",
    re.I,
)


CompleteFn = Callable[[list[dict[str, str]]], str]
StatusFn = Callable[[str], None]


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _clip_log(text: Any, cap: int = LOG_RAW_CHARS) -> str:
    body = str(text or "")
    if len(body) <= cap:
        return body
    return body[: cap - 1] + "…"


def _tool_args_for_log(args: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (args or {}).items():
        name = str(key)
        if name.lower() in {"content", "body", "text"}:
            blob = str(value or "")
            out[name + "_n"] = len(blob)
            out[name + "_head"] = _clip_log(blob, LOG_CONTENT_HEAD)
        elif isinstance(value, str) and len(value) > 800:
            out[name] = _clip_log(value, 800)
        else:
            out[name] = value
    return out


class CodingLog:
    def __init__(self, path: Path | None, mirror: Path | None = None) -> None:
        paths: list[Path] = []
        if path is not None:
            paths.append(path.resolve())
        if mirror is not None:
            paths.append(mirror.resolve())
        self.path = paths[0] if paths else None
        self.paths = paths
        for item in self.paths:
            item.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: str, **fields: Any) -> None:
        if not self.paths:
            return
        row = {"time": _utc_stamp(), "event": event, **fields}
        line = json.dumps(row, ensure_ascii=True, default=str) + "\n"
        for path in self.paths:
            try:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                continue


class SessionLogs:
    """Host-owned append-only planner/critique/test logs, mirrored into keep/_logs."""

    def __init__(self, session_dir: Path | None, keep_dir: Path | None) -> None:
        self.dir = session_dir.resolve() if session_dir else None
        if self.dir is not None:
            self.dir.mkdir(parents=True, exist_ok=True)
        self.keep = None
        if keep_dir is not None:
            self.keep = (Path(keep_dir) / "_logs").resolve()
            try:
                self.keep.mkdir(parents=True, exist_ok=True)
            except OSError:
                self.keep = None

    def append(self, name: str, **fields: Any) -> None:
        row = {"time": _utc_stamp(), **fields}
        line = json.dumps(row, ensure_ascii=True, default=str) + "\n"
        for folder in (self.dir, self.keep):
            if folder is None:
                continue
            path = folder / f"{name}.jsonl"
            try:
                with path.open("a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                continue


def _session_from_coding_log(coding_log: Path | None) -> tuple[Path | None, Path | None]:
    """Return (session_dir, generic.jsonl path)."""
    if coding_log is None:
        return None, None
    path = Path(coding_log)
    if path.suffix.lower() == ".jsonl":
        return path.parent, path
    return path, path / "generic.jsonl"


def _score_gap(board: Board) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for target in board.targets:
        metric = str(target.get("metric") or "")
        try:
            need = int(target.get("n") or 0)
        except (TypeError, ValueError):
            need = 0
        got = list(board.trial_scores.get(metric) or [])
        rows.append(
            {
                "id": target.get("id"),
                "metric": metric,
                "need_n": need,
                "got_n": len(got),
                "values": got,
                "enough": len(got) >= need if need else False,
            }
        )
    return rows


@dataclass
class TestItem:
    name: str
    feature: str = ""
    status: str = "pending"
    detail: str = ""


@dataclass
class CritiqueItem:
    item_id: str
    text: str
    score: str = ""
    status: str = "open"
    owner: str = ""
    file: str = ""
    problem: str = ""
    fix: str = ""


@dataclass
class Board:
    coding_rules: str = ""
    features: str = ""
    architecture: str = ""
    code: str = ""
    targets: list[dict[str, Any]] = field(default_factory=list)
    targets_source: str = ""
    targets_locked: bool = False
    test_plan: str = ""
    test_plan_locked: bool = False
    data_card: str = ""
    tests: list[TestItem] = field(default_factory=list)
    trial_scores: dict[str, list[float]] = field(default_factory=dict)
    qualify_detail: str = ""
    qualified: bool = False
    critiques: list[CritiqueItem] = field(default_factory=list)
    next_fix: list[dict[str, Any]] = field(default_factory=list)
    last_eval: str = ""
    harness_ok: bool = False
    smoke_ok: bool = False
    smoke_detail: str = ""
    inventory: dict[str, Any] = field(default_factory=dict)
    scored_ok: bool = False
    done_detail: str = ""
    contract_locked: bool = False
    coding_rules_locked: bool = False
    docs: str = ""
    phase: str = "0"
    round: int = 0
    last_vote: dict[str, str] = field(default_factory=dict)
    vote_open: bool = False
    phase_complete: bool = False
    stop: bool = False
    profile_update: dict[str, Any] = field(default_factory=dict)


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel: str) -> Path | None:
        raw = str(rel or "").replace("\\", "/").lstrip("/")
        if not raw or raw.startswith("..") or ".." in Path(raw).parts:
            return None
        path = (self.root / raw).resolve()
        try:
            path.relative_to(self.root)
        except ValueError:
            return None
        return path

    def write(self, rel: str, content: str) -> dict[str, Any]:
        path = self.resolve(rel)
        if path is None or path.suffix.lower() not in WRITE_EXT:
            return {"ok": False, "error": "bad_path"}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content or ""), encoding="utf-8")
        return {"ok": True, "path": str(path.relative_to(self.root)).replace("\\", "/")}

    def read(self, rel: str, start: int = 0, end: int = 4000) -> dict[str, Any]:
        path = self.resolve(rel)
        if path is None or not path.is_file():
            return {"ok": False, "error": "missing"}
        text = path.read_text(encoding="utf-8", errors="replace")
        lo = max(0, int(start or 0))
        hi = max(lo, int(end or lo + 4000))
        return {"ok": True, "text": text[lo:hi], "n": len(text)}

    def execute(self, rel: str, timeout: int = EXECUTE_TIMEOUT) -> dict[str, Any]:
        path = self.resolve(rel)
        if path is None or not path.is_file() or path.suffix.lower() != ".py":
            return {"ok": False, "error": "bad_script"}
        try:
            proc = subprocess.run(
                [sys_executable(), str(path)],
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout or EXECUTE_TIMEOUT)),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "timeout", "stdout": "", "stderr": "timeout"}
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {
            "ok": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": (proc.stdout or "")[:8000],
            "stderr": (proc.stderr or "")[:4000],
        }

    def pdfs(self) -> list[Path]:
        return sorted(p for p in self.root.rglob("*.pdf") if p.is_file())

    def listing(self, cap: int = 40) -> str:
        rows: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root)
            if any(part in {"_logs", "__pycache__"} or part.endswith(".pyc") for part in rel.parts):
                continue
            rows.append(str(rel).replace("\\", "/"))
            if len(rows) >= cap:
                break
        return "\n".join(rows) if rows else "(empty)"


def sys_executable() -> str:
    return sys.executable or shutil.which("python") or shutil.which("python3") or "python"


def public_github_remote(url: str | None) -> str | None:
    raw = str(url or "").strip()
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        if "@" in rest:
            rest = rest.rsplit("@", 1)[-1]
        raw = f"{scheme}://{rest}"
    raw = raw.rstrip("/")
    if raw.lower().endswith(".git"):
        raw = raw[:-4]
    match = _GH.fullmatch(raw)
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    if repo.lower() in {".git", "gist"}:
        return None
    return f"https://github.com/{owner}/{repo}"


def wants_code_agent(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(mark in text for mark in CODE_AGENT_MARKS)


def wants_execute(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(mark in text for mark in EXECUTE_MARKS)


def looks_high_stakes(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(mark in text for mark in HIGH_STAKES_MARKS)


def _thin_code_answer(text: str) -> bool:
    body = str(text or "").strip()
    if len(body) < 40:
        return True
    lowered = body.lower()
    if "(no local model)" in lowered:
        return True
    if "```" in body or "<html" in lowered or "def " in body or "class " in body:
        return False
    return True


def off_coding_draft(prompt: str) -> str:
    if wants_execute(prompt):
        return f"{CANNOT_TEST}\n\nExample (not executed):\n\n```python\nprint('hello')\n```\n"
    text = (prompt or "").lower()
    if "html" in text or "flashy" in text or "landing" in text or "javascript" in text or "webpage" in text or "web page" in text:
        body = _LANDING_HTML if ("landing" in text or "javascript" in text) else _FLASHY_HTML
        return f"```html\n{body.rstrip()}\n```\n\n{UNTESTED}\n"
    if "class" in text or "todo" in text:
        return f"```python\n{_TODO_CLASS.rstrip()}\n```\n\n{UNTESTED}\n"
    if "matrix" in text:
        return f"```python\n{_MATRIX.rstrip()}\n```\n\n{UNTESTED}\n"
    if "cli" in text:
        return f"```python\n{_HELLO_CLI.rstrip()}\n```\n\n{UNTESTED}\n"
    return f"```python\n{_HELLO_FN.rstrip()}\n```\n\n{UNTESTED}\n"


def finish_off_coding(prompt: str, text: str) -> str:
    if wants_execute(prompt):
        if _thin_code_answer(text):
            return off_coding_draft(prompt).strip()
        if "cannot test" not in text.lower() and "coding" not in text.lower():
            return text.rstrip() + "\n\n" + CANNOT_TEST
        return text
    if wants_code_agent(prompt):
        if _thin_code_answer(text):
            return off_coding_draft(prompt).strip()
        if "not tested" not in text.lower() and "not executed" not in text.lower():
            return text.rstrip() + "\n\n" + UNTESTED
        return text
    return text


def _unwrap_fences(text: str) -> str:
    body = (text or "").strip()
    if not body.startswith("```"):
        return body
    rest = body.split("\n", 1)[-1] if "\n" in body else ""
    rest = rest.strip()
    if rest.endswith("```"):
        rest = rest[: -3].rstrip()
    return rest or body


def _raw_decode_dict(text: str, idx: int) -> dict[str, Any] | None:
    try:
        obj, _ = json.JSONDecoder().raw_decode(text, idx)
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def _repair_fragment(frag: str) -> str:
    in_str = False
    escape = False
    stack: list[str] = []
    for ch in frag:
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]":
            if stack and stack[-1] == ch:
                stack.pop()
    out = frag
    if escape:
        out = out[:-1] if out.endswith("\\") else out
        in_str = True
    if in_str:
        out += '"'
    out = re.sub(r",[ \t\r\n]*$", "", out.rstrip())
    if out.rstrip().endswith(":"):
        out += ' ""'
    while stack:
        out += stack.pop()
    return out


def _decode_repaired(text: str, idx: int) -> dict[str, Any] | None:
    obj = _raw_decode_dict(text, idx)
    if obj is not None:
        return obj
    repaired = _repair_fragment(text[idx:])
    return _raw_decode_dict(repaired, 0)


def _object_score(obj: dict[str, Any]) -> int:
    score = 0
    keys = {str(k) for k in obj.keys()}
    if keys & _TOOL_NAMES or "tool" in keys:
        score += 8
    if "args" in keys or "board_update" in keys or "files" in keys:
        score += 4
    if keys & {"path", "file", "script", "filename", "content"}:
        score += 2
    if any(str(k).endswith(tuple(WRITE_EXT)) for k in keys):
        score += 3
    return score


def parse_committee_json(raw: str) -> dict[str, Any]:
    text = _unwrap_fences(raw or "").replace("\\'", "'")
    if not text:
        return {}
    first = text.find("{")
    if first < 0:
        return {}
    primary = _decode_repaired(text, first)
    if primary is not None and _object_score(primary) >= 8:
        return primary
    found: list[tuple[int, dict[str, Any]]] = []
    if primary is not None:
        found.append((_object_score(primary), primary))
    i = text.find("{", first + 1)
    while i >= 0:
        obj = _decode_repaired(text, i)
        if obj is not None:
            found.append((_object_score(obj), obj))
        i = text.find("{", i + 1)
    if not found:
        return {}
    found.sort(key=lambda item: item[0], reverse=True)
    return found[0][1]


def json_is_complete_object(raw: str) -> bool:
    text = _unwrap_fences(raw or "").replace("\\'", "'")
    i = text.find("{")
    if i < 0:
        return False
    try:
        obj, end = json.JSONDecoder().raw_decode(text, i)
    except json.JSONDecodeError:
        return False
    if not isinstance(obj, dict):
        return False
    tail = text[end:].strip()
    return not tail or tail.startswith("```")


def _rel_path(args: dict[str, Any] | None) -> str:
    if not isinstance(args, dict):
        return ""
    for key in _PATH_KEYS:
        val = args.get(key)
        if val not in (None, ""):
            return str(val).strip().replace("\\", "/").lstrip("/")
    name = args.get("name")
    if name not in (None, "") and "." in str(name):
        return str(name).strip().replace("\\", "/").lstrip("/")
    return ""


def is_test_script(rel: str) -> bool:
    raw = str(rel or "").replace("\\", "/").lstrip("/")
    if not raw or raw.startswith("..") or ".." in Path(raw).parts:
        return False
    path = Path(raw)
    if path.suffix.lower() != ".py":
        return False
    stem = path.stem.lower()
    return stem.startswith("test_") or stem.endswith("_test")


def is_main_script(rel: str) -> bool:
    return Path(str(rel or "").replace("\\", "/")).name.lower() == MAIN_FILE


def list_lib_scripts(box: Sandbox, cap: int = 80) -> list[str]:
    return [name for name in list_impl_scripts(box, cap) if not is_main_script(name)]


def list_test_scripts(box: Sandbox, cap: int = 80) -> list[str]:
    listing = box.listing(cap)
    if listing in {"", "(empty)"}:
        return []
    return [ln.strip() for ln in listing.splitlines() if is_test_script(ln.strip())]


def list_impl_scripts(box: Sandbox, cap: int = 80) -> list[str]:
    listing = box.listing(cap)
    if listing in {"", "(empty)"}:
        return []
    out: list[str] = []
    for ln in listing.splitlines():
        name = ln.strip()
        if not name.lower().endswith(".py"):
            continue
        if is_test_script(name):
            continue
        out.append(name)
    return out


def _fmt_sig(node: ast.AST) -> str:
    if isinstance(node, ast.ClassDef):
        return node.name
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = [a.arg for a in node.args.args if a.arg != "self"]
        return f"{node.name}({', '.join(args)})"
    return ""


def _py_symbols(text: str) -> list[str]:
    try:
        tree = ast.parse(str(text or ""))
    except SyntaxError:
        return []
    names: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(node.name)
    return names


def _py_sigs(text: str) -> dict[str, str]:
    try:
        tree = ast.parse(str(text or ""))
    except SyntaxError:
        return {}
    out: dict[str, str] = {}
    for node in tree.body:
        sig = _fmt_sig(node)
        if sig:
            out[node.name] = sig
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if child.name.startswith("_"):
                        continue
                    args = [a.arg for a in child.args.args if a.arg != "self"]
                    out[f"{node.name}.{child.name}"] = f"{node.name}.{child.name}({', '.join(args)})"
    return out


def _main_calls(text: str) -> list[str]:
    try:
        tree = ast.parse(str(text or ""))
    except SyntaxError:
        return []
    out: list[str] = []

    def add(item: str) -> None:
        if item and item not in out:
            out.append(item)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            add(func.id + "()")
        elif isinstance(func, ast.Attribute):
            add(func.attr)
    return out


def _compile_py(content: str) -> str | None:
    try:
        compile(str(content or ""), "<test>", "exec")
    except SyntaxError as exc:
        return f"{exc.msg} (line {exc.lineno})"
    return None


def _has_literal_scores(content: str) -> bool:
    blob = str(content or "")
    if _SCORES_LITERAL.search(blob):
        return True
    try:
        tree = ast.parse(blob)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _SCORES_LITERAL.search(node.value):
                return True
        if isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            only_const = True
            for val in node.values:
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    parts.append(val.value)
                else:
                    only_const = False
                    break
            if only_const and _SCORES_LITERAL.search("".join(parts)):
                return True
    return False


def build_inventory(box: Sandbox) -> dict[str, Any]:
    listing = box.listing()
    files = [] if listing in {"", "(empty)"} else [ln.strip() for ln in listing.splitlines() if ln.strip()]
    symbols: dict[str, list[str]] = {}
    sigs: dict[str, dict[str, str]] = {}
    for name in files:
        if not name.lower().endswith(".py"):
            continue
        path = box.resolve(name)
        if path is None or not path.is_file():
            continue
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        symbols[name] = _py_symbols(body)
        sigs[name] = _py_sigs(body)
    return {"files": files, "symbols": symbols, "sigs": sigs}


def impl_snapshot(box: Sandbox) -> dict[str, Any]:
    raw = build_inventory(box)
    files = [name for name in (raw.get("files") or []) if not is_test_script(name)]
    symbols = {
        name: list(names)
        for name, names in (raw.get("symbols") or {}).items()
        if not is_test_script(name)
    }
    sigs = {
        name: dict(val)
        for name, val in (raw.get("sigs") or {}).items()
        if not is_test_script(name)
    }
    main_calls: list[str] = []
    main_path = box.resolve(MAIN_FILE)
    if main_path is not None and main_path.is_file():
        try:
            main_calls = _main_calls(main_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            main_calls = []
    return {
        "files": files,
        "symbols": symbols,
        "sigs": sigs,
        "test_files": list_test_scripts(box),
        "main_calls": main_calls,
    }


def _name_set(mapping: dict[str, list[str]] | None) -> set[str]:
    return {str(n) for names in (mapping or {}).values() for n in names}


def merge_inventory(board: Board, snap: dict[str, Any]) -> dict[str, Any]:
    live_files = list(snap.get("files") or [])
    live_syms = {str(k): list(v) for k, v in (snap.get("symbols") or {}).items()}
    live_sigs = {str(k): dict(v) for k, v in (snap.get("sigs") or {}).items()}
    tests = list(snap.get("test_files") or [])
    main_calls = [str(x) for x in (snap.get("main_calls") or [])]
    prev = board.inventory or {}
    if not prev.get("locked"):
        inv = {
            "locked": True,
            "files": live_files,
            "symbols": live_syms,
            "sigs": live_sigs,
            "locked_files": list(live_files),
            "locked_symbols": {k: list(v) for k, v in live_syms.items()},
            "added": {k: list(v) for k, v in live_syms.items() if v},
            "removed": {},
            "test_files": tests,
            "main_calls": main_calls,
        }
        board.inventory = inv
        return inv
    locked_files = list(prev.get("locked_files") or [])
    locked_syms = {str(k): list(v) for k, v in (prev.get("locked_symbols") or {}).items()}
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}
    for name in live_files:
        live_names = live_syms.get(name) or []
        if name not in locked_files:
            locked_files.append(name)
            locked_syms[name] = list(live_names)
            if live_names:
                added[name] = list(live_names)
            continue
        lock_names = locked_syms.setdefault(name, [])
        for sym in live_names:
            if sym not in lock_names:
                lock_names.append(sym)
                added.setdefault(name, []).append(sym)
        gone = [sym for sym in lock_names if sym not in live_names]
        if gone:
            removed[name] = gone
    for name in locked_files:
        if name not in live_files:
            removed.setdefault(name, list(locked_syms.get(name) or []))
    inv = {
        "locked": True,
        "files": live_files,
        "symbols": live_syms,
        "sigs": live_sigs,
        "locked_files": locked_files,
        "locked_symbols": locked_syms,
        "added": added,
        "removed": removed,
        "test_files": tests,
        "main_calls": main_calls,
    }
    board.inventory = inv
    return inv


_TEST_SKIP_NAMES = frozenset(
    {
        "print",
        "len",
        "range",
        "list",
        "dict",
        "set",
        "tuple",
        "int",
        "float",
        "str",
        "bool",
        "abs",
        "min",
        "max",
        "sum",
        "open",
        "enumerate",
        "zip",
        "map",
        "filter",
        "sorted",
        "reversed",
        "any",
        "all",
        "next",
        "iter",
        "round",
        "isinstance",
        "issubclass",
        "hasattr",
        "getattr",
        "setattr",
        "delattr",
        "type",
        "super",
        "object",
        "property",
        "staticmethod",
        "classmethod",
        "Exception",
        "BaseException",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "RuntimeError",
        "StopIteration",
        "AssertionError",
        "OSError",
        "FileNotFoundError",
        "ImportError",
        "ModuleNotFoundError",
        "AttributeError",
        "NameError",
        "ZeroDivisionError",
        "NotImplementedError",
        "TimeoutError",
        "True",
        "False",
        "None",
        "NotImplemented",
        "id",
        "hash",
        "repr",
        "ascii",
        "format",
        "vars",
        "dir",
        "callable",
        "chr",
        "ord",
        "hex",
        "oct",
        "bin",
        "pow",
        "divmod",
        "slice",
        "bytearray",
        "bytes",
        "complex",
        "frozenset",
        "input",
        "eval",
        "exec",
        "compile",
        "__name__",
        "__file__",
        "__doc__",
        "main",
    }
)


def _live_modules(inv: dict[str, Any] | None) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for fname, names in ((inv or {}).get("symbols") or {}).items():
        if is_main_script(fname):
            continue
        stem = Path(str(fname)).stem
        if not stem:
            continue
        out.setdefault(stem, set()).update(str(n) for n in names)
    return out


def unknown_live_calls(content: str, inv: dict[str, Any] | None) -> list[str]:
    modules = _live_modules(inv)
    if not modules:
        return []
    live_all = {name for names in modules.values() for name in names} | set(modules)
    try:
        tree = ast.parse(str(content or ""))
    except SyntaxError:
        return []
    local: set[str] = set()
    aliases: dict[str, str] = {}
    ok_names: set[str] = set()
    unknown: list[str] = []

    def mark(item: str) -> None:
        if item not in unknown:
            unknown.append(item)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(node.name)
        elif isinstance(node, ast.arg):
            local.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            local.add(node.id)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                stem = str(alias.name or "").split(".")[0]
                asname = alias.asname or stem
                if not asname:
                    continue
                if stem in modules:
                    aliases[asname] = stem
                ok_names.add(asname)
        elif isinstance(node, ast.ImportFrom):
            if not node.module or node.level:
                continue
            stem = str(node.module).split(".")[0]
            if stem in modules:
                live = modules[stem]
                for alias in node.names:
                    if alias.name == "*":
                        ok_names.update(live)
                        continue
                    asname = alias.asname or alias.name
                    if alias.name not in live:
                        mark(f"{stem}.{alias.name}")
                    elif asname:
                        ok_names.add(asname)
            else:
                for alias in node.names:
                    ok_names.add(alias.asname or alias.name)

    allowed = live_all | local | ok_names | _TEST_SKIP_NAMES | set(aliases)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            if func.id not in allowed:
                mark(func.id)
        elif isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            stem = aliases.get(func.value.id)
            if stem and func.attr not in modules.get(stem, set()):
                mark(f"{stem}.{func.attr}")
    return unknown


def _live_hint(inv: dict[str, Any] | None) -> str:
    inv = inv or {}
    bits: list[str] = []
    sigs = inv.get("sigs") or {}
    for fname in inv.get("files") or []:
        bits.append(_line_names(fname, (inv.get("symbols") or {}).get(fname) or [], sigs))
    return "; ".join(bits) if bits else "(none)"


def _live_call_denied(rel: str, content: str, inv: dict[str, Any] | None) -> dict[str, Any] | None:
    bad = unknown_live_calls(content, inv)
    if not bad:
        return None
    hint = (
        "call only live names: "
        + _live_hint(inv)
        + ". not live: "
        + ", ".join(bad[:12])
        + ". Do not invent APIs or copy the impl into the test."
    )
    return {
        "ok": False,
        "error": "live_name_required",
        "path": rel,
        "unknown": bad[:12],
        "hint": hint[:800],
    }


def _line_names(fname: str, names: list[str], sigs: dict[str, dict[str, str]] | None = None) -> str:
    file_sigs = (sigs or {}).get(fname) or {}
    shown = [file_sigs.get(n) or n for n in names]
    extra = [file_sigs[k] for k in file_sigs if "." in k]
    bits = shown + [x for x in extra if x not in shown]
    return f"{fname}: " + (", ".join(bits) if bits else "(no top-level defs)")


def inventory_text(inv: dict[str, Any] | None, *, hide_tests: bool = False) -> str:
    inv = inv or {}
    live_files = inv.get("files") or []
    live_syms = inv.get("symbols") or {}
    locked_files = inv.get("locked_files") or live_files
    locked_syms = inv.get("locked_symbols") or live_syms
    sigs = inv.get("sigs") or {}
    tests = [] if hide_tests else (inv.get("test_files") or [])
    lines = [
        "call only live names (implementation files). Do not invent other functions or reimplement them in the test.",
        "tests: " + ("(hidden from coder)" if hide_tests else (", ".join(tests) if tests else "(none)")),
        "main.py calls: " + (", ".join(inv.get("main_calls") or []) or "(none — coder must write main.py)"),
        "locked:",
    ]
    if locked_files:
        for fname in locked_files:
            lines.append(_line_names(fname, locked_syms.get(fname) or [], sigs))
    else:
        lines.append("(none)")
    added = inv.get("added") or {}
    removed = inv.get("removed") or {}
    add_bits = [f"{k}: {', '.join(v)}" for k, v in added.items() if v]
    rem_bits = [f"{k}: {', '.join(v)}" for k, v in removed.items() if v]
    lines.append("this_round: added " + ("; ".join(add_bits) if add_bits else "(none)")
                 + "; removed " + ("; ".join(rem_bits) if rem_bits else "(none)"))
    lines.append("live:")
    if live_files:
        for fname in live_files:
            lines.append(_line_names(fname, live_syms.get(fname) or [], sigs))
    else:
        lines.append("(none)")
    return "\n".join(lines)


def _role_path_lock(role: str, rel: str, box: Sandbox | None = None) -> dict[str, Any] | None:
    if role == "tester":
        if is_test_script(rel):
            return None
        tests = list_test_scripts(box) if box is not None else []
        hint = "tester may only write/execute test_*.py or *_test.py"
        if tests:
            hint += f"; existing tests: {', '.join(tests)} — execute those"
        else:
            hint += "; write test_<name>.py then execute it"
        return {"ok": False, "error": "tester_test_only", "path": rel, "hint": hint}
    if role == "coder" and is_test_script(rel):
        return {
            "ok": False,
            "error": "coder_impl_only",
            "path": rel,
            "hint": "coder may not read, write, or execute test_*.py; tester owns tests",
        }
    return None


def _main_snippet(box: Sandbox, cap: int = 1600) -> str:
    path = box.resolve(MAIN_FILE)
    if path is None or not path.is_file():
        return f"(missing {MAIN_FILE} — wait for coder smoke)"
    try:
        body = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return f"(unreadable {MAIN_FILE})"
    body = body.strip()
    if not body:
        return f"({MAIN_FILE} is empty)"
    if len(body) <= cap:
        return body
    return body[: cap - 1] + "…"


def _is_placeholder_content(content: str) -> bool:
    body = str(content or "").strip()
    marks = {
        "",
        "...",
        "…",
        WRITE_CONTENT_PLACEHOLDER,
        WRITE_CONTENT_PLACEHOLDER.lower(),
        "<full test source>",
        "<full source>",
        "<code>",
        '"..."',
        "'...'",
    }
    return body in marks


def _placeholder_write_denied(rel: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": "placeholder_content",
        "path": rel,
        "hint": (
            f"args.content must be the full file source, not {WRITE_CONTENT_PLACEHOLDER!r} or '...'. "
            "Do not put the code only in a markdown fence."
        ),
    }


def _test_script_issues(content: str) -> tuple[str | None, list[str]]:
    body = str(content or "")
    syn = _compile_py(body)
    if syn:
        return "syntax_error", [f"test does not compile: {syn}"]
    if _has_literal_scores(body):
        return (
            "literal_scores",
            ["each SCORES value must be computed from a trial; never hardcode a 1,1,1 list"],
        )
    if not _SCORES_PRINT.search(body):
        return (
            "scores_print_required",
            ["test must print ASCII SCORES metric=v1,v2,... even when trials fail"],
        )
    warns: list[str] = []
    if _TEST_ABORT.search(body):
        warns.append(
            "do not assert or sys.exit before printing SCORES; use 0/1 per trial so scores still print"
        )
    return None, warns


def _auto_timeout(board: Board) -> int:
    for row in board.targets or []:
        if str(row.get("metric") or "") in {"fruit_points", "fruit"}:
            return min(600, EXECUTE_TIMEOUT_MAX)
    return EXECUTE_TIMEOUT


def _impl_listing(box: Sandbox) -> str:
    listing = box.listing()
    if listing in {"", "(empty)"}:
        return listing
    rows = [ln.strip() for ln in listing.splitlines() if ln.strip() and not is_test_script(ln.strip())]
    return "\n".join(rows) if rows else "(empty)"


def _norm_rel(rel: str) -> str:
    return str(rel or "").replace("\\", "/").lstrip("/")


def _finish_execute(
    ctx: "_Ctx",
    rel: str,
    timeout: int,
    result: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    stdout = str(result.get("stdout") or "")
    parsed = parse_score_blob(stdout)
    if parsed:
        ingest_scores(ctx.board, stdout)
    path = _norm_rel(rel)
    ctx.round_executes += 1
    ctx.executed_paths.add(path)
    ctx.last_execute_path = path
    ctx.last_execute_stderr = str(result.get("stderr") or result.get("error") or "")[:1000]
    ctx.last_has_scores = bool(parsed)
    ctx.last_execute_kind = _classify_execute(ctx, rel, result, parsed)
    if ctx.last_execute_kind == "harness_ok":
        ctx.board.harness_ok = True
        ctx.board.scored_ok = True
        ctx.need_test_rewrite = False
    elif ctx.last_execute_kind == "impl_crash":
        ctx.board.harness_ok = True
        ctx.board.scored_ok = False
        ctx.need_test_rewrite = False
        ctx.crash_lock = _crash_lock_file(ctx, stderr=str(result.get("stderr") or ""))
    elif ctx.last_execute_kind == "test_broken":
        ctx.board.harness_ok = False
        ctx.board.scored_ok = False
        ctx.need_test_rewrite = True
    out = dict(result)
    err = str(result.get("error") or "")
    if not parsed:
        if err == "bad_script":
            out["hint"] = (
                "that path is not on disk. sandbox_write the test file first, then execute args.path."
            )
        elif err == "timeout":
            out["hint"] = (
                "timeout with no SCORES. Wrap each trial in try/except/finally and print "
                "SCORES metric=0,0,... (n zeros) before returning. No unbounded loops."
            )
        else:
            out["hint"] = (
                "stdout had no SCORES line. Print ASCII SCORES metric=v1,v2,v3 "
                "with n comma-separated trial values (no brackets, not a total). "
                "Do not assert or sys.exit before that print."
            )
    elif ctx.last_execute_kind == "test_broken":
        out["hint"] = (
            "SCORES must list n comma-separated trial values, not a single total. "
            "Rewrite the test, then execute once."
        )
    ctx.session.append(
        "test",
        event="auto_execute" if source == "auto" else "execute",
        round=ctx.board.round,
        path=path,
        ok=result.get("ok"),
        error=result.get("error"),
        code=result.get("code"),
        timeout=timeout,
        source=source,
        stdout=_clip_log(stdout, 2000),
        stderr=_clip_log(result.get("stderr") or "", 1000),
        parsed_scores=parsed,
        has_scores=bool(parsed),
        kind=ctx.last_execute_kind,
    )
    if out.get("hint"):
        ctx.last_execute_stderr = (ctx.last_execute_stderr + " | " + str(out["hint"]))[:1000]
    return out


def _auto_execute_tests(ctx: "_Ctx") -> None:
    if ctx.round_executes > 0:
        return
    tests = list_test_scripts(ctx.box)
    if not tests:
        ctx.last_execute_kind = "no_execute"
        ctx.session.append(
            "test",
            event="no_execute",
            round=ctx.board.round,
            files=ctx.box.listing(),
        )
        return
    timeout = _auto_timeout(ctx.board)
    for rel in tests:
        if _stopped(ctx.stop_event):
            break
        body = ""
        resolved = ctx.box.resolve(rel)
        if resolved is not None and resolved.is_file():
            try:
                body = resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:
                body = ""
        issue, warns = _test_script_issues(body)
        if issue:
            hint = "; ".join(warns) if warns else issue
            ctx.last_execute_kind = "test_broken"
            ctx.last_execute_path = _norm_rel(rel)
            ctx.last_execute_stderr = hint
            ctx.board.harness_ok = False
            ctx.board.scored_ok = False
            ctx.need_test_rewrite = True
            ctx.session.append(
                "test",
                event="execute_denied",
                round=ctx.board.round,
                path=rel,
                error=issue,
                hint=hint,
                source="auto",
            )
            continue
        live_denied = _live_call_denied(rel, body, ctx.board.inventory)
        if live_denied:
            ctx.last_execute_kind = "test_broken"
            ctx.last_execute_path = _norm_rel(rel)
            ctx.last_execute_stderr = str(live_denied.get("hint") or "live_name_required")
            ctx.board.harness_ok = False
            ctx.board.scored_ok = False
            ctx.need_test_rewrite = True
            ctx.session.append(
                "test",
                event="execute_denied",
                round=ctx.board.round,
                path=rel,
                error=live_denied.get("error"),
                hint=live_denied.get("hint"),
                unknown=live_denied.get("unknown"),
                source="auto",
            )
            continue
        raw = ctx.box.execute(rel, timeout)
        _finish_execute(ctx, rel, timeout, raw, source="auto")


def _smoke_one(box: Sandbox, rel: str, timeout: int) -> dict[str, Any]:
    path = box.resolve(rel)
    if path is None or not path.is_file() or path.suffix.lower() != ".py":
        return {"ok": False, "error": "bad_script", "stderr": "bad_script", "path": rel}
    if is_main_script(rel):
        cmd = [sys_executable(), str(path)]
    else:
        loader = (
            "import importlib.util, sys\n"
            f"p = {str(path)!r}\n"
            "spec = importlib.util.spec_from_file_location('_usb_smoke', p)\n"
            "if spec is None or spec.loader is None:\n"
            "    raise ImportError('bad spec')\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "sys.modules['_usb_smoke'] = mod\n"
            "spec.loader.exec_module(mod)\n"
        )
        cmd = [sys_executable(), "-c", loader]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(box.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout or SMOKE_TIMEOUT)),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "stderr": "timeout", "stdout": "", "path": rel}
    except OSError as exc:
        return {"ok": False, "error": str(exc), "stderr": str(exc), "path": rel}
    ok = proc.returncode == 0
    return {
        "ok": ok,
        "error": "" if ok else "smoke_fail",
        "code": proc.returncode,
        "stdout": (proc.stdout or "")[:4000],
        "stderr": (proc.stderr or "")[:4000],
        "path": rel,
    }


def _auto_smoke_impl(ctx: "_Ctx") -> None:
    impls = list_impl_scripts(ctx.box)
    libs = list_lib_scripts(ctx.box)
    ctx.board.smoke_ok = False
    ctx.board.smoke_detail = ""
    if not impls:
        ctx.last_smoke_path = ""
        ctx.last_smoke_stderr = "no implementation .py"
        ctx.board.smoke_detail = "no implementation .py"
        ctx.session.append(
            "test",
            event="smoke",
            round=ctx.board.round,
            ok=False,
            error="no_impl",
            files=ctx.box.listing(),
        )
        return
    for rel in libs:
        if _stopped(ctx.stop_event):
            ctx.last_smoke_path = rel
            ctx.last_smoke_stderr = "stopped"
            ctx.board.smoke_detail = "stopped"
            return
        raw = _smoke_one(ctx.box, rel, SMOKE_TIMEOUT)
        ctx.session.append(
            "test",
            event="smoke",
            round=ctx.board.round,
            path=rel,
            ok=raw.get("ok"),
            error=raw.get("error"),
            code=raw.get("code"),
            stdout=_clip_log(raw.get("stdout") or "", 800),
            stderr=_clip_log(raw.get("stderr") or "", 1000),
        )
        if not raw.get("ok"):
            err = str(raw.get("stderr") or raw.get("error") or "smoke_fail")[:1000]
            ctx.last_smoke_path = rel
            ctx.last_smoke_stderr = err
            ctx.board.smoke_detail = f"{rel}: " + err[:400]
            return
    main_path = ctx.box.resolve(MAIN_FILE)
    if main_path is None or not main_path.is_file():
        ctx.last_smoke_path = MAIN_FILE
        ctx.last_smoke_stderr = f"{MAIN_FILE} missing — write {MAIN_FILE} that imports libs and calls them"
        ctx.board.smoke_detail = ctx.last_smoke_stderr
        ctx.session.append(
            "test",
            event="smoke",
            round=ctx.board.round,
            path=MAIN_FILE,
            ok=False,
            error="no_main",
            files=ctx.box.listing(),
        )
        return
    if _stopped(ctx.stop_event):
        ctx.last_smoke_path = MAIN_FILE
        ctx.last_smoke_stderr = "stopped"
        ctx.board.smoke_detail = "stopped"
        return
    raw = _smoke_one(ctx.box, MAIN_FILE, SMOKE_TIMEOUT)
    ctx.session.append(
        "test",
        event="smoke",
        round=ctx.board.round,
        path=MAIN_FILE,
        ok=raw.get("ok"),
        error=raw.get("error"),
        code=raw.get("code"),
        stdout=_clip_log(raw.get("stdout") or "", 800),
        stderr=_clip_log(raw.get("stderr") or "", 1000),
    )
    if not raw.get("ok"):
        err = str(raw.get("stderr") or raw.get("error") or "smoke_fail")[:1000]
        ctx.last_smoke_path = MAIN_FILE
        ctx.last_smoke_stderr = err
        ctx.board.smoke_detail = f"{MAIN_FILE}: " + err[:400]
        return
    shown = libs + [MAIN_FILE]
    ctx.board.smoke_ok = True
    ctx.last_smoke_path = MAIN_FILE
    ctx.last_smoke_stderr = ""
    ctx.board.smoke_detail = "ok " + ", ".join(shown)


def _run_coder_phase(ctx: "_Ctx") -> None:
    ctx.board.smoke_ok = False
    ctx.board.smoke_detail = ""
    for cycle in range(1, CODER_INNER_MAX + 1):
        if _stopped(ctx.stop_event):
            return
        ctx.executed_paths = set()
        _turn(ctx, "coder", "code")
        _auto_smoke_impl(ctx)
        ctx.session.append(
            "test",
            event="coder_loop",
            round=ctx.board.round,
            cycle=cycle,
            smoke_ok=ctx.board.smoke_ok,
            path=ctx.last_smoke_path,
            detail=ctx.board.smoke_detail,
        )
        if ctx.board.smoke_ok:
            _sync_inventory(ctx)
            return


def _trace_hits(stderr: str) -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for match in _TRACE_FILE.finditer(str(stderr or "")):
        raw = match.group(1)
        try:
            line = int(match.group(2))
        except ValueError:
            line = 0
        out.append((Path(raw).name, line, raw))
    return out


def _scores_cover_n(board: Board, parsed: dict[str, list[float]]) -> bool:
    if not parsed:
        return False
    for row in board.targets or []:
        metric = str(row.get("metric") or "")
        try:
            need = int(row.get("n") or 0)
        except (TypeError, ValueError):
            need = 0
        got = parsed.get(metric) or []
        if metric and need and len(got) >= need:
            return True
    return False


def _classify_execute(ctx: "_Ctx", rel: str, result: dict[str, Any], parsed: dict[str, list[float]]) -> str:
    err = str(result.get("error") or "")
    stderr = str(result.get("stderr") or "")
    if err in {"bad_script", "timeout"}:
        return "test_broken"
    if _scores_cover_n(ctx.board, parsed):
        return "harness_ok"
    if _ATTR_MODULE.search(stderr):
        return "impl_crash"
    hits = _trace_hits(stderr)
    last_name = hits[-1][0] if hits else ""
    if "ModuleNotFoundError" in stderr or "ImportError" in stderr:
        return "impl_crash"
    if last_name and not is_test_script(last_name):
        return "impl_crash"
    if last_name and is_test_script(last_name):
        return "test_broken"
    return "test_broken"


def _eval_packet(ctx: "_Ctx") -> str:
    tests = list_test_scripts(ctx.box)
    listing = ctx.box.listing()
    names = [] if listing in {"", "(empty)"} else [ln.strip() for ln in listing.splitlines() if ln.strip()]
    impl = [name for name in names if not is_test_script(name)]
    lines = [
        f"kind={ctx.last_execute_kind or '-'}",
        f"smoke_ok={ctx.board.smoke_ok}",
        f"smoke={ctx.board.smoke_detail or '-'}",
        f"qualified={ctx.board.qualified}",
        f"qualify={ctx.board.qualify_detail or '-'}",
        f"impl={', '.join(impl) or '(none)'}",
        f"tests={', '.join(tests) or '(none)'}",
        f"scores={json.dumps(ctx.board.trial_scores, ensure_ascii=True)}",
        f"gap={json.dumps(_score_gap(ctx.board), ensure_ascii=True)}",
        "inventory:\n" + inventory_text(ctx.board.inventory),
        "Results outrank code. Do not invent metric values.",
    ]
    if ctx.board.data_card:
        lines.append("data_card:\n" + ctx.board.data_card[:800])
    if ctx.last_execute_stderr:
        lines.append("stderr=" + ctx.last_execute_stderr[:400])
    if ctx.crash_lock:
        lines.append("crash_lock=" + ctx.crash_lock)
    if ctx.last_write_denied:
        lines.append(f"write_denied={ctx.last_write_denied} err={ctx.last_write_denied_error}")
    return "\n".join(lines)


def _make_critique(
    item_id: str,
    owner: str,
    file: str,
    problem: str,
    fix: str,
) -> CritiqueItem:
    bits = [x for x in (f"owner={owner}" if owner else "", f"file={file}" if file else "", problem) if x]
    if fix:
        bits.append("fix: " + fix)
    return CritiqueItem(
        item_id=item_id,
        text="; ".join(bits),
        status="open",
        owner=owner,
        file=file,
        problem=problem,
        fix=fix,
    )


def _host_critique_items(ctx: "_Ctx") -> list[CritiqueItem]:
    items: list[CritiqueItem] = []
    tests = list_test_scripts(ctx.box)
    kind = ctx.last_execute_kind or "no_execute"
    n = 1

    def add(owner: str, file: str, problem: str, fix: str) -> None:
        nonlocal n
        items.append(_make_critique(f"host-{n}", owner, file, problem, fix))
        n += 1

    if not ctx.board.smoke_ok:
        add(
            "coder",
            ctx.last_smoke_path or "",
            (ctx.last_smoke_stderr or ctx.board.smoke_detail or "impl did not compile/import")[:300],
            "fix implementation so it compile+imports; do not write tests; tester waits until smoke_ok",
        )
        if ctx.last_write_denied and ctx.last_write_denied_error == "coder_impl_only":
            add(
                "coder",
                ctx.last_write_denied,
                "coder_impl_only: coder wrote a test path",
                "write implementation files only; tester owns tests",
            )
        return items
    if not tests:
        add(
            "tester",
            "test_*.py",
            "no test script in the work folder",
            "write test_*.py that prints SCORES metric=v1,v2,... then execute",
        )
    elif kind == "no_execute":
        add("tester", tests[0], "tests exist but were not executed", f"execute {tests[0]} and print SCORES")
    elif kind == "test_broken":
        add(
            "tester",
            ctx.last_execute_path or tests[0],
            (ctx.last_execute_stderr or "test did not print n SCORES values")[:300],
            "fix the test harness only; print SCORES even when trials fail; do not weaken cases",
        )
    elif kind == "impl_crash":
        fname = ctx.crash_lock or ""
        if not fname:
            hits = _trace_hits(ctx.last_execute_stderr)
            for name, _line, _raw in reversed(hits):
                if name and not is_test_script(name):
                    fname = name
                    break
        add(
            "coder",
            fname,
            (ctx.last_execute_stderr or "implementation crashed")[:300],
            f"sandbox_write {fname or 'the impl file'} first; do not change tests",
        )
    if ctx.board.qualify_detail and not ctx.board.qualified and kind in {"harness_ok", "impl_crash"}:
        add(
            "coder",
            "",
            ctx.board.qualify_detail,
            "change impl so trial metrics meet locked targets; do not weaken tests",
        )
    if ctx.last_write_denied and ctx.last_write_denied_error == "tester_test_only":
        add(
            "tester",
            ctx.last_write_denied,
            "tester_test_only: tester wrote an impl path",
            "write or execute test_*.py only",
        )
    if ctx.last_write_denied and ctx.last_write_denied_error == "coder_impl_only":
        add(
            "coder",
            ctx.last_write_denied,
            "coder_impl_only: coder wrote a test path",
            "write implementation files only; tester owns tests",
        )
    if ctx.last_write_denied and ctx.last_write_denied_error == "scores_print_required":
        add(
            "tester",
            ctx.last_write_denied,
            "test write missing SCORES print",
            "print ASCII SCORES metric=v1,v2,... even when trials fail",
        )
    if not items and not ctx.board.qualified:
        add("tester", "", "qualify failed", "print valid SCORES; coder fixes impl from stderr")
    return items


def _merge_critiques(base: list[CritiqueItem], extra: list[CritiqueItem]) -> list[CritiqueItem]:
    seen: set[tuple[str, str, str]] = set()
    out: list[CritiqueItem] = []
    for item in list(base) + list(extra):
        key = (item.owner, item.file, (item.problem or item.text)[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _sync_next_fix(board: Board) -> None:
    rows: list[dict[str, Any]] = []
    for item in board.critiques:
        if item.status in {"discarded", "avoided", "implemented"}:
            continue
        owner = item.owner
        blob = (item.text or "").lower()
        if not owner:
            if item.file and is_test_script(item.file):
                owner = "tester"
            elif "tester" in blob:
                owner = "tester"
            else:
                owner = "coder"
        rows.append(
            {
                "id": item.item_id,
                "owner": owner,
                "file": item.file,
                "problem": item.problem or item.text,
                "fix": item.fix,
                "version": board.round,
            }
        )
    _append_next_fix(board, rows)


def _artifact_snippet(ctx: "_Ctx", radius: int = 12) -> tuple[str, str]:
    hits = _trace_hits(ctx.last_execute_stderr)
    if not hits:
        return "", ""
    name, line, _raw = hits[-1]
    rel = name
    path = ctx.box.resolve(rel)
    if path is None or not path.is_file():
        rel = ctx.last_execute_path
        path = ctx.box.resolve(rel) if rel else None
    if path is None or not path.is_file():
        return "", ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "", ""
    lo = max(0, int(line) - 1 - radius)
    hi = min(len(lines), int(line) + radius)
    body = "\n".join(f"{i + 1}|{lines[i]}" for i in range(lo, hi))
    return body[:2000], rel


def _run_tester_phase(ctx: "_Ctx") -> None:
    tests = list_test_scripts(ctx.box)
    execute_only = bool(
        ctx.board.round > 1
        and ctx.board.scored_ok
        and ctx.board.harness_ok
        and tests
        and ctx.last_execute_kind == "harness_ok"
        and not ctx.need_test_rewrite
    )
    if execute_only:
        ctx.round_executes = 0
        ctx.executed_paths = set()
        ctx.tester_wrote = False
        _auto_execute_tests(ctx)
        ctx.session.append(
            "test",
            event="execute_only",
            round=ctx.board.round,
            kind=ctx.last_execute_kind,
            files=ctx.box.listing(),
        )
        return
    for cycle in range(1, TESTER_INNER_MAX + 1):
        if _stopped(ctx.stop_event):
            return
        ctx.round_executes = 0
        ctx.executed_paths = set()
        ctx.tester_wrote = False
        _turn(ctx, "tester", "test")
        if ctx.round_executes == 0:
            if ctx.need_test_rewrite and not ctx.tester_wrote and list_test_scripts(ctx.box):
                ctx.session.append(
                    "test",
                    event="skip_auto_execute",
                    round=ctx.board.round,
                    cycle=cycle,
                    reason="rewrite_required",
                    path=ctx.last_execute_path,
                )
            else:
                _auto_execute_tests(ctx)
        kind = ctx.last_execute_kind or "no_execute"
        ctx.session.append(
            "test",
            event="tester_loop",
            round=ctx.board.round,
            cycle=cycle,
            kind=kind,
            path=ctx.last_execute_path,
        )
        if kind in {"harness_ok", "impl_crash"}:
            return


def _run_critique_phase(ctx: "_Ctx") -> None:
    host_items = _host_critique_items(ctx)
    tests = list_test_scripts(ctx.box)
    skip_llm = (
        (not ctx.board.smoke_ok)
        or (not tests)
        or ctx.last_execute_kind in {"no_execute", "test_broken", ""}
    )
    ctx.board.critiques = []
    if skip_llm:
        ctx.board.critiques = host_items
    else:
        _turn(ctx, "critique", "critique")
        model_items = list(ctx.board.critiques)
        ctx.board.critiques = _merge_critiques(host_items, model_items)
        snip, rel = _artifact_snippet(ctx)
        if snip and ctx.last_execute_kind == "impl_crash":
            ctx.artifact_snip = snip
            ctx.artifact_rel = rel
            before = list(ctx.board.critiques)
            _turn(ctx, "critique", "critique_artifact")
            ctx.board.critiques = _merge_critiques(before, ctx.board.critiques)


def _module_to_impl(ctx: "_Ctx", module: str) -> str:
    stem = str(module or "").split(".")[-1].strip()
    if not stem:
        return ""
    want = stem.lower()
    for name in list_impl_scripts(ctx.box):
        if Path(name).stem.lower() == want:
            return Path(name).name
    candidate = f"{stem}.py"
    path = ctx.box.resolve(candidate)
    if path is not None and path.is_file():
        return Path(candidate).name
    return ""


def _crash_lock_file(ctx: "_Ctx", stderr: str) -> str:
    match = _ATTR_MODULE.search(str(stderr or ""))
    if match:
        named = _module_to_impl(ctx, match.group(1))
        if named:
            return named
    hits = _trace_hits(stderr)
    for name, _line, _raw in reversed(hits):
        if name and not is_test_script(name):
            return name
    impls = list_impl_scripts(ctx.box)
    if len(impls) == 1:
        return Path(impls[0]).name
    return Path(impls[0]).name if impls else ""


def _refresh_inventory(ctx: "_Ctx") -> None:
    _sync_inventory(ctx)


def _sync_inventory(ctx: "_Ctx") -> None:
    snap = impl_snapshot(ctx.box)
    merge_inventory(ctx.board, snap)
    ctx.session.append(
        "test",
        event="inventory",
        round=ctx.board.round,
        inventory=ctx.board.inventory,
    )


def _done_packet(ctx: "_Ctx") -> str:
    discarded = [c.item_id for c in ctx.board.critiques if c.status == "discarded"]
    implemented = [c.item_id for c in ctx.board.critiques if c.status == "implemented"]
    lines = [
        f"files={ctx.box.listing()}",
        f"smoke_ok={ctx.board.smoke_ok}",
        f"harness_ok={ctx.board.harness_ok}",
        f"qualified={ctx.board.qualified}",
        f"scores={json.dumps(ctx.board.trial_scores, ensure_ascii=True)}",
        "inventory:\n" + inventory_text(ctx.board.inventory),
        "discarded=" + (",".join(discarded) if discarded else "(none)"),
        "implemented=" + (",".join(implemented) if implemented else "(none)"),
    ]
    if ctx.crash_lock:
        lines.append(f"crash_lock={ctx.crash_lock}")
    ctx.board.done_detail = "\n".join(lines)
    return ctx.board.done_detail


def _score_is_reject(score: str) -> bool:
    raw = str(score or "").strip().lower()
    if not raw:
        return False
    first = re.split(r"[\s,:/]+", raw, maxsplit=1)[0]
    return first in {"0", "false", "no", "discard", "discarded", "reject", "fake"} or "hallucin" in raw


def _apply_reject_scores(board: Board) -> None:
    for item in board.critiques:
        if item.status == "open" and _score_is_reject(item.score):
            item.status = "discarded"


def _absent_claim_present(board: Board, file: str, blob: str) -> bool:
    text = str(blob or "")
    if not _ABSENT_CLAIM.search(text):
        return False
    inv = board.inventory or {}
    file_names = {Path(str(f)).name.lower() for f in (
        list(inv.get("files") or []) + list(inv.get("locked_files") or []) + list(inv.get("test_files") or [])
    )}
    all_syms = sorted(
        _name_set(inv.get("symbols")) | _name_set(inv.get("locked_symbols")),
        key=len,
        reverse=True,
    )
    all_syms = [n for n in all_syms if len(n) >= 3]
    tests_exist = bool(inv.get("test_files")) or any(is_test_script(str(f)) for f in (inv.get("files") or []))
    lowered = text.lower()
    for sym in all_syms:
        if re.search(rf"\b{re.escape(sym.lower())}\b", lowered):
            return True
    fname = Path(file or "").name.lower()
    if fname and fname in file_names and re.search(r"\b(missing|does not exist|not found)\b", lowered):
        return True
    if tests_exist and re.search(r"\bno tests?(?: cases)?\b", lowered):
        return True
    return False


def _filter_critiques_inventory(board: Board) -> None:
    for item in board.critiques:
        if item.status != "open":
            continue
        blob = f"{item.file} {item.problem} {item.text} {item.fix}"
        if _absent_claim_present(board, item.file, blob):
            item.status = "discarded"
            if not item.score:
                item.score = "inventory"


def _prune_next_fix(board: Board) -> None:
    discarded = {
        (c.owner, c.file, (c.problem or c.text)[:80])
        for c in board.critiques
        if c.status == "discarded"
    }
    kept: list[dict[str, Any]] = []
    for row in board.next_fix:
        key = (
            str(row.get("owner") or ""),
            str(row.get("file") or ""),
            str(row.get("problem") or "")[:80],
        )
        if key in discarded:
            continue
        blob = f"{row.get('file')} {row.get('problem')} {row.get('fix')}"
        if _absent_claim_present(board, str(row.get("file") or ""), blob):
            continue
        kept.append(row)
    board.next_fix = kept


def _append_next_fix(board: Board, rows: list[dict[str, Any]]) -> None:
    seen: set[tuple[str, str, str]] = set()
    for existing in board.next_fix:
        seen.add(
            (
                str(existing.get("owner") or ""),
                str(existing.get("file") or ""),
                str(existing.get("problem") or "")[:80],
            )
        )
    for row in rows:
        key = (str(row.get("owner") or ""), str(row.get("file") or ""), str(row.get("problem") or "")[:80])
        if key in seen:
            continue
        seen.add(key)
        board.next_fix.append(row)


def _rel_content(args: dict[str, Any] | None) -> str:
    if not isinstance(args, dict):
        return ""
    for key in _CONTENT_KEYS:
        if key in args and args[key] is not None:
            return str(args[key])
    return ""


def _write_pairs_from_mapping(blob: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    path = _rel_path(blob)
    content = _rel_content(blob)
    if path and content:
        pairs.append((path, content))
    for key, value in blob.items():
        name = str(key).strip().replace("\\", "/").lstrip("/")
        if Path(name).suffix.lower() not in WRITE_EXT:
            continue
        if not isinstance(value, str):
            continue
        if any(existing == name for existing, _ in pairs):
            continue
        pairs.append((name, value))
    return pairs


def _actions_from_blob(name: str, blob: Any) -> list[tuple[str, dict[str, Any]]]:
    actions: list[tuple[str, dict[str, Any]]] = []
    if name not in _TOOL_NAMES:
        return actions
    if isinstance(blob, list):
        for item in blob:
            actions.extend(_actions_from_blob(name, item))
        return actions
    if not isinstance(blob, dict):
        return actions
    if name == "sandbox_write":
        for path, content in _write_pairs_from_mapping(blob):
            actions.append((name, {"path": path, "content": content}))
        return actions
    args = dict(blob)
    path = _rel_path(args)
    if path:
        args["path"] = path
    content = _rel_content(args)
    if content and "content" not in args:
        args["content"] = content
    actions.append((name, args))
    return actions


def _actions_from_fences(raw: str) -> list[tuple[str, dict[str, Any]]]:
    actions: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for lang, fname, body in _FENCE.findall(raw or ""):
        lang_l = str(lang or "").lower()
        if lang_l in {"json", ""}:
            continue
        text = str(body or "").strip("\n")
        if not text.strip():
            continue
        path = str(fname or "").strip().replace("\\", "/").lstrip("/")
        first = text.splitlines()[0].strip() if text.splitlines() else ""
        hash_name = _HASH_FILE.match(first)
        if hash_name and not path:
            path = hash_name.group(1)
            text = "\n".join(text.splitlines()[1:]).lstrip("\n")
        if not path or Path(path).suffix.lower() not in WRITE_EXT:
            continue
        if path in seen:
            continue
        seen.add(path)
        actions.append(("sandbox_write", {"path": path, "content": text}))
    return actions


def extract_tool_actions(parsed: dict[str, Any] | None, raw: str = "") -> list[tuple[str, dict[str, Any]]]:
    parsed = parsed or {}
    actions: list[tuple[str, dict[str, Any]]] = []
    tool = str(parsed.get("tool") or "").strip()
    args = parsed.get("args") if isinstance(parsed.get("args"), dict) else {}
    if tool in _TOOL_NAMES:
        if tool == "sandbox_write":
            actions.extend(_actions_from_blob(tool, args))
            if not actions:
                actions.extend(_actions_from_blob(tool, parsed))
        else:
            packed = dict(args)
            if _rel_path(parsed) and not _rel_path(packed):
                packed = {**parsed, **packed}
            actions.extend(_actions_from_blob(tool, packed))
    for name in _TOOL_NAMES:
        if name == tool:
            continue
        if name in parsed:
            actions.extend(_actions_from_blob(name, parsed.get(name)))
    files = parsed.get("files")
    if isinstance(files, dict):
        actions.extend(_actions_from_blob("sandbox_write", files))
    if not actions and (_rel_path(parsed) and _rel_content(parsed)):
        actions.extend(_actions_from_blob("sandbox_write", parsed))
    if not actions and any(str(k).endswith(tuple(WRITE_EXT)) for k in parsed.keys()):
        actions.extend(_actions_from_blob("sandbox_write", parsed))
    if not actions:
        actions.extend(_actions_from_fences(raw))
    deduped: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for name, args in actions:
        path = _rel_path(args)
        key = (name, path, _rel_content(args)[:80])
        if key in seen:
            continue
        seen.add(key)
        if path:
            args = {**args, "path": path}
        content = _rel_content(args)
        if content and "content" not in args:
            args = {**args, "content": content}
        deduped.append((name, args))
    return deduped


def yes_count(votes: dict[str, str]) -> int:
    return sum(1 for role in VOTING_ROLES if str(votes.get(role) or "").lower() in {"yes", "y", "ship"})


def should_commit(board: Board, votes: dict[str, str] | None = None) -> bool:
    ballots = votes if votes is not None else board.last_vote
    return bool(board.vote_open and board.qualified and yes_count(ballots) >= YES_FOR_COMMIT)


def _metric_key(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "", str(name or "").strip().lower().replace(" ", "_"))


def _is_vacuous_metric(name: str) -> bool:
    key = _metric_key(name)
    return not key or key in _VACUOUS_METRIC


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "").strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


def normalize_criteria(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        if isinstance(raw.get("criteria"), list):
            rows = raw["criteria"]
        elif "metric" in raw:
            rows = [raw]
        else:
            rows = [raw]
    elif isinstance(raw, list):
        rows = raw
    else:
        parsed = parse_committee_json(str(raw or ""))
        if parsed:
            return normalize_criteria(parsed)
        decoder = json.JSONDecoder()
        text = str(raw or "")
        i = text.find("[")
        while i >= 0:
            try:
                obj, _end = decoder.raw_decode(text, i)
            except json.JSONDecodeError:
                i = text.find("[", i + 1)
                continue
            if isinstance(obj, list):
                return normalize_criteria(obj)
            i = text.find("[", i + 1)
        return []
    out: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            continue
        metric = _metric_key(row.get("metric") or row.get("name") or row.get("id") or "")
        n_raw = row.get("n") if row.get("n") is not None else row.get("trials")
        try:
            n_val = int(n_raw)
        except (TypeError, ValueError):
            n_val = 0
        agg = str(row.get("aggregate") or row.get("agg") or "mean").strip().lower()
        op = str(row.get("op") or row.get("compare") or ">=").strip()
        value = _as_number(row.get("value") if row.get("value") is not None else row.get("threshold"))
        item = {
            "id": str(row.get("id") or f"{metric}_{agg}_{index}")[:80],
            "metric": metric,
            "n": n_val,
            "aggregate": agg,
            "op": op,
            "value": value if value is not None else 0.0,
        }
        out.append(item)
    return out


def criteria_valid(rows: list[dict[str, Any]]) -> bool:
    if len(rows) < 1:
        return False
    for row in rows:
        if _is_vacuous_metric(row.get("metric")):
            return False
        if int(row.get("n") or 0) < 2:
            return False
        if str(row.get("aggregate") or "") not in TARGET_AGGS:
            return False
        if str(row.get("op") or "") not in TARGET_OPS:
            return False
        if _as_number(row.get("value")) is None:
            return False
    return True


def extract_targets_from_text(text: str) -> list[dict[str, Any]]:
    blob = str(text or "")
    marker = re.search(r"TARGETS\s*:", blob, re.I)
    if marker:
        decoder = json.JSONDecoder()
        j = blob.find("[", marker.end())
        if j >= 0:
            try:
                obj, _end = decoder.raw_decode(blob, j)
                rows = normalize_criteria(obj)
                if criteria_valid(rows):
                    return rows
            except json.JSONDecodeError:
                pass
    return []


QUALITY_PRESETS: dict[str, list[dict[str, Any]]] = {
    "snake-dqn": [
        {"id": "fruit_mean", "metric": "fruit_points", "n": 5, "aggregate": "mean", "op": ">=", "value": 16},
        {"id": "fruit_min", "metric": "fruit_points", "n": 5, "aggregate": "min", "op": ">=", "value": 0},
    ],
    "maze-path": [
        {"id": "maze_mean", "metric": "maze_ok", "n": 8, "aggregate": "mean", "op": ">=", "value": 1},
    ],
    "csv-sql": [
        {"id": "csv_mean", "metric": "query_ok", "n": 6, "aggregate": "mean", "op": ">=", "value": 1},
    ],
    "expr-lang": [
        {"id": "expr_mean", "metric": "expr_ok", "n": 8, "aggregate": "mean", "op": ">=", "value": 1},
    ],
    "http-kv": [
        {"id": "kv_mean", "metric": "kv_ok", "n": 4, "aggregate": "mean", "op": ">=", "value": 1},
    ],
}

GENERIC_QUALITY = [
    {"id": "case_mean", "metric": "case_ok", "n": 4, "aggregate": "mean", "op": ">=", "value": 1},
]


def preset_targets_for_text(text: str) -> list[dict[str, Any]]:
    blob = str(text or "").lower()
    if "snake" in blob and ("dqn" in blob or "fruit" in blob):
        return [dict(row) for row in QUALITY_PRESETS["snake-dqn"]]
    if "maze" in blob and ("path" in blob or "bfs" in blob or "shortest" in blob):
        return [dict(row) for row in QUALITY_PRESETS["maze-path"]]
    if "csv" in blob and ("select" in blob or "query" in blob or "where" in blob):
        return [dict(row) for row in QUALITY_PRESETS["csv-sql"]]
    if ("expression" in blob and ("eval" in blob or "parentheses" in blob)) or "expr.py" in blob:
        return [dict(row) for row in QUALITY_PRESETS["expr-lang"]]
    if "kv" in blob or ("key-value" in blob or "key value" in blob) or "overwrite the same key" in blob:
        return [dict(row) for row in QUALITY_PRESETS["http-kv"]]
    return [dict(row) for row in GENERIC_QUALITY]


def _criterion_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_metric_key(row.get("metric")), str(row.get("aggregate") or "mean"))


def _is_stricter(old: dict[str, Any], new: dict[str, Any]) -> bool:
    if _criterion_key(old) != _criterion_key(new):
        return False
    if int(new.get("n") or 0) < int(old.get("n") or 0):
        return False
    op = str(old.get("op") or ">=")
    if str(new.get("op") or "") != op:
        return False
    old_v = float(old.get("value") or 0)
    new_v = float(new.get("value") or 0)
    if op in {">=", ">"}:
        return new_v >= old_v
    if op in {"<=", "<"}:
        return new_v <= old_v
    return new_v == old_v


def merge_targets(locked: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not incoming:
        return list(locked)
    if not locked:
        return list(incoming) if criteria_valid(incoming) else []
    by_key = {_criterion_key(row): dict(row) for row in locked}
    for row in incoming:
        key = _criterion_key(row)
        if key not in by_key:
            if criteria_valid([row]):
                by_key[key] = dict(row)
            continue
        if _is_stricter(by_key[key], row):
            by_key[key] = dict(row)
    out = list(by_key.values())
    return out if criteria_valid(out) else list(locked)


def _parse_score_values(raw: str) -> list[float]:
    text = str(raw or "").strip()
    if len(text) >= 2 and text[0] == "[" and text[-1] == "]":
        text = text[1:-1].strip()
    values: list[float] = []
    if not text:
        return values
    for item in text.split(","):
        bit = item.strip().strip("[]() ")
        if not bit:
            continue
        num = _as_number(bit)
        if num is None:
            return []
        values.append(num)
    return values


def parse_score_blob(text: str) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    blob = str(text or "")
    for match in _SCORES_LINE.finditer(blob):
        body = match.group(1).strip()
        line_found: dict[str, list[float]] = {}
        for pair in _SCORES_PAIR.finditer(body):
            metric = _metric_key(pair.group(1))
            if not metric:
                continue
            values = _parse_score_values(pair.group(2))
            if values:
                line_found[metric] = values
        for metric, values in line_found.items():
            found[metric] = values
    decoder = json.JSONDecoder()
    i = blob.find("{")
    while i >= 0:
        try:
            obj, end = decoder.raw_decode(blob, i)
        except json.JSONDecodeError:
            i = blob.find("{", i + 1)
            continue
        if isinstance(obj, dict) and isinstance(obj.get("scores"), dict):
            for key, val in obj["scores"].items():
                metric = _metric_key(key)
                if isinstance(val, list):
                    nums = [_as_number(x) for x in val]
                    if metric and nums and all(n is not None for n in nums):
                        found[metric] = [float(n) for n in nums if n is not None]
        i = blob.find("{", end)
    return found


def ingest_scores(board: Board, stdout: str) -> None:
    for metric, values in parse_score_blob(stdout).items():
        board.trial_scores[metric] = list(values)


def _aggregate(values: list[float], how: str) -> float | None:
    if not values:
        return None
    if how == "min":
        return float(min(values))
    if how == "mean":
        return float(sum(values) / len(values))
    return None


def _compare(got: float, op: str, want: float) -> bool:
    if op == ">=":
        return got >= want
    if op == "<=":
        return got <= want
    if op == ">":
        return got > want
    if op == "<":
        return got < want
    if op == "==":
        return abs(got - want) <= 1e-9
    return False


def evaluate_criteria(targets: list[dict[str, Any]], scores: dict[str, list[float]]) -> tuple[bool, str]:
    if not criteria_valid(targets):
        return False, "no valid quality targets"
    bits: list[str] = []
    ok = True
    for row in targets:
        metric = str(row["metric"])
        need_n = int(row["n"])
        got = list(scores.get(metric) or [])
        agg = str(row["aggregate"])
        if len(got) < need_n:
            ok = False
            extra = ""
            if len(got) == 1 and need_n >= 2:
                extra = " (print n comma-separated trial values, not a total)"
            bits.append(f"{row['id']}: need {need_n} {metric} values, got {len(got)}{extra}")
            continue
        use = got[:need_n]
        stat = _aggregate(use, agg)
        if stat is None:
            ok = False
            bits.append(f"{row['id']}: cannot {agg} {metric}")
            continue
        if not _compare(stat, str(row["op"]), float(row["value"])):
            ok = False
            bits.append(
                f"{row['id']}: {agg}({metric})={stat:.4g} not {row['op']} {row['value']} n={len(use)}"
            )
        else:
            bits.append(f"{row['id']}: {agg}({metric})={stat:.4g} {row['op']} {row['value']} n={len(use)}")
    return ok, "; ".join(bits) if bits else "no criteria"


def lock_targets(board: Board, user_text: str) -> None:
    user_rows = extract_targets_from_text(user_text)
    manager_rows = normalize_criteria(board.targets) if board.targets else []
    if not criteria_valid(manager_rows):
        manager_rows = []
    preset = preset_targets_for_text(user_text)
    if user_rows:
        merged = merge_targets(user_rows, manager_rows)
        source = "user"
    elif manager_rows:
        merged = manager_rows
        source = "manager"
    else:
        merged = preset
        source = "preset"
    if not criteria_valid(merged):
        merged = preset if criteria_valid(preset) else [dict(row) for row in GENERIC_QUALITY]
        source = "preset"
    board.targets = merged
    board.targets_source = source
    board.targets_locked = True


def apply_qualify(board: Board, box: Sandbox) -> None:
    listing = box.listing()
    empty = listing in {"", "(empty)"}
    ok, detail = evaluate_criteria(board.targets, board.trial_scores)
    if empty:
        ok = False
        detail = "no files in work folder; " + detail
    board.qualified = bool(ok)
    board.vote_open = bool(ok)
    board.qualify_detail = detail
    if not ok:
        board.last_vote = {}


def _round_snapshot(board: Board, box: Sandbox, *, shipped: bool, stopped: bool) -> dict[str, Any]:
    files = box.listing()
    file_count = 0 if files in {"", "(empty)"} else len([ln for ln in files.splitlines() if ln.strip()])
    scores = {k: list(v) for k, v in board.trial_scores.items()}
    means: dict[str, float] = {}
    mins: dict[str, float] = {}
    for key, values in scores.items():
        if not values:
            continue
        means[key] = round(sum(values) / len(values), 4)
        mins[key] = float(min(values))
    return {
        "round": board.round,
        "qualified": bool(board.qualified),
        "vote_open": bool(board.vote_open),
        "shipped": bool(shipped),
        "stopped": bool(stopped),
        "vote": dict(board.last_vote),
        "yes": yes_count(board.last_vote) if board.vote_open else 0,
        "scores": scores,
        "means": means,
        "mins": mins,
        "qualify_detail": board.qualify_detail,
        "harness_ok": bool(board.harness_ok),
        "smoke_ok": bool(board.smoke_ok),
        "smoke_detail": board.smoke_detail,
        "files": files,
        "file_count": file_count,
        "next_fix": list(board.next_fix),
    }


def looks_like_usb_chat_app(folder: Path) -> bool:
    src = Path(folder)
    if not src.is_dir():
        return False
    try:
        names = {p.name.lower() for p in src.iterdir() if p.is_file()}
    except OSError:
        return False
    return {"chat.py", "committee.py", "usbchat.py"} <= names


def _seed_skip_rel(rel: Path) -> bool:
    parts = [str(part).lower() for part in rel.parts]
    if any(part in SEED_SKIP_DIRS or part.endswith(".dist-info") for part in parts):
        return True
    name = rel.name.lower()
    if name in SEED_SKIP_NAMES or name.startswith(".env."):
        return True
    if rel.suffix.lower() in SEED_SKIP_SUFFIX:
        return True
    if rel.suffix.lower() not in WRITE_EXT:
        return True
    return False


def _is_data_doc(rel: Path) -> bool:
    parts = [str(part).lower() for part in rel.parts]
    if any(part in SEED_SKIP_DIRS or part.endswith(".dist-info") for part in parts):
        return False
    name = rel.name.lower()
    if name in SEED_SKIP_NAMES or name.startswith(".env."):
        return False
    if name in {n.lower() for n in SEED_PROMPT_NAMES}:
        return False
    if rel.suffix.lower() in SEED_SKIP_SUFFIX:
        return False
    return rel.suffix.lower() in DATA_DOC_EXT


def _csv_data_section(path: Path, rel: str) -> str:
    raw = path.read_bytes()
    if not raw:
        return f"### {rel}\nempty body (0 bytes). 0 rows.\n"
    text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = [str(h) for h in (reader.fieldnames or []) if h is not None]
    if not headers:
        return f"### {rel}\nempty body (no header/rows).\n"
    uniques: dict[str, list[str]] = {h: [] for h in headers}
    seen: dict[str, set[str]] = {h: set() for h in headers}
    samples: list[dict[str, str]] = []
    n = 0
    for row in reader:
        n += 1
        if len(samples) < DATA_CARD_SAMPLES:
            samples.append({h: "" if row.get(h) is None else str(row.get(h)) for h in headers})
        for h in headers:
            val = "" if row.get(h) is None else str(row.get(h))
            if val not in seen[h] and len(uniques[h]) < DATA_CARD_UNIQUES:
                seen[h].add(val)
                uniques[h].append(val)
    lines = [
        f"### {rel}",
        f"rows={n} headers={headers} (every cell is a string)",
    ]
    for h in headers:
        bits = ", ".join(json.dumps(v, ensure_ascii=True) for v in uniques[h])
        lines.append(f"  {h}: {bits or '(none)'}")
    for i, samp in enumerate(samples, 1):
        bits = ", ".join(f"{h}={json.dumps(samp.get(h, ''), ensure_ascii=True)}" for h in headers[:8])
        lines.append(f"  sample{i}: {bits}")
    return "\n".join(lines) + "\n"


def _text_data_section(path: Path, rel: str) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if not text.strip():
        return f"### {rel}\nempty.\n"
    if path.suffix.lower() == ".json":
        try:
            blob = json.dumps(json.loads(text), ensure_ascii=True)
        except json.JSONDecodeError:
            blob = text.strip()
        return f"### {rel}\n{blob[:400]}\n"
    return f"### {rel}\n{text.strip()[:400]}\n"


def build_data_card(box: Sandbox) -> str:
    """One-time host summary of non-script seed documents (csv/txt/json/md)."""
    sections: list[str] = []
    header = (
        "Host data card. main.py and tests must use these file values "
        "(same spelling and type; CSV numbers are quoted strings). "
        "Do not invent labels such as Engineering if the file has eng.\n"
    )
    budget = max(200, DATA_CARD_CAP - len(header))
    used = 0
    try:
        paths = sorted(p for p in box.root.rglob("*") if p.is_file())
    except OSError:
        return ""
    for path in paths:
        try:
            rel = path.relative_to(box.root)
        except ValueError:
            continue
        if not _is_data_doc(rel):
            continue
        posix = str(rel).replace("\\", "/")
        try:
            if path.suffix.lower() == ".csv":
                body = _csv_data_section(path, posix)
            else:
                body = _text_data_section(path, posix)
        except OSError:
            continue
        if not body:
            continue
        if used + len(body) > budget:
            remain = budget - used
            if remain > 48:
                sections.append(body[: remain - 1] + "…\n")
            break
        sections.append(body)
        used += len(body)
    if not sections:
        return ""
    return header + "".join(sections)


def read_seed_prompt(root: Path, cap: int = SEED_PROMPT_CAP) -> tuple[str, str]:
    folder = Path(root)
    for name in SEED_PROMPT_NAMES:
        path = folder / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body = text.strip()
        if body:
            return name, body[: max(1, int(cap))]
    return "", ""


def merge_seed_prompt(user_text: str, prompt: str, name: str) -> str:
    body = str(user_text or "").strip()
    extra = str(prompt or "").strip()
    if not extra:
        return body
    block = f"Seed prompt ({name}):\n{extra}" if name else extra
    if extra in body or block in body:
        return body
    return (body + "\n\n" + block).strip() if body else block


def copy_seed_folder(src: Path, dest: Path) -> dict[str, Any]:
    try:
        source = Path(src).expanduser().resolve()
        target = Path(dest).resolve()
    except OSError as exc:
        return {"ok": False, "error": str(exc), "files": [], "skipped": 0, "prompt_name": "", "prompt": ""}
    if not source.is_dir():
        return {"ok": False, "error": "not_a_folder", "files": [], "skipped": 0, "prompt_name": "", "prompt": ""}
    if looks_like_usb_chat_app(source):
        return {"ok": False, "error": "app_folder", "files": [], "skipped": 0, "prompt_name": "", "prompt": ""}
    if source == target:
        return {"ok": False, "error": "same_folder", "files": [], "skipped": 0, "prompt_name": "", "prompt": ""}
    copied: list[str] = []
    skipped = 0
    total = 0
    try:
        paths = list(source.rglob("*"))
    except OSError as exc:
        return {"ok": False, "error": str(exc), "files": [], "skipped": 0, "prompt_name": "", "prompt": ""}
    for path in paths:
        try:
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(source)
            resolved = path.resolve()
            resolved.relative_to(source)
        except (OSError, ValueError):
            skipped += 1
            continue
        try:
            resolved.relative_to(target)
            continue
        except ValueError:
            pass
        if _seed_skip_rel(rel):
            skipped += 1
            continue
        try:
            size = resolved.stat().st_size
        except OSError:
            skipped += 1
            continue
        if size > SEED_MAX_FILE_BYTES:
            skipped += 1
            continue
        if len(copied) >= SEED_MAX_FILES or total + size > SEED_MAX_BYTES:
            skipped += 1
            continue
        out = target / rel
        try:
            out.resolve().relative_to(target)
        except (OSError, ValueError):
            skipped += 1
            continue
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(resolved, out)
        except OSError:
            skipped += 1
            continue
        copied.append(str(rel).replace("\\", "/"))
        total += size
    prompt_name, prompt = read_seed_prompt(target)
    return {
        "ok": True,
        "files": copied,
        "skipped": skipped,
        "bytes": total,
        "prompt_name": prompt_name,
        "prompt": prompt,
    }


def clone_github(url: str, dest: Path, status: StatusFn | None = None) -> dict[str, Any]:
    git = shutil.which("git")
    if git is None:
        return {"ok": False, "error": "git is not installed on this PC."}
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    if status:
        status(f"Coding: cloning {url}…")
    try:
        proc = subprocess.run(
            [git, "clone", "--depth", "1", url, str(dest)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CLONE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "clone timed out"}
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "clone failed").strip()[:400]
        return {"ok": False, "error": err}
    return {"ok": True, "path": str(dest)}


def run_coding(
    *,
    complete: CompleteFn,
    user_text: str,
    keep_dir: Path,
    github_url: str | None = None,
    seed_dir: Path | None = None,
    web_digest: str = "",
    stop_event=None,
    status: StatusFn | None = None,
    build_pdf: Callable[[str, str], bytes] | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
    coding_log: Path | None = None,
) -> dict[str, Any]:
    box = Sandbox(keep_dir)
    notes: list[str] = []
    round_log: list[dict[str, Any]] = []
    session_dir, generic_path = _session_from_coding_log(coding_log)
    session = SessionLogs(session_dir, box.root)
    clog = CodingLog(generic_path, session.keep / "generic.jsonl" if session.keep else None)
    seed_info: dict[str, Any] = {}
    if seed_dir:
        if status:
            status("Coding: copying folder…")
        seed_info = copy_seed_folder(Path(seed_dir), box.root)
        if seed_info.get("ok"):
            n_files = len(seed_info.get("files") or [])
            notes.append(f"Seeded {Path(seed_dir).resolve()} ({n_files} files)")
            user_text = merge_seed_prompt(
                user_text,
                str(seed_info.get("prompt") or ""),
                str(seed_info.get("prompt_name") or ""),
            )
        else:
            notes.append("Seed copy failed: " + str(seed_info.get("error") or "unknown"))
    elif github_url:
        cloned = clone_github(github_url, box.root / "repo", status)
        if not cloned.get("ok"):
            notes.append("GitHub clone failed: " + str(cloned.get("error") or "unknown"))
        else:
            notes.append("Cloned " + github_url)
    board = Board(
        coding_rules=OWNERSHIP_RULES,
        coding_rules_locked=True,
        phase="0",
    )
    ctx = _Ctx(complete, board, box, user_text, web_digest, stop_event, status, build_pdf, clog, session)
    listing = box.listing()
    if listing not in {"", "(empty)"}:
        _sync_inventory(ctx)
    board.data_card = build_data_card(box)
    if board.data_card:
        clog.emit(
            "data_card",
            n=len(board.data_card),
            text=_clip_log(board.data_card, 1200),
        )
    clog.emit(
        "run_start",
        kind="coding",
        keep_dir=str(box.root),
        log=str(clog.path) if clog.path else "",
        session=str(session.dir) if session.dir else "",
        prompt=_clip_log(user_text, 2000),
        github=bool(github_url) and not seed_dir,
        seed=str(Path(seed_dir).resolve()) if seed_dir else "",
        seed_files=list(seed_info.get("files") or []),
    )
    if _stopped(stop_event):
        clog.emit("run_end", stopped=True, files=box.listing())
        return _result(
            board, box, notes, stopped=True, rounds=round_log, coding_log=clog.path, coding_session=session.dir
        )
    _turn(ctx, "manager", "phase0")
    lock_targets(board, user_text)
    board.contract_locked = True
    if str(board.test_plan or "").strip():
        board.test_plan_locked = True
    clog.emit("targets", source=board.targets_source, targets=list(board.targets))
    if not str(board.features or "").strip():
        board.features = (user_text or "phase 1").strip()[:800]
    if not str(board.architecture or "").strip():
        if box.listing() not in {"", "(empty)"}:
            board.architecture = "continue the seeded files in the local work folder"
        else:
            board.architecture = "scripts in the local work folder (.py / .html / .css / .js)"
    session.append(
        "planner",
        event="phase0",
        targets=list(board.targets),
        targets_source=board.targets_source,
        features=_clip_log(board.features, 800),
        architecture=_clip_log(board.architecture, 800),
        test_plan=_clip_log(board.test_plan, 800),
        data_card=_clip_log(board.data_card, 800),
    )
    board.phase = "1"
    for rnd in range(1, MAX_ROUNDS + 1):
        if _stopped(stop_event) or board.stop or board.phase_complete:
            break
        board.round = rnd
        board.vote_open = False
        board.qualified = False
        board.trial_scores = {}
        board.qualify_detail = ""
        board.last_vote = {}
        shipped_this = False
        reached_qualify = False
        try:
            ctx.last_write_denied = ""
            ctx.last_write_denied_error = ""
            ctx.artifact_snip = ""
            ctx.artifact_rel = ""
            ctx.last_smoke_path = ""
            ctx.last_smoke_stderr = ""
            _run_coder_phase(ctx)
            ctx.round_executes = 0
            ctx.executed_paths = set()
            ctx.last_execute_stderr = ""
            ctx.last_execute_path = ""
            ctx.last_has_scores = False
            ctx.last_execute_kind = ""
            if ctx.board.smoke_ok:
                _run_tester_phase(ctx)
            else:
                ctx.last_execute_kind = "no_execute"
                ctx.session.append(
                    "test",
                    event="skip_tester",
                    round=rnd,
                    smoke_ok=False,
                    detail=ctx.board.smoke_detail,
                    files=box.listing(),
                )
            apply_qualify(board, box)
            _refresh_inventory(ctx)
            board.last_eval = _eval_packet(ctx)
            reached_qualify = True
            clog.emit(
                "qualify",
                round=rnd,
                qualified=board.qualified,
                vote_open=board.vote_open,
                files=box.listing(),
                scores=dict(board.trial_scores),
                detail=board.qualify_detail,
                kind=ctx.last_execute_kind,
                harness_ok=board.harness_ok,
                smoke_ok=board.smoke_ok,
                smoke_detail=board.smoke_detail,
            )
            session.append(
                "test",
                event="qualify",
                round=rnd,
                qualified=board.qualified,
                vote_open=board.vote_open,
                ballot_will_run=bool(board.vote_open),
                detail=board.qualify_detail,
                scores={k: list(v) for k, v in board.trial_scores.items()},
                score_gap=_score_gap(board),
                files=box.listing(),
                kind=ctx.last_execute_kind,
                harness_ok=board.harness_ok,
                smoke_ok=board.smoke_ok,
                smoke_detail=board.smoke_detail,
            )
            if status:
                status(
                    f"Committee: qualify ({'pass' if board.qualified else 'fail'})…"
                )
            _run_critique_phase(ctx)
            session.append(
                "critique",
                event="round",
                round=rnd,
                qualify_detail=board.qualify_detail,
                kind=ctx.last_execute_kind,
                next_fix=list(board.next_fix),
                items=[
                    {
                        "id": item.item_id,
                        "text": _clip_log(item.text, 800),
                        "score": item.score,
                        "status": item.status,
                        "owner": item.owner,
                        "file": item.file,
                        "problem": _clip_log(item.problem, 400),
                        "fix": _clip_log(item.fix, 400),
                    }
                    for item in board.critiques
                ],
            )
            _turn(ctx, "evaluator", "evaluate")
            _apply_reject_scores(board)
            _filter_critiques_inventory(board)
            _prune_next_fix(board)
            _done_packet(ctx)
            _sync_next_fix(board)
            _turn(ctx, "manager", "plan")
            session.append(
                "planner",
                event="plan",
                round=rnd,
                qualify_detail=board.qualify_detail,
                qualified=board.qualified,
                vote_open=board.vote_open,
                features=_clip_log(board.features, 800),
                architecture=_clip_log(board.architecture, 800),
                docs=_clip_log(board.docs, 800),
                next_fix=list(board.next_fix),
                done=_clip_log(board.done_detail, 800),
                stop=board.stop,
            )
            if _stopped(stop_event) or board.stop:
                break
            vote_turns = 0
            if not board.vote_open:
                notes.append(f"round {rnd} no vote ({board.qualify_detail or 'criteria not met'})")
            else:
                for role in VOTING_ROLES:
                    _turn(ctx, role, "vote")
                    vote_turns += 1
                    if _stopped(stop_event):
                        break
                if should_commit(board):
                    shipped_this = True
                    notes.append(f"round {rnd} shipped ({yes_count(board.last_vote)}/5)")
                    _turn(ctx, "documenter", "document")
                if yes_count(board.last_vote) == len(VOTING_ROLES):
                    board.phase_complete = True
                    board.stop = True
            session.append(
                "test",
                event="ballot",
                round=rnd,
                vote_open=board.vote_open,
                vote_turns_ran=vote_turns,
                last_vote=dict(board.last_vote),
                should_commit=should_commit(board),
                shipped=shipped_this,
            )
        finally:
            if reached_qualify:
                rec = _round_snapshot(
                    board,
                    box,
                    shipped=shipped_this,
                    stopped=_stopped(stop_event) or board.stop,
                )
                round_log.append(rec)
                if on_round:
                    on_round(rec)
                clog.emit("round", **rec)
    reply = _coding_answer(board, box, notes)
    if session.dir:
        reply = (reply + f"\n\nCoding session: {session.dir}").strip()
    elif clog.path:
        reply = (reply + f"\n\nCoding log: {clog.path}").strip()
    clog.emit(
        "run_end",
        stopped=_stopped(stop_event),
        qualified=board.qualified,
        vote_open=board.vote_open,
        files=box.listing(),
        rounds=len(round_log),
        session=str(session.dir) if session.dir else "",
    )
    return _result(
        board, box, notes, reply=reply, rounds=round_log, coding_log=clog.path, coding_session=session.dir
    )


def run_review(
    *,
    complete: CompleteFn,
    user_text: str,
    keep_dir: Path,
    web_digest: str = "",
    stop_event=None,
    status: StatusFn | None = None,
    build_pdf: Callable[[str, str], bytes] | None = None,
    coding_log: Path | None = None,
) -> dict[str, Any]:
    box = Sandbox(keep_dir)
    session_dir, generic_path = _session_from_coding_log(coding_log)
    session = SessionLogs(session_dir, box.root)
    clog = CodingLog(generic_path, session.keep / "generic.jsonl" if session.keep else None)
    board = Board(phase="review")
    ctx = _Ctx(complete, board, box, user_text, web_digest, stop_event, status, build_pdf, clog, session)
    clog.emit("run_start", kind="review", keep_dir=str(box.root), log=str(clog.path) if clog.path else "", session=str(session.dir) if session.dir else "", prompt=_clip_log(user_text, 2000))
    _turn(ctx, "drafter", "draft")
    _turn(ctx, "critic", "review")
    session.append(
        "critique",
        event="review",
        items=[
            {
                "id": item.item_id,
                "text": _clip_log(item.text, 800),
                "score": item.score,
                "status": item.status,
            }
            for item in board.critiques
        ],
    )
    _turn(ctx, "writer", "write")
    reply = str(board.docs or board.features or "").strip() or _review_answer(box, user_text)
    if session.dir:
        reply = (reply + f"\n\nCoding session: {session.dir}").strip()
    elif clog.path:
        reply = (reply + f"\n\nCoding log: {clog.path}").strip()
    clog.emit("run_end", files=box.listing())
    return _result(board, box, [], reply=reply, coding_log=clog.path, coding_session=session.dir)


@dataclass
class _Ctx:
    complete: CompleteFn
    board: Board
    box: Sandbox
    user_text: str
    web_digest: str
    stop_event: Any
    status: StatusFn | None
    build_pdf: Callable[[str, str], bytes] | None
    log: CodingLog
    session: SessionLogs
    round_executes: int = 0
    executed_paths: set[str] = field(default_factory=set)
    last_write_denied: str = ""
    last_execute_stderr: str = ""
    last_execute_path: str = ""
    last_has_scores: bool = False
    last_execute_kind: str = ""
    last_write_denied_error: str = ""
    artifact_snip: str = ""
    artifact_rel: str = ""
    last_smoke_path: str = ""
    last_smoke_stderr: str = ""
    crash_lock: str = ""
    tester_wrote: bool = False
    need_test_rewrite: bool = False


def _stopped(stop_event) -> bool:
    return stop_event is not None and stop_event.is_set()


def _turn(ctx: _Ctx, role: str, stage: str) -> None:
    if _stopped(ctx.stop_event):
        return
    if stage == "vote" and not ctx.board.vote_open:
        return
    if ctx.status:
        ctx.status(f"Committee: {role} ({stage})…")
    ctx.log.emit("turn", role=role, stage=stage, round=ctx.board.round, phase=ctx.board.phase)
    messages = [
        {"role": "system", "content": _system(ctx, role, stage)},
        {"role": "user", "content": _user(ctx, role, stage)},
    ]
    raw = ""
    parsed: dict[str, Any] = {}
    for step in range(MAX_TOOL_STEPS + 1):
        if _stopped(ctx.stop_event):
            return
        try:
            raw = ctx.complete(messages)
        except Exception as exc:
            raw = str(exc)
            ctx.log.emit("complete", role=role, stage=stage, step=step, raw=_clip_log(raw), tool="", error=str(exc))
            break
        parsed = parse_committee_json(raw)
        actions = extract_tool_actions(parsed, raw)
        if not parsed and raw.strip():
            parsed = {"final": raw.strip()[:2000]}
        tool = actions[0][0] if actions else ""
        update = parsed.get("board_update")
        complete_json = json_is_complete_object(raw)
        ctx.log.emit(
            "complete",
            role=role,
            stage=stage,
            step=step,
            raw=_clip_log(raw),
            tool=tool or "",
            board_section=str((update or {}).get("section") or "") if isinstance(update, dict) else "",
            parsed_keys=sorted(str(k) for k in parsed.keys()),
            action_n=len(actions),
            complete_json=complete_json,
        )
        if not actions:
            break
        progress = False
        for tool, args in actions:
            result = _dispatch(ctx, role, tool, args)
            ctx.log.emit(
                "tool",
                role=role,
                stage=stage,
                step=step,
                name=tool,
                args=_tool_args_for_log(args),
                result={
                    "ok": result.get("ok"),
                    "error": result.get("error"),
                    "path": result.get("path"),
                    "code": result.get("code"),
                    "hint": result.get("hint"),
                    "warning": result.get("warning"),
                    "stdout": _clip_log(result.get("stdout") or "", 2000),
                    "stderr": _clip_log(result.get("stderr") or "", 1000),
                },
            )
            messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)[:1500]})
            messages.append(
                {
                    "role": "user",
                    "content": "Tool result:\n"
                    + json.dumps(result, ensure_ascii=False)[:2000]
                    + "\nWork folder files:\n"
                    + ctx.box.listing(),
                }
            )
            if tool == "sandbox_write":
                path = _norm_rel(str(result.get("path") or _rel_path(args) or ""))
                if result.get("ok"):
                    progress = True
                    if path:
                        ctx.executed_paths.discard(path)
                else:
                    progress = True
            if tool == "executeScriptInSandbox" and result.get("error") != "already_executed":
                progress = True
        if not complete_json:
            break
        if not progress:
            break
    _ingest(ctx.board, role, parsed, raw)
    if stage != "vote":
        final = str(parsed.get("final") or "").strip()
        if final and role in {"drafter", "writer", "documenter", "manager"} and len(final) > len(ctx.board.docs or ""):
            if role in {"drafter", "writer", "documenter"}:
                ctx.board.docs = final[:4000]


def _system(ctx: _Ctx, role: str, stage: str) -> str:
    tools = _tools_for(role)
    view = _clip(_view(ctx.board, role, stage), VIEW_CHARS)
    extra = ""
    if ctx.web_digest.strip():
        extra = "\nWeb notes:\n" + _clip(ctx.web_digest, 800)
    job = _job(role, stage)
    vote = ""
    if stage == "vote":
        vote = 'Ballot is OPEN because host qualify passed. Reply {"vote":"yes"} or {"vote":"no"}.\n'
    logs = ""
    if role == "critique":
        logs = "Use the results packet on the board. Do not read JSONL dumps. Results outrank code.\n"
    elif role == "evaluator":
        logs = "Use the host inventory. Discard critiques that claim a listed file or function is missing.\n"
    elif role == "manager" and stage == "plan":
        logs = "Do not reread features or architecture. Newest critiques, scores, and the done list only.\n"
    elif role == "tester":
        logs = "Call live inventory signatures. Write then execute. n trial values, not a total.\n"
    elif role == "coder":
        logs = "Write impl files only. Keep locked names. Fix smoke stderr. Tester owns tests.\n"
    elif role == "manager":
        logs = "Host logs (append-only, sandbox_read _logs/planner.jsonl _logs/critique.jsonl _logs/test.jsonl _logs/generic.jsonl).\n"
    if role == "manager" and stage == "plan":
        user_bit = "User request is locked. Do not rewrite features, architecture, or targets.\n"
    elif role in {"coder", "tester"}:
        user_bit = "Full user request is in the user message. Follow last stderr and live inventory first.\n"
    else:
        user_bit = f"User request:\n{ctx.user_text}\n"
    return (
        f"You are the {role} on a sequential local committee. One role. JSON only.\n"
        + user_bit
        + f"Work folder files:\n{ctx.box.listing()}\n"
        f"Tools: {', '.join(tools) or '(none)'}\n"
        + logs
        + job
        + vote
        + 'Tool: {"tool":"NAME","args":{...}}\n'
        'Board: {"board_update":{"section":"features","content":"..."}}\n'
        'If you learned durable user facts (name, title, skills, education, links), add "profile_update".\n'
        "Board:\n"
        + view
        + extra
    )


def _tester_user_status(ctx: _Ctx) -> str:
    tests = list_test_scripts(ctx.box)
    lines = [
        "files: " + ctx.box.listing(),
        "inventory:\n" + inventory_text(ctx.board.inventory),
        f"{MAIN_FILE} (clone these calls with other literals):\n" + _main_snippet(ctx.box),
    ]
    if ctx.board.data_card:
        lines.append("data_card (literals must appear here):\n" + ctx.board.data_card)
    if ctx.board.test_plan:
        lines.append("test_plan:\n" + ctx.board.test_plan[:800])
    if ctx.last_write_denied:
        lines.append(
            f"last_denied={ctx.last_write_denied_error} path={ctx.last_write_denied}"
        )
    if ctx.last_execute_kind:
        lines.append(f"last_execute kind={ctx.last_execute_kind} path={ctx.last_execute_path}")
    if ctx.last_execute_stderr:
        lines.append("stderr=" + ctx.last_execute_stderr[:500])
    err = (ctx.last_execute_stderr or "").lower()
    denied = ctx.last_write_denied_error
    if "timeout" in err:
        lines.append(
            "Timeout: wrap trials in try/finally and print SCORES of n zeros. No unbounded loops."
        )
    if denied in {"live_name_required", "rewrite_required"} or "live_name" in err:
        lines.append("Rewrite the test to the live signatures above. Copy main.py calls.")
    if denied == "literal_scores":
        lines.append("Do not hardcode SCORES lists. Compute 1/0 from each trial return value.")
    if denied == "placeholder_content":
        lines.append(
            "args.content was a placeholder. Put the full test source in content, not '...' and not only a markdown fence."
        )
    if denied == "syntax_error":
        lines.append("Fix the syntax error in the test, then write again.")
    if denied in {"bad_script", "missing_test"} or "bad_script" in err or "missing_test" in err:
        lines.append("That test path is not on disk. sandbox_write it first, then execute the same path.")
    if ctx.need_test_rewrite or ctx.last_execute_kind == "test_broken":
        lines.append(
            "Harness broken. Rewrite the test (clone main.py, n computed trial values). "
            "Do not execute the same file unchanged."
        )
    if ctx.last_execute_kind == "impl_crash":
        lines.append(
            "Impl crash. Do not rewrite tests unless last_denied is live_name_required."
        )
    if not tests:
        lines.append(
            "No test_*.py yet. Clone main.py calls with other literals, print computed SCORES, then execute."
        )
    else:
        lines.append(
            "Existing tests: "
            + ", ".join(tests)
            + ". Rewrite if harness is broken; otherwise execute after a write this turn."
        )
    return "\n".join(lines) + "\n"


def _coder_user_status(ctx: _Ctx) -> str:
    lines = [
        "files: " + _impl_listing(ctx.box),
        "inventory:\n" + inventory_text(ctx.board.inventory, hide_tests=True),
    ]
    if ctx.board.data_card:
        lines.append("data_card (main.py literals must appear here):\n" + ctx.board.data_card)
    if ctx.board.test_plan:
        lines.append("test_plan:\n" + ctx.board.test_plan[:800])
    if ctx.last_write_denied_error == "placeholder_content":
        lines.append(
            "args.content was a placeholder. Put the full impl source in content, not '...'."
        )
    if ctx.last_write_denied_error == "coder_impl_only":
        lines.append(
            f"coder_impl_only on {ctx.last_write_denied}. Next sandbox_write must be a non-test impl file."
        )
    if ctx.last_write_denied_error == "locked_name_removed":
        lines.append(
            f"locked_name_removed on {ctx.last_write_denied}. Keep locked names; edit in place."
        )
    if ctx.crash_lock:
        lines.append(
            f"crash_lock: sandbox_write {ctx.crash_lock} before any other impl file. Do not write tests."
        )
    if ctx.last_smoke_stderr:
        lines.append("Last smoke fail:\n" + ctx.last_smoke_stderr[:600])
    if MAIN_FILE not in (ctx.box.listing() or "") and "missing" in (ctx.last_smoke_stderr or "").lower():
        lines.append(f"Write {MAIN_FILE} that imports the libraries and calls them with example values.")
    if ctx.board.scored_ok and ctx.board.smoke_ok:
        lines.append(
            "Smoke passed and SCORES exist. Do not rewrite the whole module; patch the function named in stderr."
        )
    return "\n".join(lines) + "\n"


def _user(ctx: _Ctx, role: str, stage: str) -> str:
    if stage == "phase0":
        extra = ""
        listing = ctx.box.listing()
        if listing not in {"", "(empty)"}:
            extra = (
                "Work folder already has files. Continue from them; do not empty the folder "
                "or invent a new API over locked inventory names. "
            )
        if ctx.board.data_card:
            extra += (
                "Host data card (do not re-read these files; use these values):\n"
                + ctx.board.data_card
                + "Write test_plan cases from this card only. JSON board_update section test_plan. "
            )
        return (
            extra
            + "Write the contract. No code yet. JSON board_update for features, architecture, "
            "targets (runtime quality criteria: metric, n>=2, aggregate mean or min, op, value)"
            + (", and test_plan" if ctx.board.data_card else "")
            + "."
        )
    if stage == "vote":
        return "Cast your yes/no vote for this round. Vote only because the host already opened the ballot."
    if stage == "draft":
        return "Draft the high-stakes document. JSON with final text. Do not execute code."
    if stage == "review":
        return "List blocking issues vs the request. JSON critiques. No sandbox."
    if stage == "write":
        return "Write the document with write_pdf or write_doc. JSON only."
    if stage == "critique_artifact":
        return (
            f"Trace snippet of {ctx.artifact_rel or 'the crashing file'}:\n"
            f"{ctx.artifact_snip}\n"
            "JSON critiques with owner,file,problem,fix. Results outrank this snippet."
        )
    extra = ""
    if role == "tester":
        extra = _tester_user_status(ctx)
        owned = [row for row in ctx.board.next_fix if str(row.get("owner") or "") == "tester"]
        if owned:
            extra += "Do your next_fix items only.\n"
    elif role == "coder":
        extra = _coder_user_status(ctx)
        owned = [row for row in ctx.board.next_fix if str(row.get("owner") or "") in {"", "coder"}]
        if owned:
            extra += "Do the next_fix items you own (coder). Do not write tests.\n"
    elif role == "manager" and stage == "plan":
        extra = (
            "Append next_fix only (new version). Do not rewrite features, architecture, or targets. "
            "Use newest critiques (after scores) and the done list. "
            "board_update section next_fix with [{owner,file,problem,fix}].\n"
        )
        return extra
    elif role == "evaluator":
        extra = (
            "Score each open critique. If inventory already lists a file or function the critique "
            "says is missing, score discarded. JSON critique_scores {id: score}.\n"
        )
    elif role == "critique":
        extra = (
            'JSON board_update section critiques with a list of {id,owner,file,problem,fix}. '
            "No fake critique tool. Results outrank code. Do not invent SCORES.\n"
        )
        if ctx.board.data_card:
            extra += "Compare test literals to the host data card.\n"
    return extra + f"Do the {role} job. User asked:\n{ctx.user_text}"


def _job(role: str, stage: str) -> str:
    if role == "manager" and stage == "phase0":
        return (
            "Phase 0: contract plus runtime QUALITY targets. Copy user numbers if given. "
            "Else invent measurable standards (scores, exact cases, rates). "
            "If the work folder already has files, continue that architecture; do not start from empty. "
            "Forbidden: 'the code works', 'tests pass', 'no bugs'. "
            "Each criterion needs metric, n>=2 trials, aggregate mean or min, op, numeric value. JSON targets section. No code. "
            "If a host data card is present, also write test_plan with concrete cases using only those file values "
            "(CSV cells are strings). Do not invent values. Do not change user TARGETS metrics.\n"
        )
    if role == "manager":
        return (
            "Append the next fix version from newest critiques and the done list. "
            "Do not rewrite locked targets, features, or architecture. "
            "board_update section next_fix with a list of {owner,file,problem,fix}. "
            "If test_*.py exists and harness_ok, plan coder impl fixes then re-execute tests. "
            "You may stop.\n"
        )
    if role == "coder":
        return (
            "sandbox_write non-test .py only, including main.py. JSON, no markdown fences. "
            "Only edit files already in the work folder or new non-test .py you create. "
            "Never read, write, or execute test_*.py. "
            "After sandbox_write, execute that same impl path to see stdout; host also imports libs and runs main.py. "
            "Libraries must import; main.py must call them with example values so python main.py exits 0. "
            "If a host data card exists, those example values must appear on the card (same spelling; CSV numbers are strings). "
            "Quality is not your job. No SCORES. "
            "If the last error was coder_impl_only, the next path must be an impl file. "
            "Copy live inventory signatures. Do not delete locked names. "
            "Edit the crash_lock or next_fix file; do not replace a compiling module unless smoke failed. "
            "If smoke already passed and SCORES exist, patch the function named in stderr only. "
            "Fix syntax and missing stdlib imports from smoke stderr. "
            "A '...' or \"...\" string must be one physical line; use \\n, triple quotes, or a data file for multi-line text. "
            "Do not name a field the same as a method (self.store = {} makes store() a dict). "
            "No if __name__ training loops. Stdlib only. "
            "Replace <FULL_SOURCE> in args.content with the full file text (not a markdown fence). "
            + '{"tool":"sandbox_write","args":{"path":"file.py","content":"'
            + WRITE_CONTENT_PLACEHOLDER
            + '"}}.\n'
        )
    if role == "tester":
        return (
            "Clone main.py call pattern with different literals that still appear on the host data card. "
            "Write test_*.py first; only execute a path that is already on disk. "
            "If execute returns missing_test, sandbox_write that path, then execute it. "
            "Each trial in try/except; compute 1/0 from the impl return (never a literal SCORES 1,1,1 list). "
            "An empty input file scores 1 when the impl returns no rows. "
            "Finally print SCORES metric=v1,v2,... with n values (not a count). "
            "Call live signatures the same way main.py does, including constructor args. "
            "If live_name_required, syntax_error, or literal_scores, rewrite. "
            "If last stdout was a single total, rewrite to n comma-separated trials; do not re-execute the same file. "
            "No assert or sys.exit. Timeout 30 unless fruit_points (up to 600). Never write impl files. "
            "Replace <FULL_SOURCE> in args.content with the full test source (not a markdown fence). "
            + '{"tool":"sandbox_write","args":{"path":"test_foo.py","content":"'
            + WRITE_CONTENT_PLACEHOLDER
            + '"}} then '
            '{"tool":"executeScriptInSandbox","args":{"path":"test_foo.py","timeout":30}}.\n'
        )
    if role == "critique":
        if stage == "critique_artifact":
            return (
                "Read the traceback snippet. JSON critiques with owner,file,problem,fix. "
                "Results outrank code. Do not invent SCORES.\n"
            )
        return (
            "Use the results packet, not JSONL. Blocking bugs vs locked targets. "
            'JSON: {"board_update":{"section":"critiques","content":[{"id":"c1","owner":"coder","file":"...","problem":"...","fix":"..."}]}}. '
            "Results outrank code. Do not invent metric values.\n"
        )
    if role == "evaluator":
        return (
            "Score open critiques against the host inventory and results packet. "
            "If a critique claims a listed file or function is missing, score discarded. "
            "critique_scores section as {id: score}.\n"
        )
    if role == "documenter":
        return "Write README notes. sandbox_write README.md if useful. Do not vote.\n"
    if role == "drafter":
        return "High-stakes review. No sandbox. Draft the document in final.\n"
    if role == "critic":
        return "High-stakes review. No sandbox. Open critiques only.\n"
    if role == "writer":
        return "High-stakes review. No sandbox. write_pdf or write_doc, then final.\n"
    return "Do your role only.\n"


def _tools_for(role: str) -> list[str]:
    if role == "coder":
        return ["sandbox_write", "sandbox_read", "executeScriptInSandbox"]
    if role == "tester":
        return ["sandbox_write", "sandbox_read", "executeScriptInSandbox"]
    if role == "documenter":
        return ["sandbox_write", "sandbox_read"]
    if role == "writer":
        return ["write_pdf", "write_doc"]
    return ["sandbox_read"] if role in {"manager", "critique", "evaluator"} else []


def _dispatch(ctx: _Ctx, role: str, name: str, args: dict[str, Any]) -> dict[str, Any]:
    allowed = set(_tools_for(role))
    if name not in allowed:
        return {"ok": False, "error": "role_denied", "tool": name}
    if name == "sandbox_write":
        rel = _rel_path(args)
        locked = _role_path_lock(role, rel, ctx.box)
        if locked is None and role == "coder" and ctx.crash_lock:
            want = Path(ctx.crash_lock).name.lower()
            got = Path(rel).name.lower()
            if got != want:
                locked = {
                    "ok": False,
                    "error": "crash_lock",
                    "path": rel,
                    "hint": f"write {ctx.crash_lock} first (traceback impl); do not write tests",
                }
        if locked is not None:
            ctx.last_write_denied = rel
            ctx.last_write_denied_error = str(locked.get("error") or "")
            ctx.session.append(
                "test",
                event="write_denied",
                round=ctx.board.round,
                role=role,
                path=rel,
                error=locked.get("error"),
                hint=locked.get("hint"),
            )
            return locked
        content = _rel_content(args)
        if _is_placeholder_content(content):
            denied = _placeholder_write_denied(rel)
            ctx.last_write_denied = rel
            ctx.last_write_denied_error = "placeholder_content"
            ctx.session.append(
                "test",
                event="write_denied",
                round=ctx.board.round,
                role=role,
                path=rel,
                error="placeholder_content",
                hint=denied.get("hint"),
            )
            return denied
        if role == "coder" and rel.lower().endswith(".py") and not is_test_script(rel):
            syn = _compile_py(content)
            if syn:
                denied = {
                    "ok": False,
                    "error": "syntax_error",
                    "path": rel,
                    "hint": f"impl does not compile: {syn}",
                }
                ctx.last_write_denied = rel
                ctx.last_write_denied_error = "syntax_error"
                ctx.last_smoke_path = rel
                ctx.last_smoke_stderr = denied["hint"]
                ctx.session.append(
                    "test",
                    event="write_denied",
                    round=ctx.board.round,
                    role=role,
                    path=rel,
                    error="syntax_error",
                    hint=denied["hint"],
                )
                return denied
            if not is_main_script(rel):
                inv = ctx.board.inventory or {}
                locked_map = inv.get("locked_symbols") or {}
                key = Path(rel).name
                locked_names = list(
                    locked_map.get(rel)
                    or locked_map.get(key)
                    or locked_map.get(_norm_rel(rel))
                    or []
                )
                new_names = _py_symbols(content)
                if locked_names and new_names:
                    missing = [n for n in locked_names if n not in new_names]
                    if missing:
                        denied = {
                            "ok": False,
                            "error": "locked_name_removed",
                            "path": rel,
                            "hint": (
                                f"keep locked names on {key}: {', '.join(locked_names)}. "
                                f"missing: {', '.join(missing)}. edit; do not drop them."
                            ),
                        }
                        ctx.last_write_denied = rel
                        ctx.last_write_denied_error = "locked_name_removed"
                        ctx.session.append(
                            "test",
                            event="write_denied",
                            round=ctx.board.round,
                            role=role,
                            path=rel,
                            error="locked_name_removed",
                            hint=denied["hint"],
                        )
                        return denied
        if role == "tester" and is_test_script(rel):
            issue, warns = _test_script_issues(content)
            if issue:
                denied = {
                    "ok": False,
                    "error": issue,
                    "path": rel,
                    "hint": "; ".join(warns) if warns else "test must print SCORES",
                }
                ctx.last_write_denied = rel
                ctx.last_write_denied_error = issue
                ctx.session.append(
                    "test",
                    event="write_denied",
                    round=ctx.board.round,
                    role=role,
                    path=rel,
                    error=issue,
                    hint=denied.get("hint"),
                )
                return denied
            live_denied = _live_call_denied(rel, content, ctx.board.inventory)
            if live_denied:
                ctx.last_write_denied = rel
                ctx.last_write_denied_error = str(live_denied.get("error") or "")
                ctx.session.append(
                    "test",
                    event="write_denied",
                    round=ctx.board.round,
                    role=role,
                    path=rel,
                    error=live_denied.get("error"),
                    hint=live_denied.get("hint"),
                    unknown=live_denied.get("unknown"),
                )
                return live_denied
        result = ctx.box.write(rel, content)
        if (
            role == "coder"
            and ctx.crash_lock
            and result.get("ok")
            and Path(rel).name.lower() == Path(ctx.crash_lock).name.lower()
        ):
            ctx.crash_lock = ""
        if role == "tester":
            _issue, warns = _test_script_issues(content)
            if warns:
                result["warning"] = "; ".join(warns)
            if result.get("ok"):
                ctx.tester_wrote = True
                ctx.need_test_rewrite = False
                ctx.executed_paths.discard(_norm_rel(rel))
            ctx.session.append(
                "test",
                event="write",
                round=ctx.board.round,
                path=result.get("path") or rel,
                ok=result.get("ok"),
                error=result.get("error"),
                warning=result.get("warning"),
            )
        if (
            role == "coder"
            and result.get("ok")
            and str(rel).lower().endswith(".py")
            and not is_test_script(rel)
        ):
            raw = _smoke_one(ctx.box, rel, SMOKE_TIMEOUT)
            ctx.last_smoke_path = rel
            smoke_ok = bool(raw.get("ok"))
            if smoke_ok:
                ctx.last_smoke_stderr = ""
            else:
                ctx.last_smoke_stderr = str(raw.get("stderr") or raw.get("error") or "smoke_fail")[:1000]
            result["smoke_ok"] = smoke_ok
            result["smoke_stderr"] = ctx.last_smoke_stderr
            ctx.session.append(
                "test",
                event="smoke",
                round=ctx.board.round,
                path=rel,
                ok=smoke_ok,
                error=raw.get("error"),
                code=raw.get("code"),
                stdout=_clip_log(raw.get("stdout") or "", 800),
                stderr=_clip_log(raw.get("stderr") or "", 1000),
                source="write",
            )
        return result
    if name == "sandbox_read":
        rel = _rel_path(args)
        locked = _role_path_lock(role, rel, ctx.box) if role == "coder" else None
        if locked is not None:
            ctx.last_write_denied = rel
            ctx.last_write_denied_error = str(locked.get("error") or "")
            ctx.session.append(
                "test",
                event="read_denied",
                round=ctx.board.round,
                role=role,
                path=rel,
                error=locked.get("error"),
                hint=locked.get("hint"),
            )
            return locked
        return ctx.box.read(rel, int(args.get("start") or 0), int(args.get("end") or 4000))
    if name == "executeScriptInSandbox":
        rel = _rel_path(args)
        locked = _role_path_lock(role, rel, ctx.box)
        if locked is not None:
            ctx.last_write_denied = rel
            ctx.last_write_denied_error = str(locked.get("error") or "")
            ctx.session.append(
                "test",
                event="execute_denied",
                round=ctx.board.round,
                role=role,
                path=rel,
                error=locked.get("error"),
                hint=locked.get("hint"),
            )
            return locked
        path = _norm_rel(rel)
        if role == "tester" and is_test_script(rel):
            resolved = ctx.box.resolve(rel)
            if resolved is None or not resolved.is_file():
                denied = {
                    "ok": False,
                    "error": "missing_test",
                    "path": path,
                    "hint": (
                        f"{path} is not on disk. sandbox_write that test file first, "
                        "then execute the same path."
                    ),
                }
                ctx.last_write_denied = path
                ctx.last_write_denied_error = "missing_test"
                ctx.last_execute_path = path
                ctx.last_execute_stderr = denied["hint"]
                ctx.session.append(
                    "test",
                    event="execute_denied",
                    round=ctx.board.round,
                    role=role,
                    path=path,
                    error="missing_test",
                    hint=denied["hint"],
                )
                return denied
            if ctx.need_test_rewrite and not ctx.tester_wrote:
                denied = {
                    "ok": False,
                    "error": "rewrite_required",
                    "path": path,
                    "hint": (
                        "last run was test_broken; sandbox_write a new harness "
                        "(n comma-separated trial values, not a total) then execute once"
                    ),
                }
                ctx.last_write_denied = path
                ctx.last_write_denied_error = "rewrite_required"
                ctx.session.append(
                    "test",
                    event="execute_denied",
                    round=ctx.board.round,
                    role=role,
                    path=path,
                    error="rewrite_required",
                    hint=denied["hint"],
                )
                return denied
            body = ""
            resolved = ctx.box.resolve(rel)
            if resolved is not None and resolved.is_file():
                try:
                    body = resolved.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    body = ""
            issue, warns = _test_script_issues(body)
            if issue:
                hint = "; ".join(warns) if warns else issue
                denied = {"ok": False, "error": issue, "path": path, "hint": hint}
                ctx.last_write_denied = path
                ctx.last_write_denied_error = issue
                ctx.last_execute_kind = "test_broken"
                ctx.last_execute_path = path
                ctx.last_execute_stderr = hint
                ctx.need_test_rewrite = True
                ctx.board.harness_ok = False
                ctx.board.scored_ok = False
                ctx.session.append(
                    "test",
                    event="execute_denied",
                    round=ctx.board.round,
                    role=role,
                    path=rel,
                    error=issue,
                    hint=hint,
                )
                return denied
            live_denied = _live_call_denied(rel, body, ctx.board.inventory)
            if live_denied:
                ctx.last_write_denied = rel
                ctx.last_write_denied_error = str(live_denied.get("error") or "")
                ctx.last_execute_kind = "test_broken"
                ctx.last_execute_path = path
                ctx.last_execute_stderr = str(live_denied.get("hint") or "live_name_required")
                ctx.need_test_rewrite = True
                ctx.board.harness_ok = False
                ctx.board.scored_ok = False
                ctx.session.append(
                    "test",
                    event="execute_denied",
                    round=ctx.board.round,
                    role=role,
                    path=rel,
                    error=live_denied.get("error"),
                    hint=live_denied.get("hint"),
                    unknown=live_denied.get("unknown"),
                )
                return live_denied
        if path in ctx.executed_paths:
            return {
                "ok": False,
                "error": "already_executed",
                "path": path,
                "hint": "already ran this script this turn; rewrite the test if it failed, then execute once",
            }
        try:
            timeout = int(args.get("timeout") or EXECUTE_TIMEOUT)
        except (TypeError, ValueError):
            timeout = EXECUTE_TIMEOUT
        timeout = max(1, min(timeout, EXECUTE_TIMEOUT_MAX))
        raw = ctx.box.execute(rel, timeout)
        if role == "coder":
            path = _norm_rel(rel)
            ctx.executed_paths.add(path)
            ctx.last_smoke_path = path
            if not raw.get("ok"):
                ctx.last_smoke_stderr = str(raw.get("stderr") or raw.get("error") or "")[:1000]
            ctx.session.append(
                "test",
                event="coder_execute",
                round=ctx.board.round,
                path=path,
                ok=raw.get("ok"),
                error=raw.get("error"),
                code=raw.get("code"),
                timeout=timeout,
                stdout=_clip_log(raw.get("stdout") or "", 800),
                stderr=_clip_log(raw.get("stderr") or "", 1000),
            )
            return raw
        return _finish_execute(ctx, rel, timeout, raw, source="tester")
    if name == "write_doc":
        rel = str(args.get("name") or "document") + "." + str(args.get("type") or "md").lstrip(".")
        return ctx.box.write(rel, str(args.get("content") or ""))
    if name == "write_pdf":
        if ctx.build_pdf is None:
            return {"ok": False, "error": "no_pdf"}
        name = str(args.get("name") or "document").strip() or "document"
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", name)[:40] + ".pdf"
        data = ctx.build_pdf(name, str(args.get("content") or ""))
        path = ctx.box.root / safe
        path.write_bytes(data)
        return {"ok": True, "path": safe}
    return {"ok": False, "error": "unknown_tool"}


def _ingest(board: Board, role: str, parsed: dict[str, Any], raw: str) -> None:
    update = parsed.get("board_update")
    if isinstance(update, dict):
        if "section" in update:
            apply_update(board, role, str(update.get("section")), update.get("content"))
        else:
            for key, value in update.items():
                apply_update(board, role, str(key), value)
    if parsed.get("stop") and role == "manager":
        board.stop = True
    vote = parsed.get("vote")
    if vote is None:
        vote = infer_vote(str(parsed.get("final") or raw or ""))
    if vote is not None:
        record_vote(board, role, str(vote))
    if role == "critique":
        extra = parsed.get("critiques")
        if extra is not None:
            board.critiques.extend(_parse_critiques(extra))
    profile = parsed.get("profile_update")
    if isinstance(profile, dict):
        for key, value in profile.items():
            if value in (None, "", [], {}):
                continue
            board.profile_update[str(key)] = value


def apply_update(board: Board, role: str, section: str, content: Any) -> dict[str, Any]:
    section = SECTION_ALIASES.get(str(section or "").strip().lower(), str(section or "").strip())
    allowed = SECTION_WRITERS.get(section)
    if allowed is None:
        return {"ok": False, "error": "unknown_section"}
    if role not in allowed:
        return {"ok": False, "error": "role_denied"}
    if section == "coding_rules" and board.coding_rules_locked:
        return {"ok": False, "error": "coding_rules_locked"}
    if section in {"features", "architecture"} and board.contract_locked:
        return {"ok": False, "error": "contract_locked"}
    if section == "test_plan":
        if board.test_plan_locked:
            return {"ok": False, "error": "test_plan_locked"}
        if isinstance(content, (list, dict)):
            text = json.dumps(content, ensure_ascii=True)
        else:
            text = str(content or "")
        if not text.strip():
            return {"ok": True, "skipped": "empty"}
        board.test_plan = text
        return {"ok": True, "section": section}
    if section in {"features", "architecture", "coding_rules", "code", "docs"}:
        text = str(content or "")
        if not text.strip():
            return {"ok": True, "skipped": "empty"}
        setattr(board, section, text)
        return {"ok": True, "section": section}
    if section == "targets":
        incoming = normalize_criteria(content)
        if board.targets_locked:
            board.targets = merge_targets(board.targets, incoming)
        elif criteria_valid(incoming):
            board.targets = incoming
        else:
            return {"ok": False, "error": "invalid_targets"}
        return {"ok": True, "section": "targets"}
    if section == "tests":
        board.tests = _parse_tests(content)
    elif section == "critiques":
        board.critiques.extend(_parse_critiques(content))
    elif section == "critique_scores":
        _apply_scores(board, content)
    elif section == "critique_status":
        _apply_status(board, content)
    elif section == "next_fix":
        rows = _parse_next_fix(content)
        if not rows:
            return {"ok": True, "skipped": "empty"}
        kept: list[dict[str, Any]] = []
        for row in rows:
            row["version"] = board.round
            blob = f"{row.get('file')} {row.get('problem')} {row.get('fix')}"
            if _absent_claim_present(board, str(row.get("file") or ""), blob):
                continue
            kept.append(row)
        if not kept:
            return {"ok": True, "skipped": "inventory"}
        _append_next_fix(board, kept)
        return {"ok": True, "section": section}
    return {"ok": True, "section": section}


def _parse_tests(content: Any) -> list[TestItem]:
    items: list[TestItem] = []
    if isinstance(content, list):
        raw = content
    elif isinstance(content, dict):
        raw = content.get("tests") or content.get("cases") or [content]
    else:
        raw = [ln.strip().lstrip("-").strip() for ln in str(content or "").splitlines() if ln.strip()]
    for row in raw:
        if isinstance(row, dict):
            items.append(
                TestItem(
                    name=str(row.get("name") or row.get("id") or f"t{len(items)+1}"),
                    feature=str(row.get("feature") or ""),
                    status=str(row.get("status") or "pending"),
                    detail=str(row.get("detail") or ""),
                )
            )
        else:
            items.append(TestItem(name=str(row)[:120], status="pending"))
    return items


def _parse_next_fix(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, list):
        raw = content
    elif isinstance(content, dict):
        raw = content.get("items") or content.get("fixes") or content.get("next_fix") or [content]
    else:
        text = str(content or "").strip()
        raw = [{"problem": text}] if text else []
    rows: list[dict[str, Any]] = []
    for row in raw:
        if isinstance(row, dict):
            problem = str(row.get("problem") or row.get("text") or "").strip()
            fix = str(row.get("fix") or "").strip()
            if not problem and not fix:
                continue
            rows.append(
                {
                    "id": str(row.get("id") or row.get("item_id") or ""),
                    "owner": str(row.get("owner") or ""),
                    "file": str(row.get("file") or row.get("path") or ""),
                    "problem": problem,
                    "fix": fix,
                }
            )
        else:
            text = str(row).strip()
            if text:
                rows.append({"id": "", "owner": "", "file": "", "problem": text, "fix": ""})
    return rows


def _parse_critiques(content: Any) -> list[CritiqueItem]:
    if isinstance(content, list):
        rows = content
    elif isinstance(content, dict):
        rows = content.get("critiques") or content.get("items") or [content]
    else:
        rows = [ln.strip().lstrip("-").strip() for ln in str(content or "").splitlines() if ln.strip()]
    out: list[CritiqueItem] = []
    for row in rows:
        if isinstance(row, dict):
            owner = str(row.get("owner") or "")
            file = str(row.get("file") or row.get("path") or "")
            problem = str(row.get("problem") or "")
            fix = str(row.get("fix") or "")
            text = str(row.get("text") or row.get("body") or "").strip()
            if not text:
                bits = [x for x in (f"owner={owner}" if owner else "", f"file={file}" if file else "", problem) if x]
                if fix:
                    bits.append("fix: " + fix)
                text = "; ".join(bits)
            if not text.strip():
                continue
            out.append(
                CritiqueItem(
                    item_id=str(row.get("id") or row.get("item_id") or f"c-{uuid.uuid4().hex[:6]}"),
                    text=text.strip(),
                    score=str(row.get("score") or ""),
                    status="open",
                    owner=owner,
                    file=file,
                    problem=problem or text.strip(),
                    fix=fix,
                )
            )
        else:
            text = str(row).strip()
            if text:
                out.append(CritiqueItem(item_id=f"c-{uuid.uuid4().hex[:6]}", text=text, status="open"))
    return out


def _apply_scores(board: Board, content: Any) -> None:
    mapping: dict[str, str] = {}
    if isinstance(content, dict) and not any(k in content for k in ("id", "item_id")):
        mapping = {str(k): str(v) for k, v in content.items()}
    else:
        for item in _parse_critiques(content):
            mapping[item.item_id] = item.score or item.text
    for item in board.critiques:
        if item.item_id in mapping:
            item.score = mapping[item.item_id]


def _apply_status(board: Board, content: Any) -> None:
    mapping: dict[str, str] = {}
    if isinstance(content, dict) and "status" not in content:
        mapping = {str(k): str(v) for k, v in content.items()}
    elif isinstance(content, dict):
        mapping[str(content.get("id") or content.get("item_id") or "")] = str(content.get("status") or "")
    elif isinstance(content, list):
        for row in content:
            if isinstance(row, dict):
                mapping[str(row.get("id") or row.get("item_id") or "")] = str(row.get("status") or "")
    allowed = {"open", "discarded", "avoided", "implemented"}
    for item in board.critiques:
        nxt = mapping.get(item.item_id)
        if nxt and str(nxt).lower() in allowed:
            item.status = str(nxt).lower()


def record_vote(board: Board, role: str, vote: str) -> dict[str, Any]:
    if role not in VOTING_ROLES:
        return {"ok": False, "error": "no_vote"}
    if not board.vote_open:
        return {"ok": False, "error": "vote_closed"}
    mark = str(vote or "").strip().lower()
    if mark in {"y", "ship", "pass", "true"}:
        mark = "yes"
    if mark in {"n", "reject", "fail", "false"}:
        mark = "no"
    if mark not in {"yes", "no"}:
        return {"ok": False, "error": "bad_vote"}
    board.last_vote[role] = mark
    return {"ok": True, "vote": mark}


def infer_vote(text: str) -> str | None:
    blob = str(text or "").strip().lower()
    if not blob:
        return None
    first = re.split(r"[\s,.:;]+", blob, maxsplit=1)[0]
    if first in {"yes", "y", "ship", "pass", "true"}:
        return "yes"
    if first in {"no", "n", "reject", "fail", "false"}:
        return "no"
    if re.search(r'"vote"\s*:\s*"(yes|y|ship)"', blob):
        return "yes"
    if re.search(r'"vote"\s*:\s*"(no|n|reject)"', blob):
        return "no"
    return None


def _view(board: Board, role: str, stage: str = "") -> str:
    plan_only = role == "manager" and stage == "plan"
    chunks = [
        f"phase={board.phase} round={board.round} vote_open={board.vote_open} "
        f"qualified={board.qualified} harness_ok={board.harness_ok} smoke_ok={board.smoke_ok} "
        f"targets_source={board.targets_source or '-'}"
    ]
    if board.inventory:
        chunks.append("## inventory\n" + inventory_text(board.inventory))
    if not plan_only and board.data_card and role in {"manager", "coder", "tester", "critique", "evaluator"}:
        chunks.append("## data card\n" + board.data_card)
    chunks.append("## ownership\n" + OWNERSHIP_RULES)
    if board.done_detail and role in {"manager", "coder", "evaluator"}:
        chunks.append("## done\n" + board.done_detail)
    if board.smoke_detail:
        chunks.append("## smoke\n" + board.smoke_detail)
    if board.next_fix:
        chunks.append("## next_fix\n" + json.dumps(board.next_fix, ensure_ascii=True))
    if board.last_eval:
        chunks.append("## results\n" + board.last_eval)
    if board.targets:
        chunks.append("## targets (locked)\n" + json.dumps(board.targets, ensure_ascii=True))
    if board.qualify_detail:
        chunks.append("## qualify\n" + board.qualify_detail)
    if board.trial_scores:
        chunks.append("## scores\n" + json.dumps(board.trial_scores, ensure_ascii=True))
    if not plan_only and board.coding_rules:
        chunks.append("## coding rules\n" + board.coding_rules)
    if not plan_only and board.test_plan and role in {"manager", "coder", "tester", "critique", "evaluator"}:
        chunks.append("## test plan\n" + board.test_plan)
    if not plan_only and board.features:
        chunks.append("## features\n" + board.features)
    if (
        not plan_only
        and role in {"manager", "coder", "critique", "documenter", "drafter", "writer"}
        and board.architecture
    ):
        chunks.append("## architecture\n" + board.architecture)
    if not plan_only and role in {"coder", "tester", "critique"} and board.code:
        chunks.append("## code\n" + board.code)
    if board.tests and role in {"manager", "tester", "critique", "evaluator"}:
        lines = [f"- {t.name}: {t.status} {t.detail}".rstrip() for t in board.tests]
        chunks.append("## tests\n" + "\n".join(lines))
    if board.critiques and role in {
        "manager",
        "coder",
        "tester",
        "critique",
        "evaluator",
        "documenter",
        "critic",
    }:
        lines = [f"- {c.item_id} [{c.status}/{c.score or '-'}] {c.text}" for c in board.critiques]
        chunks.append("## critiques\n" + "\n".join(lines))
    if board.docs and role in {"documenter", "writer", "drafter", "critic"}:
        chunks.append("## docs\n" + board.docs)
    if board.last_vote:
        chunks.append("## last vote\n" + json.dumps(board.last_vote, ensure_ascii=False))
    return "\n\n".join(chunks)


def _clip(text: str, cap: int) -> str:
    body = str(text or "")
    if len(body) <= cap:
        return body
    return body[: cap - 1] + "…"


def _coding_answer(board: Board, box: Sandbox, notes: list[str]) -> str:
    files = box.listing(20)
    if board.vote_open and board.last_vote:
        vote = json.dumps(board.last_vote, ensure_ascii=False)
    else:
        vote = "(not opened)"
    body = (board.docs or board.features or "").strip()
    bits = [
        f"Committee phase {board.phase} round {board.round}. Vote: {vote}",
        f"Qualify: {'yes' if board.qualified else 'no'} ({board.qualify_detail or 'n/a'})",
        "Targets: " + json.dumps(board.targets, ensure_ascii=True),
        body,
        "Files:\n" + files,
    ]
    if notes:
        bits.append("\n".join(notes))
    return "\n\n".join(b for b in bits if b).strip()


def _review_answer(box: Sandbox, user_text: str) -> str:
    files = box.listing(20)
    if files != "(empty)":
        return f"Review files:\n{files}"
    return f"High-stakes review of:\n{user_text}"


def _result(
    board: Board,
    box: Sandbox,
    notes: list[str],
    reply: str = "",
    stopped: bool = False,
    rounds: list[dict[str, Any]] | None = None,
    coding_log: Path | None = None,
    coding_session: Path | None = None,
) -> dict[str, Any]:
    pdfs = [str(p) for p in box.pdfs()]
    return {
        "ok": not stopped,
        "stopped": stopped,
        "reply": reply,
        "pdf_paths": pdfs,
        "profile_update": dict(board.profile_update),
        "keep_dir": str(box.root),
        "notes": notes,
        "files": box.listing(),
        "qualified": bool(board.qualified),
        "vote_open": bool(board.vote_open),
        "targets": list(board.targets),
        "targets_source": board.targets_source,
        "scores": {k: list(v) for k, v in board.trial_scores.items()},
        "qualify_detail": board.qualify_detail,
        "rounds": list(rounds or []),
        "coding_log": str(coding_log) if coding_log else "",
        "coding_session": str(coding_session) if coding_session else "",
    }


def profile_snippet(update: dict[str, Any]) -> str:
    if not update:
        return ""
    lines: list[str] = []
    for key, value in update.items():
        if isinstance(value, list):
            shown = ", ".join(str(v) for v in value if str(v).strip())
        else:
            shown = str(value).strip()
        if shown:
            lines.append(f"{key}: {shown}")
    return "\n".join(lines)


_FLASHY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Flashy</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: conic-gradient(from 0.15turn, #ff2d95, #5b8def, #00e5a8, #ff2d95);
      animation: hue 8s linear infinite; color: #fff; font-family: system-ui, sans-serif; }
    @keyframes hue { to { filter: hue-rotate(360deg); } }
    h1 { text-shadow: 0 0 28px #fff; }
  </style>
</head>
<body>
  <h1>Flashy</h1>
</body>
</html>
"""

_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Landing</title>
  <style>
    body { margin: 0; font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }
    main { max-width: 40rem; margin: 12vh auto; padding: 0 1.5rem; }
    button { background: #38bdf8; color: #0f172a; border: 0; padding: 0.6rem 1rem; font-weight: 700; cursor: pointer; }
  </style>
</head>
<body>
  <main>
    <h1>Hello</h1>
    <p>A small landing page.</p>
    <button type="button">Start</button>
  </main>
</body>
</html>
"""

_HELLO_FN = '''def hello(name: str = "world") -> str:
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(hello())
'''

_HELLO_CLI = '''import argparse

parser = argparse.ArgumentParser(description="hello CLI")
parser.add_argument("name", nargs="?", default="world")
args = parser.parse_args()
print(f"Hello, {args.name}!")
'''

_TODO_CLASS = '''class TodoList:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, text: str) -> None:
        self.items.append(text)

    def done(self, index: int) -> str:
        return self.items.pop(index)
'''

_MATRIX = '''def matmul(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    n, m, p = len(a), len(a[0]), len(b[0])
    out = [[0] * p for _ in range(n)]
    for i in range(n):
        for k in range(m):
            for j in range(p):
                out[i][j] += a[i][k] * b[k][j]
    return out
'''
