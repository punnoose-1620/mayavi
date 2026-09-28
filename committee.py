"""Sequential coding/review committee for USB chat. One GGUF. No factory imports."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

YES_FOR_COMMIT = 4
MAX_ROUNDS = 2
MAX_TOOL_STEPS = 3
VIEW_CHARS = 1400
EXECUTE_TIMEOUT = 30
CLONE_TIMEOUT = 120
WRITE_EXT = {".py", ".txt", ".md", ".html", ".css", ".js", ".json", ".csv"}
VOTING_ROLES = ("manager", "coder", "tester", "critique", "evaluator")

SECTION_ALIASES = {
    "targets": "features",
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
}
SECTION_WRITERS = {
    "coding_rules": frozenset({"factory", "manager"}),
    "features": frozenset({"manager", "drafter"}),
    "architecture": frozenset({"manager", "drafter"}),
    "code": frozenset({"coder"}),
    "tests": frozenset({"tester"}),
    "critiques": frozenset({"critique", "critic"}),
    "critique_scores": frozenset({"evaluator"}),
    "critique_status": frozenset({"manager"}),
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


@dataclass
class Board:
    coding_rules: str = ""
    features: str = ""
    architecture: str = ""
    code: str = ""
    tests: list[TestItem] = field(default_factory=list)
    critiques: list[CritiqueItem] = field(default_factory=list)
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
            if path.is_file():
                rows.append(str(path.relative_to(self.root)).replace("\\", "/"))
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


def parse_committee_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    decoder = json.JSONDecoder()
    i = text.find("{")
    while i >= 0:
        try:
            obj, _end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            nxt = text.find("{", i + 1)
            i = nxt
            continue
        if isinstance(obj, dict):
            return obj
        nxt = text.find("{", i + 1)
        i = nxt
    return {}


def yes_count(votes: dict[str, str]) -> int:
    return sum(1 for role in VOTING_ROLES if str(votes.get(role) or "").lower() in {"yes", "y", "ship"})


def should_commit(votes: dict[str, str]) -> bool:
    return yes_count(votes) >= YES_FOR_COMMIT


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
    web_digest: str = "",
    stop_event=None,
    status: StatusFn | None = None,
    build_pdf: Callable[[str, str], bytes] | None = None,
) -> dict[str, Any]:
    box = Sandbox(keep_dir)
    notes: list[str] = []
    if github_url:
        cloned = clone_github(github_url, box.root / "repo", status)
        if not cloned.get("ok"):
            notes.append("GitHub clone failed: " + str(cloned.get("error") or "unknown"))
        else:
            notes.append("Cloned " + github_url)
    board = Board(
        coding_rules="Stdlib Python only. No pip. Tester runs .py files. No secrets on the board.",
        phase="0",
    )
    ctx = _Ctx(complete, board, box, user_text, web_digest, stop_event, status, build_pdf)
    if _stopped(stop_event):
        return _result(board, box, notes, stopped=True)
    _turn(ctx, "manager", "phase0")
    if not str(board.features or "").strip():
        board.features = (user_text or "phase 1").strip()[:800]
    if not str(board.architecture or "").strip():
        board.architecture = "scripts in the local work folder (.py / .html / .css / .js)"
    board.phase = "1"
    for rnd in range(1, MAX_ROUNDS + 1):
        if _stopped(stop_event) or board.stop or board.phase_complete:
            break
        board.round = rnd
        _turn(ctx, "coder", "code")
        _turn(ctx, "tester", "test")
        _turn(ctx, "critique", "critique")
        _turn(ctx, "evaluator", "evaluate")
        _turn(ctx, "manager", "plan")
        if _stopped(stop_event) or board.stop:
            break
        board.last_vote = {}
        for role in VOTING_ROLES:
            _turn(ctx, role, "vote")
            if _stopped(stop_event):
                break
        if should_commit(board.last_vote):
            notes.append(f"round {rnd} shipped ({yes_count(board.last_vote)}/5)")
            _turn(ctx, "documenter", "document")
        if yes_count(board.last_vote) == len(VOTING_ROLES):
            board.phase_complete = True
            board.stop = True
    reply = _coding_answer(board, box, notes)
    return _result(board, box, notes, reply=reply)


def run_review(
    *,
    complete: CompleteFn,
    user_text: str,
    keep_dir: Path,
    web_digest: str = "",
    stop_event=None,
    status: StatusFn | None = None,
    build_pdf: Callable[[str, str], bytes] | None = None,
) -> dict[str, Any]:
    box = Sandbox(keep_dir)
    board = Board(phase="review")
    ctx = _Ctx(complete, board, box, user_text, web_digest, stop_event, status, build_pdf)
    _turn(ctx, "drafter", "draft")
    _turn(ctx, "critic", "review")
    _turn(ctx, "writer", "write")
    reply = str(board.docs or board.features or "").strip() or _review_answer(box, user_text)
    return _result(board, box, [], reply=reply)


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


def _stopped(stop_event) -> bool:
    return stop_event is not None and stop_event.is_set()


def _turn(ctx: _Ctx, role: str, stage: str) -> None:
    if _stopped(ctx.stop_event):
        return
    if ctx.status:
        ctx.status(f"Committee: {role} ({stage})…")
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
            break
        parsed = parse_committee_json(raw)
        if not parsed and raw.strip():
            parsed = {"final": raw.strip()[:2000]}
        tool = str(parsed.get("tool") or "").strip()
        if not tool:
            break
        result = _dispatch(ctx, role, tool, parsed.get("args") if isinstance(parsed.get("args"), dict) else {})
        messages.append({"role": "assistant", "content": json.dumps(parsed, ensure_ascii=False)[:1500]})
        messages.append({"role": "user", "content": "Tool result:\n" + json.dumps(result, ensure_ascii=False)[:2000]})
    _ingest(ctx.board, role, parsed, raw)
    if stage != "vote":
        final = str(parsed.get("final") or "").strip()
        if final and role in {"drafter", "writer", "documenter", "manager"} and len(final) > len(ctx.board.docs or ""):
            if role in {"drafter", "writer", "documenter"}:
                ctx.board.docs = final[:4000]


def _system(ctx: _Ctx, role: str, stage: str) -> str:
    tools = _tools_for(role)
    view = _clip(_view(ctx.board, role), VIEW_CHARS)
    extra = ""
    if ctx.web_digest.strip():
        extra = "\nWeb notes:\n" + _clip(ctx.web_digest, 800)
    job = _job(role, stage)
    vote = ""
    if stage == "vote":
        vote = 'Ballot. Reply {"vote":"yes"} or {"vote":"no"}.\n'
    return (
        f"You are the {role} on a sequential local committee. One role. JSON only.\n"
        f"User request:\n{ctx.user_text}\n"
        f"Work folder files:\n{ctx.box.listing()}\n"
        f"Tools: {', '.join(tools) or '(none)'}\n"
        + job
        + vote
        + 'Tool: {"tool":"NAME","args":{...}}\n'
        'Board: {"board_update":{"section":"features","content":"..."}}\n'
        'If you learned durable user facts (name, title, skills, education, links), add "profile_update".\n'
        "Board:\n"
        + view
        + extra
    )


def _user(ctx: _Ctx, role: str, stage: str) -> str:
    if stage == "phase0":
        return "Write the contract. No code yet. JSON board_update for features and architecture."
    if stage == "vote":
        return "Cast your yes/no vote for this round."
    if stage == "draft":
        return "Draft the high-stakes document. JSON with final text. Do not execute code."
    if stage == "review":
        return "List blocking issues vs the request. JSON critiques. No sandbox."
    if stage == "write":
        return "Write the document with write_pdf or write_doc. JSON only."
    return f"Do the {role} job. User asked:\n{ctx.user_text}"


def _job(role: str, stage: str) -> str:
    if role == "manager" and stage == "phase0":
        return "Phase 0: contract only. Cover job, non-goals, files, tests. No code.\n"
    if role == "manager":
        return "Plan the next fix. Update features or critique_status. You may stop.\n"
    if role == "coder":
        return "Implement with sandbox_write. Stdlib only. Never execute.\n"
    if role == "tester":
        return "Write tests with sandbox_write then executeScriptInSandbox on .py files.\n"
    if role == "critique":
        return "Blocking bugs and missing features only.\n"
    if role == "evaluator":
        return "Score open critiques. critique_scores section.\n"
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
        return ["sandbox_write", "sandbox_read"]
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
        return ctx.box.write(str(args.get("path") or ""), str(args.get("content") or ""))
    if name == "sandbox_read":
        return ctx.box.read(str(args.get("path") or ""), int(args.get("start") or 0), int(args.get("end") or 4000))
    if name == "executeScriptInSandbox":
        return ctx.box.execute(str(args.get("path") or ""), int(args.get("timeout") or EXECUTE_TIMEOUT))
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
    if section in {"features", "architecture", "coding_rules", "code", "docs"}:
        text = str(content or "")
        if not text.strip():
            return {"ok": True, "skipped": "empty"}
        setattr(board, section, text)
        return {"ok": True, "section": section}
    if section == "tests":
        board.tests = _parse_tests(content)
    elif section == "critiques":
        board.critiques.extend(_parse_critiques(content))
    elif section == "critique_scores":
        _apply_scores(board, content)
    elif section == "critique_status":
        _apply_status(board, content)
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
            text = str(row.get("text") or row.get("body") or "")
            if not text.strip():
                continue
            out.append(
                CritiqueItem(
                    item_id=str(row.get("id") or row.get("item_id") or f"c-{uuid.uuid4().hex[:6]}"),
                    text=text.strip(),
                    score=str(row.get("score") or ""),
                    status="open",
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


def _view(board: Board, role: str) -> str:
    chunks = [f"phase={board.phase} round={board.round}"]
    if board.features:
        chunks.append("## features\n" + board.features)
    if role in {"manager", "coder", "critique", "documenter", "drafter", "writer"} and board.architecture:
        chunks.append("## architecture\n" + board.architecture)
    if role == "coder" and board.coding_rules:
        chunks.append("## coding rules\n" + board.coding_rules)
    if role in {"coder", "tester", "critique"} and board.code:
        chunks.append("## code\n" + board.code)
    if board.tests and role in {"manager", "tester", "critique", "evaluator"}:
        lines = [f"- {t.name}: {t.status} {t.detail}".rstrip() for t in board.tests]
        chunks.append("## tests\n" + "\n".join(lines))
    if board.critiques and role in {"manager", "critique", "evaluator", "documenter", "critic"}:
        lines = [f"- {c.item_id} [{c.status}] {c.text}" for c in board.critiques]
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
    vote = json.dumps(board.last_vote, ensure_ascii=False) if board.last_vote else "{}"
    body = (board.docs or board.features or "").strip()
    bits = [
        f"Committee phase {board.phase} round {board.round}. Vote: {vote}",
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


def _result(board: Board, box: Sandbox, notes: list[str], reply: str = "", stopped: bool = False) -> dict[str, Any]:
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
