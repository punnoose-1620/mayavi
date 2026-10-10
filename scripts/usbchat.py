"""Standalone USB chat helpers. No factory imports."""

from __future__ import annotations

import copy
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from xml.etree import ElementTree as ET

RAM_HEADROOM = 1.2
RAM_RESERVE = 2 * 1024**3
LOG_KEEP_DAYS = 30
NOTES_CAP = 4000
QUOTE_CAP = 400
DOC_CAP = 8000
OLDER_CAP = 12_000
SESSION_CAP = 16_000
N_CTX_DEFAULT = 4096
MAX_TOKENS_DEFAULT = 512
CODING_MAX_TOKENS = 1024
WEB_MAX_URLS = 3
WEB_HTML_CAP = 12_000
WEB_PAGE_CAP = 8_000
WEB_HTML_TOTAL_CAP = 80_000
WEB_MAX_CHUNKS = 8
DOC_BOARD_MAX_CHUNKS = 20
DOC_FILE_MAX_CHUNKS = 4
FOLDER_DOC_CAP = 80_000
FOLDER_DOC_PAGES = 80
FOLDER_MAX_FILES = 40
FOLDER_MAX_FILE_BYTES = 20 * 1024 * 1024
CTX_SLACK = 64
HTML_CHARS_PER_TOKEN = 3

LOG_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_\d{6}\.log$")
WEB_LOG_NAME = re.compile(r"^web_(\d{4}-\d{2}-\d{2})_\d{6}\.jsonl$")
_QUANT = re.compile(
    r"(?i)[-_.](Q\d+_K[_-][SML]|Q\d+_[01]|IQ\d+_X[SML]|IQ\d+_XXS|F16|F32|BF16)$"
)
_INSTRUCT = re.compile(r"(?i)[-_](Instruct|Chat|it)$")
_SS_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

ALLOWED_ATTACH = {".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv"}
FOLDER_SKIP_DIRS = frozenset(
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
    }
)
ATTACH_ICON = "📄"
FOLDER_ICON = "📁"
FILE_TYPE_ICONS = {
    ".pdf": "📕",
    ".docx": "📘",
    ".xlsx": "📗",
    ".txt": "📝",
    ".md": "📃",
    ".csv": "📊",
}
_ATTACH_MARK = re.compile(r"\[attached ([^\]]+)\]")


@dataclass(frozen=True)
class ModelChoice:
    path: Path
    label: str
    size: int
    required_ram: int
    tags: tuple[str, ...] = ()


def required_ram(file_size: int) -> int:
    return int(file_size * RAM_HEADROOM) + RAM_RESERVE


def fits_ram(file_size: int, free: int) -> bool:
    return free >= required_ram(file_size)


def pretty_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = _QUANT.sub("", stem)
    stem = _INSTRUCT.sub("", stem)
    stem = stem.replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip() or Path(filename).stem
    parts = stem.split()
    if len(parts) >= 2 and parts[1].lower().startswith(parts[0].lower()):
        parts = parts[1:]
    pretty: list[str] = []
    for word in parts:
        if word[-1:] in "bB" and word[:-1].replace(".", "").isdigit():
            pretty.append(word[:-1] + "B")
        elif any(ch.isdigit() for ch in word) and word[0].isalpha():
            pretty.append(word[0].upper() + word[1:])
        elif word.islower():
            pretty.append(word.capitalize())
        else:
            pretty.append(word)
    return " ".join(pretty)


def size_label(path: Path, file_size: int | None = None) -> str:
    size = path.stat().st_size if file_size is None else file_size
    gb = size / (1024**3)
    return f"{pretty_name(path.name)} ({gb:.1f} GB)"


def free_ram() -> int | None:
    if sys.platform == "win32":
        class _Mem(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        info = _Mem()
        info.dwLength = ctypes.sizeof(_Mem)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(info)):
            return None
        return int(info.ullAvailPhys)

    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        for line in meminfo.read_text(encoding="ascii", errors="ignore").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                return int(parts[1]) * 1024
    try:
        import psutil  # type: ignore

        return int(psutil.virtual_memory().available)
    except Exception:
        return None


def discover_ggufs(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*.gguf") if p.is_file())


def model_tags(root: Path) -> dict[str, tuple[str, ...]]:
    """Filename to job tags from models.json beside the GGUFs. Missing file means no tags."""
    path = root / "models.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    found: dict[str, tuple[str, ...]] = {}
    for item in data.get("models") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("filename") or "").strip()
        raw = item.get("tags") or []
        if not name or not isinstance(raw, list):
            continue
        tags = tuple(str(tag).strip() for tag in raw if str(tag).strip())
        if tags:
            found[name] = tags
    return found


def pickable_models(root: Path, free: int | None) -> list[ModelChoice]:
    tags_by_name = model_tags(root)
    choices: list[ModelChoice] = []
    for path in discover_ggufs(root):
        size = path.stat().st_size
        need = required_ram(size)
        if free is not None and free < need:
            continue
        choices.append(
            ModelChoice(
                path=path,
                label=size_label(path, size),
                size=size,
                required_ram=need,
                tags=tags_by_name.get(path.name, ()),
            )
        )
    choices.sort(key=lambda c: c.size, reverse=True)
    return choices


JOB_MODEL_MIN = int(1.8 * 1024**3)
JOB_MODEL_MAX = 6 * 1024**3


def job_model(choices: list[ModelChoice]) -> ModelChoice | None:
    """Smallest instruct model that still fits, preferring about 3B–7B over 1.5B or 14B."""
    if not choices:
        return None
    band = [item for item in choices if JOB_MODEL_MIN <= item.size <= JOB_MODEL_MAX]
    pool = band or list(choices)
    return min(pool, key=lambda item: item.size)


# Best measured file first. A name that is not listed sorts after these, larger files first.
TAG_RANK: dict[str, tuple[str, ...]] = {
    "coding": ("gemma-2-9b-it", "Meta-Llama-3.1-8B", "Qwen2.5-7B"),
    "documentation": ("Qwen3-8B", "Qwen2.5-7B"),
    "summary": ("Qwen3-8B", "gemma-2-9b-it", "qwen2.5-1.5b", "Meta-Llama-3.1-8B"),
    "report": ("gemma-2-9b-it", "Qwen3-8B", "qwen2.5-1.5b", "Meta-Llama-3.1-8B"),
    "ui-building": ("Qwen2.5-7B",),
    "search": ("Qwen3-8B", "Meta-Llama-3.1-8B"),
    "search-sift": (
        "gemma-2-9b-it",
        "Qwen2.5-7B",
        "Qwen2.5-3B",
        "Meta-Llama-3.1-8B",
        "Qwen3-8B",
        "qwen2.5-1.5b",
    ),
    "reading": ("gemma-2-9b-it", "Qwen3-8B", "Qwen2.5-7B", "Qwen2.5-3B"),
}

_INTENT_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ui-building", ("from top to bottom", "button order", "one screen", "kitchen timer", "tea timer", "user interface")),
    ("search-sift", ("saved search", "search result", "search page", "people also ask")),
    ("search", ("search quer", "search for")),
    ("summary", ("summarize", "summary", "tl;dr", "tldr", "in two sentences", "in four sentences")),
    ("report", ("plain text report", "status report", "blocker")),
    ("documentation", ("handoff", "coworker", "from that note")),
    ("reading", ("saved page", "side note", "from this page")),
    ("coding", ("debug", "buggy", "refactor", "syntax", "python", "javascript")),
)


def _has_phrase(text: str, phrase: str) -> bool:
    if " " in phrase:
        return phrase in text
    return re.search(rf"\b{re.escape(phrase)}\b", text) is not None


def intent_tag(text: str, *, coding: bool = False, web: bool = False) -> str:
    """Job tag for this message. Empty means keep the model the user already picked."""
    if coding:
        return "coding"
    if web:
        return "search"
    lowered = str(text or "").lower()
    for tag, phrases in _INTENT_RULES:
        if any(_has_phrase(lowered, phrase) for phrase in phrases):
            return tag
    return ""


def _rank_index(filename: str, ranks: tuple[str, ...]) -> int:
    low = filename.casefold()
    for index, key in enumerate(ranks):
        if key.casefold() in low:
            return index
    return len(ranks)


def route_model(
    choices: list[ModelChoice],
    user_text: str,
    *,
    coding: bool = False,
    web: bool = False,
) -> tuple[ModelChoice | None, str]:
    """Best loaded model whose tag matches the message. None keeps the current choice."""
    tag = intent_tag(user_text, coding=coding, web=web)
    if not tag:
        return None, ""
    pool = [item for item in choices if tag in item.tags]
    if not pool and web:
        tag = "search-sift"
        pool = [item for item in choices if tag in item.tags]
    if not pool:
        return None, ""
    ranks = TAG_RANK.get(tag, ())
    best = min(pool, key=lambda item: (_rank_index(item.path.name, ranks), -item.size))
    return best, tag


def smallest_model(choices: list[ModelChoice]) -> ModelChoice | None:
    if not choices:
        return None
    return min(choices, key=lambda item: item.size)


def default_models_root(here: Path | None = None) -> Path:
    here = (here or Path(__file__).resolve().parent).resolve()
    env = os.environ.get("MODELS_DIR", "").strip()
    if env:
        env_path = Path(env)
        if env_path.is_dir() and discover_ggufs(env_path):
            return env_path
    for candidate in (here, here.parent):
        if discover_ggufs(candidate):
            return candidate
    if sys.platform == "win32":
        for letter in "EFGHIJKLMNOP":
            drive = Path(f"{letter}:/")
            if discover_ggufs(drive):
                return drive
    backup = here.parent / "models"
    if discover_ggufs(backup):
        return backup
    return here


def project_home(here: Path | None = None) -> Path:
    """Stick root. Scripts live in scripts\\; logs, PDFs, and GGUFs sit beside that folder."""
    here = (here or Path(__file__).resolve().parent).resolve()
    if here.name.lower() == "scripts":
        return here.parent
    return here


def documentation_dir(here: Path | None = None) -> Path:
    home = project_home(here)
    docs = home / "documentation"
    if docs.is_dir():
        return docs
    return home


def usb_root(models_root: Path, here: Path | None = None) -> Path:
    here = (here or Path(__file__).resolve().parent).resolve()
    home = project_home(here)
    if not discover_ggufs(models_root):
        return home
    if models_root.name.lower() == "models":
        return home
    return models_root


def notes_path(root: Path) -> Path:
    return root / "notes.md"


def profile_path(root: Path) -> Path:
    return root / "profile.md"


PROFILE_TEMPLATE = """# Professional profile

The job application committee uses only this file. Write your real background.
Include contact details, roles, employers, dates, skills, education, and results you can point to.
Leave out skills, titles, and numbers you do not have.

"""


def read_profile(path: Path, cap: int = 24_000) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:cap]


def logs_dir(root: Path) -> Path:
    return root / "logs"


def coding_logs_dir(root: Path) -> Path:
    return root / "coding-logs"


def outputs_dir(root: Path) -> Path:
    path = root / "outputs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_stick_dirs(root: Path) -> tuple[Path, Path]:
    """Create logs, coding-logs, and outputs on the stick. Raises OSError if they are not writable."""
    logs = logs_dir(root)
    coding = coding_logs_dir(root)
    logs.mkdir(parents=True, exist_ok=True)
    coding.mkdir(parents=True, exist_ok=True)
    outputs = outputs_dir(root)
    for folder in (logs, coding, outputs):
        probe = folder / ".usb-chat-write"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    return logs, outputs


def new_coding_session_dir(root: Path, slug: str = "run") -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(slug or "run")).strip("-.")[:40] or "run"
    when = datetime.now()
    folder = coding_logs_dir(root) / f"{when:%Y-%m-%d_%H%M%S}_{safe}"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def new_coding_log_path(root: Path, slug: str = "run") -> Path:
    return new_coding_session_dir(root, slug) / "generic.jsonl"


def build_markdown_pdf(title: str, markdown: str) -> bytes:
    return build_guide_pdf(title, markdown)


def guide_markdown(home: Path, docs: Path, stem: str) -> Path | None:
    """README.md is at the repo root for GitHub. On the USB every Markdown file is in documentation\\."""
    if stem == "README":
        candidates = (home / "README.md", docs / "README.md")
    else:
        candidates = (docs / f"{stem}.md", home / f"{stem}.md")
    for src in candidates:
        if src.is_file():
            return src
    return None


def write_guide_pdfs(folder: Path | None = None) -> list[Path]:
    """Write the guide PDFs at the project root. Markdown sources stay in documentation\\, except README.md at the repo root."""
    here = (folder or Path(__file__).resolve().parent).resolve()
    home = project_home(here)
    docs = documentation_dir(here)
    written: list[Path] = []
    for stem in ("README", "REQUIREMENTS", "CHANGELOG", "TestResults"):
        src = guide_markdown(home, docs, stem)
        if src is None:
            continue
        dest = home / f"{stem}.pdf"
        dest.write_bytes(build_markdown_pdf(stem, src.read_text(encoding="utf-8", errors="replace")))
        written.append(dest)
    return written


def new_keep_dir(root: Path, slug: str = "run") -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(slug or "run")).strip("-.")[:40] or "run"
    when = datetime.now()
    path = outputs_dir(root) / f"{when:%Y-%m-%d_%H%M%S}_{safe}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_text_pdf(title: str, body: str) -> bytes:
    return build_transcript_pdf(title, [("Document", body)])


def open_local_file(path: Path) -> Path:
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return path
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener is None:
        raise RuntimeError("no opener for this file")
    subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return path


def open_html_document(html_text: str) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="usb-chat-", suffix=".html", delete=False)
    handle.write(str(html_text or "").encode("utf-8"))
    handle.close()
    return open_local_file(Path(handle.name))


def read_notes(path: Path, cap: int = NOTES_CAP) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    return text[:cap]


def append_notes(path: Path, extra: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = extra.rstrip() + "\n"
    if path.is_file() and path.stat().st_size:
        existing = path.read_text(encoding="utf-8", errors="replace")
        if not existing.endswith("\n"):
            existing += "\n"
        path.write_text(existing + "\n" + body, encoding="utf-8")
    else:
        path.write_text(body, encoding="utf-8")


def new_session_path(log_root: Path, when: datetime | None = None) -> Path:
    when = when or datetime.now()
    log_root.mkdir(parents=True, exist_ok=True)
    return log_root / f"{when:%Y-%m-%d_%H%M%S}.log"


def session_date(path: Path) -> date | None:
    match = LOG_NAME.match(path.name)
    if not match:
        return None
    return date.fromisoformat(match.group(1))


def web_log_date(path: Path) -> date | None:
    match = WEB_LOG_NAME.match(path.name)
    if not match:
        return None
    return date.fromisoformat(match.group(1))


def purge_old_logs(log_root: Path, today: date | None = None, keep_days: int = LOG_KEEP_DAYS) -> list[Path]:
    today = today or date.today()
    cutoff = today - timedelta(days=keep_days)
    removed: list[Path] = []
    if not log_root.is_dir():
        return removed
    for path in log_root.iterdir():
        stamped = session_date(path) or web_log_date(path)
        if stamped is None or stamped >= cutoff:
            continue
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed


def new_web_log_path(log_root: Path, when: datetime | None = None) -> Path:
    when = when or datetime.now()
    log_root.mkdir(parents=True, exist_ok=True)
    return log_root / f"web_{when:%Y-%m-%d_%H%M%S}.jsonl"


def append_web_event(path: Path, event: dict) -> None:
    row = {"time": utc_now(), **event}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def list_sessions(log_root: Path) -> list[Path]:
    if not log_root.is_dir():
        return []
    files = [p for p in log_root.glob("*.log") if session_date(p)]
    files.sort(reverse=True)
    return files


def append_turn(path: Path, turn: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(turn, ensure_ascii=False) + "\n")


def load_turns(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    turns: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            turns.append(row)
    return turns


def file_type_icon(path_or_name: str) -> str:
    return FILE_TYPE_ICONS.get(Path(str(path_or_name)).suffix.lower(), ATTACH_ICON)


def attach_label(path_or_name: str) -> str:
    return f"{file_type_icon(path_or_name)} {path_or_name}"


def folder_attach_block(folder: str, files: list[str], truncated: bool = False) -> str:
    """History block: folder path, then each file name with its type icon."""
    lines = [f"{FOLDER_ICON} {folder}"]
    for item in files:
        text = str(item or "").strip()
        if not text:
            continue
        lines.append(f"- {file_type_icon(text)} {Path(text).name}")
    if truncated:
        lines.append(f"- … only the first {FOLDER_MAX_FILES} files")
    return "\n".join(lines)


def _token_phrase(tokens: int) -> str:
    noun = "token" if tokens == 1 else "tokens"
    return f"{tokens:,} {noun}"


def attach_row_file(name: str, text: str) -> str:
    """Attach-row label: file name and token estimate. History still uses the full path."""
    return f"{name} · {_token_phrase(estimate_tokens(text))}"


def attach_row_folder(folder_name: str, file_count: int, tokens: int, truncated: bool = False) -> str:
    """Attach-row label: folder name, readable file count, and total tokens."""
    noun = "file" if file_count == 1 else "files"
    label = f"{folder_name} · {file_count} {noun} · {_token_phrase(tokens)}"
    if truncated:
        label += f" · first {FOLDER_MAX_FILES} only"
    return label


def folder_extracted_tokens(files: list[Path]) -> int:
    """Token estimate for the text the folder reader will use."""
    total = 0
    for path in files:
        try:
            text = extract_document(path, cap=FOLDER_DOC_CAP, max_pages=FOLDER_DOC_PAGES)
        except Exception:
            text = ""
        total += estimate_tokens(text)
    return total


def rewrite_attach_markers(text: str) -> str:
    return _ATTACH_MARK.sub(lambda m: attach_label(m.group(1)), text)


def display_user_prompt(turn: dict) -> str:
    """History line for a logged user turn, including an attach note if present."""
    shown = str(turn.get("shown") or "").strip()
    if shown:
        return rewrite_attach_markers(shown)
    prompt = str(turn.get("prompt") or "")
    names = [str(n) for n in (turn.get("attached") or []) if n]
    if not names:
        return prompt
    prefix = "\n".join(attach_label(n) for n in names)
    return f"{prefix}\n{prompt}" if prompt else prefix


def _budget_turns(turns: list[dict], budget: int) -> list[dict]:
    kept: list[dict] = []
    used = 0
    for turn in reversed(turns):
        prompt = str(turn.get("prompt") or "")
        response = str(turn.get("response") or "")
        cost = len(prompt) + len(response)
        if kept and used + cost > budget:
            break
        kept.append(turn)
        used += cost
    kept.reverse()
    return kept


def build_chat_messages(
    *,
    notes: str = "",
    older_turns: list[dict] | None = None,
    session_turns: list[dict] | None = None,
    quote: str = "",
    attachments: list[dict] | None = None,
    user_text: str,
) -> list[dict[str, str]]:
    system = (
        "You are a local USB chat assistant. Answer helpfully and directly. "
        "Attached documents are read-only context."
    )
    if notes.strip():
        system += "\n\nUser notes:\n" + notes.strip()[:NOTES_CAP]

    messages = [{"role": "system", "content": system}]
    for turn in _budget_turns(older_turns or [], OLDER_CAP):
        if turn.get("prompt"):
            messages.append({"role": "user", "content": str(turn["prompt"])})
        if turn.get("response"):
            messages.append({"role": "assistant", "content": str(turn["response"])})
    for turn in _budget_turns(session_turns or [], SESSION_CAP):
        if turn.get("prompt"):
            messages.append({"role": "user", "content": str(turn["prompt"])})
        if turn.get("response"):
            messages.append({"role": "assistant", "content": str(turn["response"])})

    parts: list[str] = []
    if quote.strip():
        parts.append("Replying to:\n> " + quote.strip()[:QUOTE_CAP])
    for att in attachments or []:
        label = str(att.get("path") or att.get("name") or "document")
        body = str(att.get("text") or "")[:DOC_CAP]
        parts.append(f"Attached {label}:\n{body}")
    parts.append(user_text)
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages


def extract_json_object(text: str) -> dict:
    blob = (text or "").strip()
    if blob.startswith("```"):
        blob = re.sub(r"^```(?:json)?\s*", "", blob, count=1, flags=re.IGNORECASE)
        blob = re.sub(r"\s*```\s*$", "", blob)
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(blob[start : end + 1])
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _stopped(stop_event) -> bool:
    return stop_event is not None and stop_event.is_set()


def _with_instruction(
    messages: list[dict[str, str]],
    system_add: str,
    user_add: str,
) -> list[dict[str, str]]:
    cloned = copy.deepcopy(messages)
    if cloned and cloned[0].get("role") == "system":
        cloned[0]["content"] = str(cloned[0].get("content") or "") + "\n\n" + system_add
    else:
        cloned.insert(0, {"role": "system", "content": system_add})
    cloned.append({"role": "user", "content": user_add})
    return cloned


def token_budget(n_ctx: int) -> int:
    return max(256, int(n_ctx) - MAX_TOKENS_DEFAULT - CTX_SLACK)


def messages_tokens(messages: list[dict[str, str]]) -> int:
    return estimate_tokens(flatten_prompt(messages))


def chunk_text(text: str, max_chars: int, max_chunks: int = WEB_MAX_CHUNKS) -> list[str]:
    text = text or ""
    if not text:
        return []
    limit = max(400, int(max_chars))
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    cap = max(1, int(max_chunks))
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + limit // 2, end)
            if cut > start:
                end = cut + 1
        chunks.append(text[start:end])
        start = end
        if len(chunks) >= cap:
            break
    return chunks


def lean_web_messages(user_text: str, system: str, blob: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"User request:\n{user_text}\n\n{blob}"},
    ]


def _blob_char_budget(n_ctx: int, user_text: str, system: str, chars_per_token: int = HTML_CHARS_PER_TOKEN) -> int:
    overhead = estimate_tokens(system) + estimate_tokens(f"User request:\n{user_text}\n\n") + 32
    room = max(64, token_budget(n_ctx) - overhead)
    return max(400, room * chars_per_token)


def _context_overflow(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "exceed context" in text or "context window" in text


def merge_filter_specs(specs: list[dict]) -> dict:
    keep_pairs: list[list[str]] = []
    classes: list[str] = []
    ids: list[str] = []
    saw_keep = False
    for spec in specs:
        if not spec:
            continue
        mode = str(spec.get("mode") or "remove").strip().lower()
        raw_pairs = spec.get("pairs") or spec.get("keep") or []
        if mode in {"keep", "isolate"} and raw_pairs:
            saw_keep = True
        if isinstance(raw_pairs, list):
            for item in raw_pairs:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    keep_pairs.append([str(item[0]).strip(), str(item[1]).strip()])
                elif isinstance(item, dict):
                    keep_pairs.append(
                        [
                            str(item.get("class") or item.get("class_") or "").strip(),
                            str(item.get("id") or "").strip(),
                        ]
                    )
        classes.extend(str(c).strip() for c in (spec.get("classes") or []) if str(c).strip())
        ids.extend(str(i).strip() for i in (spec.get("ids") or []) if str(i).strip())
    if saw_keep:
        uniq: list[list[str]] = []
        seen: set[tuple[str, str]] = set()
        for class_, id_ in keep_pairs:
            key = (class_, id_)
            if not class_ and not id_ or key in seen:
                continue
            seen.add(key)
            uniq.append([class_, id_])
        return {"mode": "keep", "pairs": uniq}
    return {
        "mode": "remove",
        "classes": list(dict.fromkeys(classes)),
        "ids": list(dict.fromkeys(ids)),
    }


def normalize_urls(raw, *, limit: int = WEB_MAX_URLS) -> list[str]:
    import search

    values: list[str] = []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, list):
        values = [str(item) for item in raw]
    found: list[str] = []
    seen: set[str] = set()
    for item in values:
        url = search.normalize_result_url(item)
        if url is None or url in seen:
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= limit:
            break
    return found


def web_search_available() -> bool:
    try:
        import search  # noqa: F401

        return True
    except Exception:
        return False


def _safe_complete(complete, messages: list[dict[str, str]], log) -> str:
    try:
        return complete(messages)
    except Exception as exc:
        if _context_overflow(exc):
            if log is not None:
                log({"step": "context_overflow", "error": str(exc)})
            return ""
        raise


def ask_over_chunks(
    *,
    complete,
    user_text: str,
    system: str,
    blob: str,
    n_ctx: int,
    stop_event,
    status,
    status_label: str,
    parse,
    merge,
    log,
    chars_per_token: int = HTML_CHARS_PER_TOKEN,
):
    """Run a silent model call per chunk. Returns (merged, stopped)."""
    budget = token_budget(n_ctx)
    chunks = chunk_text(blob, _blob_char_budget(n_ctx, user_text, system, chars_per_token))
    if not chunks:
        return merge([]), False
    parsed: list = []
    raws: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        if _stopped(stop_event):
            return merge(parsed), True
        label = status_label if len(chunks) == 1 else f"{status_label} ({index}/{len(chunks)})"
        status(f"{label}…")
        prefix = f"Part {index} of {len(chunks)}.\n" if len(chunks) > 1 else ""
        msgs = lean_web_messages(user_text, system, prefix + chunk)
        while messages_tokens(msgs) > budget and len(chunk) > 400:
            chunk = chunk[: max(400, len(chunk) * 3 // 4)]
            msgs = lean_web_messages(user_text, system, prefix + chunk)
        raw = _safe_complete(complete, msgs, log)
        raws.append(raw)
        parsed.append(parse(raw))
    if log is not None:
        log({"step": "chunks", "label": status_label, "parts": len(chunks), "raw": [r[:2000] for r in raws]})
    return merge(parsed), False


def run_web_search(
    *,
    complete,
    messages: list[dict[str, str]],
    user_text: str,
    stop_event,
    log_path: Path,
    status,
    n_ctx: int = N_CTX_DEFAULT,
) -> dict:
    """Model-guided Google scrape. Intermediate steps go to log_path, not History."""
    import search

    result: dict = {
        "ok": False,
        "query": "",
        "urls": [],
        "excerpts": [],
        "error": "",
        "stopped": False,
    }

    def log(event: dict) -> None:
        append_web_event(log_path, event)

    if _stopped(stop_event):
        result["stopped"] = True
        result["error"] = "stopped"
        return result

    status("Web Search: writing a query…")
    query_system = (
        "Reply with JSON only, no markdown. Choose one short Google query for the latest user request."
    )
    query_msgs = _with_instruction(messages, query_system, 'Return {"query":"..."} now.')
    if messages_tokens(query_msgs) > token_budget(n_ctx):
        query_msgs = lean_web_messages(user_text, query_system, 'Return {"query":"..."} now.')
    query_raw = _safe_complete(complete, query_msgs, log)
    query_spec = extract_json_object(query_raw)
    query = str(query_spec.get("query") or "").strip() or user_text.strip()
    result["query"] = query
    log({"step": "query", "raw": query_raw[:4000], "query": query})
    if _stopped(stop_event):
        result["stopped"] = True
        result["error"] = "stopped"
        return result

    status("Web Search: fetching Google…")
    soup = search.search_google(query)
    if soup is None:
        result["error"] = "Google search failed (blocked, empty, or offline)."
        log({"step": "serp", "ok": False, "error": result["error"]})
        return result
    log({"step": "serp", "ok": True, "html_chars": len(str(soup))})

    serp_html = search.soup_html(soup, WEB_HTML_TOTAL_CAP)
    filter_system = (
        "You are looking at search-result HTML, which may be only a part. "
        "Reply with JSON only, no markdown. "
        'Strip noise with {"mode":"remove","classes":["..."],"ids":["..."]} '
        'or keep only result blocks with {"mode":"keep","pairs":[["class","id"],...]}. '
        "Each keep pair is a class and id on the SAME tag. Empty lists leave the HTML as-is."
    )
    filter_spec, stopped = ask_over_chunks(
        complete=complete,
        user_text=user_text,
        system=filter_system,
        blob="HTML:\n" + serp_html,
        n_ctx=n_ctx,
        stop_event=stop_event,
        status=status,
        status_label="Web Search: cleaning results",
        parse=extract_json_object,
        merge=merge_filter_specs,
        log=log,
    )
    if stopped:
        result["stopped"] = True
        result["error"] = "stopped"
        return result
    soup = search.apply_markup_filter(soup, filter_spec)
    log({"step": "serp_filter", "spec": filter_spec})
    if _stopped(stop_event):
        result["stopped"] = True
        result["error"] = "stopped"
        return result

    url_system = (
        "Reply with JSON only, no markdown. Pick at most 3 http(s) URLs from this "
        "search HTML (it may be only a part) that best help the user. "
        'Return {"urls":["https://..."]}. Use [] if none.'
    )

    def merge_url_specs(specs: list[dict]) -> dict:
        urls: list[str] = []
        for spec in specs:
            urls.extend(normalize_urls((spec or {}).get("urls"), limit=WEB_MAX_URLS))
        return {"urls": normalize_urls(urls, limit=WEB_MAX_URLS)}

    url_spec, stopped = ask_over_chunks(
        complete=complete,
        user_text=user_text,
        system=url_system,
        blob="HTML:\n" + search.soup_html(soup, WEB_HTML_TOTAL_CAP),
        n_ctx=n_ctx,
        stop_event=stop_event,
        status=status,
        status_label="Web Search: picking pages",
        parse=extract_json_object,
        merge=merge_url_specs,
        log=log,
    )
    if stopped:
        result["stopped"] = True
        result["error"] = "stopped"
        return result
    urls = normalize_urls((url_spec or {}).get("urls"), limit=WEB_MAX_URLS)
    if not urls:
        urls = search.extract_result_urls(soup, WEB_MAX_URLS)
    result["urls"] = urls
    log({"step": "urls", "urls": urls})
    if not urls:
        result["error"] = "No usable result URLs."
        return result

    excerpts: list[dict[str, str]] = []
    page_filter_system = (
        "You are looking at a web page, which may be only a part. Reply with JSON only, no markdown. "
        'Strip chrome with {"mode":"remove","classes":["..."],"ids":["..."]} '
        'or keep the article/content with {"mode":"keep","pairs":[["class","id"],...]}. '
        "Empty lists leave the HTML as-is."
    )
    for index, url in enumerate(urls, start=1):
        if _stopped(stop_event):
            result["stopped"] = True
            result["error"] = "stopped"
            result["excerpts"] = excerpts
            return result
        status(f"Web Search: fetching page {index}/{len(urls)}…")
        page = search.get_page_content(url)
        if page is None:
            log({"step": "page", "url": url, "ok": False})
            continue
        page_spec, stopped = ask_over_chunks(
            complete=complete,
            user_text=user_text,
            system=page_filter_system,
            blob=f"URL: {url}\n\nHTML:\n" + search.soup_html(page, WEB_HTML_TOTAL_CAP),
            n_ctx=n_ctx,
            stop_event=stop_event,
            status=status,
            status_label=f"Web Search: cleaning page {index}/{len(urls)}",
            parse=extract_json_object,
            merge=merge_filter_specs,
            log=log,
        )
        if stopped:
            result["stopped"] = True
            result["error"] = "stopped"
            result["excerpts"] = excerpts
            return result
        page = search.apply_markup_filter(page, page_spec)
        text = search.soup_text(page, WEB_PAGE_CAP)
        log({"step": "page", "url": url, "ok": True, "spec": page_spec, "chars": len(text)})
        if text:
            excerpts.append({"url": url, "text": text})

    result["excerpts"] = excerpts
    if not excerpts:
        result["error"] = "Could not read any result pages."
        return result
    result["ok"] = True
    return result


def format_web_excerpts(query: str, excerpts: list[dict[str, str]]) -> str:
    blocks = [f"Web search query: {query}"]
    for index, item in enumerate(excerpts, start=1):
        blocks.append(f"Page {index} ({item.get('url') or ''}):\n{item.get('text') or ''}")
    return "\n\n".join(blocks)


def _packed_excerpt_tokens(query: str, user_text: str, excerpts: list[dict[str, str]], system: str) -> int:
    return messages_tokens(lean_web_messages(user_text, system, format_web_excerpts(query, excerpts)))


def compress_web_excerpts(
    *,
    complete,
    query: str,
    user_text: str,
    excerpts: list[dict[str, str]],
    n_ctx: int,
    stop_event,
    status,
    log,
) -> tuple[list[dict[str, str]], bool]:
    """Shrink page text until a lean final prompt fits. Intermediate summaries stay off History."""
    answer_system = (
        "Answer the user from these web excerpts. Cite URLs in prose if useful. Do not dump HTML."
    )
    summarize_system = (
        "Summarize this excerpt for a later answer. Keep facts, names, numbers, and URLs. "
        "No HTML. A few short paragraphs. This may be only part of a page."
    )
    items = [{"url": str(item.get("url") or ""), "text": str(item.get("text") or "")} for item in excerpts]
    if _packed_excerpt_tokens(query, user_text, items, answer_system) <= token_budget(n_ctx):
        return items, False

    summarized: list[dict[str, str]] = []
    for index, item in enumerate(items, start=1):
        parts = chunk_text(
            item["text"],
            _blob_char_budget(n_ctx, user_text, summarize_system, chars_per_token=4),
        ) or [item["text"]]
        notes: list[str] = []
        for part_index, part in enumerate(parts, start=1):
            if _stopped(stop_event):
                return summarized, True
            label = (
                f"Web Search: summarizing page {index}/{len(items)}"
                if len(parts) == 1
                else f"Web Search: summarizing page {index}/{len(items)}, part {part_index}/{len(parts)}"
            )
            status(f"{label}…")
            prefix = f"URL: {item['url']}\n" + (f"Part {part_index} of {len(parts)}.\n" if len(parts) > 1 else "")
            raw = _safe_complete(
                complete,
                lean_web_messages(user_text, summarize_system, prefix + part),
                log,
            )
            notes.append(raw.strip() or part[:800])
        summarized.append({"url": item["url"], "text": "\n".join(notes)})
        if log is not None:
            log({"step": "page_summary", "url": item["url"], "parts": len(parts)})

    if _packed_excerpt_tokens(query, user_text, summarized, answer_system) <= token_budget(n_ctx):
        return summarized, False

    blob = format_web_excerpts(query, summarized)
    reduced: list[str] = []
    parts = chunk_text(blob, _blob_char_budget(n_ctx, user_text, summarize_system, chars_per_token=4)) or [blob]
    for part_index, part in enumerate(parts, start=1):
        if _stopped(stop_event):
            return [{"url": "combined", "text": "\n".join(reduced)}], True
        status(f"Web Search: combining notes ({part_index}/{len(parts)})…")
        raw = _safe_complete(
            complete,
            lean_web_messages(user_text, summarize_system, part),
            log,
        )
        reduced.append(raw.strip() or part[:800])
    combined = [{"url": "combined", "text": "\n".join(reduced)}]
    if _packed_excerpt_tokens(query, user_text, combined, answer_system) > token_budget(n_ctx):
        cap = _blob_char_budget(n_ctx, user_text, answer_system, chars_per_token=4)
        combined[0]["text"] = combined[0]["text"][:cap]
        if log is not None:
            log({"step": "excerpt_truncate", "chars": cap})
    return combined, False


def fit_web_answer_messages(
    *,
    complete,
    chat_messages: list[dict[str, str]],
    user_text: str,
    query: str,
    excerpts: list[dict[str, str]],
    n_ctx: int,
    stop_event,
    status,
    log,
) -> tuple[list[dict[str, str]], bool]:
    """Build the one History-visible prompt, compressing web text if it will not fit."""
    items, stopped = compress_web_excerpts(
        complete=complete,
        query=query,
        user_text=user_text,
        excerpts=excerpts,
        n_ctx=n_ctx,
        stop_event=stop_event,
        status=status,
        log=log,
    )
    if stopped:
        return [], True
    block = format_web_excerpts(query, items)
    extra = " Use the web excerpts when they help. Cite URLs in prose if useful. Do not dump HTML."
    fitted = [dict(msg) for msg in chat_messages]
    if fitted and fitted[0].get("role") == "system":
        fitted[0] = {"role": "system", "content": str(fitted[0].get("content") or "") + extra}
    fitted.append({"role": "user", "content": block})
    if messages_tokens(fitted) <= token_budget(n_ctx):
        return fitted, False
    lean = lean_web_messages(
        user_text,
        "You are a local USB chat assistant. Answer from the web excerpts. Cite URLs in prose if useful. Do not dump HTML.",
        block,
    )
    if messages_tokens(lean) > token_budget(n_ctx):
        cap = _blob_char_budget(
            n_ctx,
            user_text,
            "You are a local USB chat assistant. Answer from the web excerpts. Cite URLs in prose if useful. Do not dump HTML.",
            chars_per_token=4,
        )
        lean = lean_web_messages(
            user_text,
            "You are a local USB chat assistant. Answer from the web excerpts. Cite URLs in prose if useful. Do not dump HTML.",
            block[:cap],
        )
    return lean, False


DOC_NOTE_SYSTEM = (
    "You are reading attached documents for a later answer. This may be only one part of one file. "
    "Write notes that help answer the user. Keep facts, names, numbers, and the file path they came from. "
    "Leave out parts that do not help. A few short paragraphs."
)


def document_card(index: int, total: int, doc: dict) -> str:
    label = str(doc.get("path") or doc.get("name") or "document")
    body = str(doc.get("text") or "").strip() or "(empty)"
    return f"Document {index} of {total}: {label}\n{body}"


def format_document_board(docs: list[dict]) -> str:
    total = len(docs)
    return "\n\n".join(document_card(index, total, doc) for index, doc in enumerate(docs, start=1))


def _messages_with_document_block(messages: list[dict[str, str]], block: str) -> list[dict[str, str]]:
    cloned = copy.deepcopy(messages)
    if not cloned:
        cloned = [{"role": "user", "content": ""}]
    last = dict(cloned[-1])
    prior = str(last.get("content") or "").strip()
    body = f"Attached documents (read-only):\n{block}"
    last["content"] = f"{body}\n\n{prior}" if prior else body
    cloned[-1] = last
    return cloned


CONTINUE_PROMPT = "Read 20 parts. More of this folder is still unread. Continue? Yes or no."

_CONTINUE_YES = {
    "yes",
    "y",
    "yeah",
    "yep",
    "continue",
    "go on",
    "keep going",
    "go ahead",
    "carry on",
    "sure",
    "ok",
    "okay",
    "please",
    "please continue",
}
_CONTINUE_NO = {
    "no",
    "n",
    "nope",
    "stop",
    "done",
    "finish",
    "stop here",
    "that's enough",
    "thats enough",
    "do not continue",
    "don't continue",
}


def continue_intent(text: str) -> str | None:
    """Map a clear yes or no. Other wording returns None so a model can read it."""
    cleaned = re.sub(r"[^a-z']+", " ", str(text or "").lower()).strip()
    if cleaned in _CONTINUE_YES:
        return "yes"
    if cleaned in _CONTINUE_NO:
        return "no"
    return None


def classify_continue(complete, text: str) -> str | None:
    known = continue_intent(text)
    if known:
        return known
    raw = complete(
        [
            {
                "role": "system",
                "content": (
                    "The user was asked whether to keep reading a folder or to stop. "
                    "Reply with one word: YES or NO."
                ),
            },
            {"role": "user", "content": str(text or "").strip() or "(empty)"},
        ]
    )
    first = re.sub(r"[^a-z]", "", str(raw or "").lower().split(" ", 1)[0] if str(raw or "").strip() else "")
    if first == "yes":
        return "yes"
    if first == "no":
        return "no"
    return None


def _note_from_part(complete, user_text: str, part: str, prefix: str, n_ctx: int) -> str:
    piece = part
    msgs = lean_web_messages(user_text, DOC_NOTE_SYSTEM, prefix + piece)
    budget = token_budget(n_ctx)
    while messages_tokens(msgs) > budget and len(piece) > 400:
        piece = piece[: max(400, len(piece) * 3 // 4)]
        msgs = lean_web_messages(user_text, DOC_NOTE_SYSTEM, prefix + piece)
    raw = _safe_complete(complete, msgs, None)
    return raw.strip() or piece[:800]


def document_board_fits(
    chat_messages: list[dict[str, str]],
    board: list[dict],
    n_ctx: int,
    file_limit_note: str = "",
) -> tuple[list[dict[str, str]] | None, str]:
    """Return the prompt when the whole board fits. Otherwise return no messages."""
    if not board:
        return [dict(msg) for msg in chat_messages], ""
    full = format_document_board(board)
    if file_limit_note:
        full = f"{full}\n\n{file_limit_note}"
    direct = _messages_with_document_block(chat_messages, full)
    if messages_tokens(direct) <= token_budget(n_ctx):
        return direct, full
    return None, full


def split_document_board(board: list[dict], n_ctx: int, user_text: str) -> tuple[list[dict], bool]:
    """Split each file into note-sized parts. One file still stops after four parts."""
    char_budget = _blob_char_budget(n_ctx, user_text, DOC_NOTE_SYSTEM, chars_per_token=4)
    parts: list[dict] = []
    file_cut = False
    total = len(board)
    for index, doc in enumerate(board, start=1):
        card = document_card(index, total, doc)
        chunks = chunk_text(card, char_budget, max_chunks=DOC_FILE_MAX_CHUNKS) or [card]
        if sum(len(chunk) for chunk in chunks) < len(card):
            file_cut = True
        name = str(doc.get("name") or Path(str(doc.get("path") or "")).name or "document")
        for part_index, chunk in enumerate(chunks, start=1):
            parts.append(
                {
                    "name": name,
                    "index": index,
                    "total": total,
                    "part_index": part_index,
                    "part_count": len(chunks),
                    "text": chunk,
                }
            )
    return parts, file_cut


def take_document_notes(
    complete,
    status,
    stop_event,
    parts: list[dict],
    cursor: int,
    user_text: str,
    n_ctx: int,
    batch: int = DOC_BOARD_MAX_CHUNKS,
) -> tuple[list[str], int, bool]:
    """Read up to one batch of parts. Returns notes, the next cursor, and whether the user stopped."""
    notes: list[str] = []
    end = min(len(parts), max(0, cursor) + max(1, batch))
    for part in parts[cursor:end]:
        if _stopped(stop_event):
            return notes, cursor, True
        if part["part_count"] == 1:
            status(f"Notes: {part['name']} ({part['index']}/{part['total']})")
        else:
            status(
                f"Notes: {part['name']} ({part['index']}/{part['total']}), "
                f"part {part['part_index']}/{part['part_count']}"
            )
        prefix = f"Part {part['part_index']} of {part['part_count']}.\n" if part["part_count"] > 1 else ""
        notes.append(_note_from_part(complete, user_text, part["text"], prefix, n_ctx))
        cursor += 1
    return notes, cursor, False


def notes_block(
    notes: list[str],
    *,
    file_cut: bool = False,
    file_limit_note: str = "",
    stopped_early: bool = False,
) -> str:
    header = (
        "Notes taken from the attached documents one part at a time. "
        "Answer only from these notes."
    )
    if stopped_early:
        header += " The reader stopped early. These notes cover the parts read so far."
    elif file_cut or file_limit_note:
        header += " Some later text was not covered in this pass."
    if file_limit_note:
        header += " " + file_limit_note
    body = "\n\n".join(f"Note {i}:\n{note}" for i, note in enumerate(notes, start=1))
    return header + ("\n\n" + body if body else "")


def fold_notes_until_fit(
    *,
    complete,
    chat_messages: list[dict[str, str]],
    user_text: str,
    notes: list[str],
    n_ctx: int,
    stop_event,
    status,
    file_cut: bool = False,
    file_limit_note: str = "",
    stopped_early: bool = False,
) -> tuple[list[dict[str, str]], str, bool]:
    """Keep combining notes until they fit. A later round covers every piece from the round before."""
    current = [str(note).strip() for note in notes if str(note).strip()] or ["(No notes were kept.)"]
    answer_system = (
        "You are a local USB chat assistant. Answer from the attached-document notes. "
        "They are read-only. Cite the file path when you use a fact."
    )
    for _round in range(8):
        block = notes_block(
            current,
            file_cut=file_cut,
            file_limit_note=file_limit_note,
            stopped_early=stopped_early,
        )
        fitted = _messages_with_document_block(chat_messages, block)
        if messages_tokens(fitted) <= token_budget(n_ctx):
            return fitted, block, False
        if _stopped(stop_event):
            return [], "", True
        char_budget = _blob_char_budget(n_ctx, user_text, DOC_NOTE_SYSTEM, chars_per_token=4)
        pieces = chunk_text(block, char_budget, max_chunks=80) or [block]
        if len(pieces) == 1 and len(pieces[0]) > 400:
            pieces = chunk_text(block, max(400, len(block) // 2), max_chunks=80) or pieces
        reduced: list[str] = []
        for index, piece in enumerate(pieces, start=1):
            if _stopped(stop_event):
                return [], "", True
            status(f"Combining notes ({index}/{len(pieces)})")
            reduced.append(_note_from_part(complete, user_text, piece, "", n_ctx)[:1200])
        joined = "\n".join(reduced)
        if len(joined) >= len(block):
            per = max(200, char_budget // max(1, len(current)))
            shrunk = [note[:per] for note in current]
            if sum(len(note) for note in shrunk) >= sum(len(note) for note in current):
                current = reduced or shrunk
                break
            current = shrunk
            continue
        current = reduced or current
    block = notes_block(
        current,
        file_cut=file_cut,
        file_limit_note=file_limit_note,
        stopped_early=stopped_early,
    )
    fitted = _messages_with_document_block(chat_messages, block)
    if messages_tokens(fitted) <= token_budget(n_ctx):
        return fitted, block, False
    cap = _blob_char_budget(n_ctx, user_text, answer_system, chars_per_token=4)
    lean = lean_web_messages(user_text, answer_system, block[:cap])
    return lean, block[:cap], False


def fit_document_messages(
    *,
    complete,
    chat_messages: list[dict[str, str]],
    user_text: str,
    board: list[dict],
    n_ctx: int,
    stop_event,
    status,
    file_limit_note: str = "",
) -> tuple[list[dict[str, str]], str, bool]:
    """Attach a document board to the prompt. Walk every part, then fold the notes until they fit."""
    if not board:
        return [dict(msg) for msg in chat_messages], "", False
    direct, _full = document_board_fits(chat_messages, board, n_ctx, file_limit_note)
    if direct is not None:
        return direct, _full, False
    parts, file_cut = split_document_board(board, n_ctx, user_text)
    notes: list[str] = []
    cursor = 0
    while cursor < len(parts):
        batch, cursor, stopped = take_document_notes(
            complete, status, stop_event, parts, cursor, user_text, n_ctx
        )
        notes.extend(batch)
        if stopped:
            return [], "", True
    return fold_notes_until_fit(
        complete=complete,
        chat_messages=chat_messages,
        user_text=user_text,
        notes=notes,
        n_ctx=n_ctx,
        stop_event=stop_event,
        status=status,
        file_cut=file_cut,
        file_limit_note=file_limit_note,
    )


def fold_system_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Move system text into the first user message for templates that reject role=system."""
    systems: list[str] = []
    rest: list[dict[str, str]] = []
    for msg in messages:
        role = str(msg.get("role") or "user").lower()
        content = str(msg.get("content") or "")
        if role == "system":
            if content.strip():
                systems.append(content.strip())
            continue
        rest.append({"role": role if role in {"user", "assistant"} else "user", "content": content})
    if not systems:
        return rest
    prefix = "\n\n".join(systems)
    for index, msg in enumerate(rest):
        if msg.get("role") == "user":
            rest[index] = {"role": "user", "content": prefix + "\n\n" + msg.get("content", "")}
            return rest
    return [{"role": "user", "content": prefix}] + rest


def flatten_prompt(messages: list[dict[str, str]]) -> str:
    chunks: list[str] = []
    for msg in messages:
        role = msg.get("role", "user").capitalize()
        chunks.append(f"### {role}\n{msg.get('content', '')}")
    chunks.append("### Assistant\n")
    return "\n\n".join(chunks)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _read_text_file(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def extract_docx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)
    lines: list[str] = []
    for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        bits = [node.text or "" for node in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        lines.append("".join(bits))
    return unescape("\n".join(lines)).strip()


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        xml = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml)
    out: list[str] = []
    for si in root.findall("s:si", _SS_NS):
        texts = [t.text or "" for t in si.findall(".//s:t", _SS_NS)]
        out.append("".join(texts))
    return out


def extract_xlsx(path: Path) -> str:
    with zipfile.ZipFile(path) as zf:
        shared = _xlsx_shared_strings(zf)
        sheets = sorted(
            n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")
        )
        blocks: list[str] = []
        for name in sheets[:4]:
            root = ET.fromstring(zf.read(name))
            rows: list[str] = []
            for row in root.findall("s:sheetData/s:row", _SS_NS):
                cells: list[str] = []
                for cell in row.findall("s:c", _SS_NS):
                    value = cell.find("s:v", _SS_NS)
                    raw = value.text if value is not None and value.text else ""
                    if cell.attrib.get("t") == "s" and raw.isdigit() and int(raw) < len(shared):
                        cells.append(shared[int(raw)])
                    else:
                        cells.append(raw)
                if any(cells):
                    rows.append("\t".join(cells))
            if rows:
                blocks.append(f"# {Path(name).stem}\n" + "\n".join(rows))
    return "\n\n".join(blocks).strip()


def extract_pdf(path: Path, max_pages: int = 20) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = []
        limit = max(1, int(max_pages))
        for page in reader.pages[:limit]:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages).strip()
        if text:
            return text
    except Exception:
        pass
    return _pdf_strings(path.read_bytes())


def _pdf_strings(data: bytes) -> str:
    texts: list[str] = []
    for match in re.finditer(rb"\((?:\\.|[^\\)])*\)\s*Tj", data):
        raw = match.group(0)[:-2].strip()
        if raw.startswith(b"(") and raw.endswith(b")"):
            raw = raw[1:-1]
        raw = raw.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
        texts.append(raw.decode("latin-1", errors="replace"))
    return "\n".join(texts).strip()


def extract_document(path: Path, cap: int = DOC_CAP, max_pages: int = 20) -> str:
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_ATTACH:
        raise ValueError(f"unsupported type: {suffix}")
    if suffix in {".txt", ".md", ".csv"}:
        text = _read_text_file(path)
    elif suffix == ".docx":
        text = extract_docx(path)
    elif suffix == ".xlsx":
        text = extract_xlsx(path)
    else:
        text = extract_pdf(path, max_pages=max_pages)
        if not text:
            text = "(Could not extract text from this PDF.)"
    text = text.strip()
    if len(text) > cap:
        return text[:cap] + "\n…[truncated]"
    return text


def list_attach_files(folder: Path) -> tuple[list[Path], bool]:
    """Accepted documents under folder. Skips other types. Second value is True when the file cap cut the list."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        return [], False
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name.lower() not in FOLDER_SKIP_DIRS
            and not name.lower().endswith(".dist-info")
            and not name.startswith(".")
        ]
        for name in sorted(filenames):
            if name.startswith(".") or name.startswith("~$"):
                continue
            path = Path(dirpath) / name
            if path.suffix.lower() not in ALLOWED_ATTACH:
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    continue
            except OSError:
                continue
            found.append(path)
            if len(found) > FOLDER_MAX_FILES:
                return sorted(found[:FOLDER_MAX_FILES]), True
    return sorted(found), False


def _read_attach_file(path: Path) -> dict:
    item = {"name": path.name, "path": str(path.resolve()), "text": ""}
    try:
        size = path.stat().st_size
    except OSError as exc:
        item["text"] = f"(Could not read this file: {exc})"
        return item
    if size > FOLDER_MAX_FILE_BYTES:
        item["text"] = "(Skipped: file is larger than 20 MB.)"
        return item
    try:
        item["text"] = extract_document(path, cap=FOLDER_DOC_CAP, max_pages=FOLDER_DOC_PAGES)
    except Exception as exc:
        item["text"] = f"(Could not read this file: {exc})"
    return item


def read_document_board(folder: Path, on_file=None) -> tuple[list[dict], bool]:
    """Parse each accepted file before a model is loaded. Returns (documents, hit file cap)."""
    files, truncated = list_attach_files(folder)
    docs: list[dict] = []
    total = len(files)
    for index, path in enumerate(files, start=1):
        if on_file is not None:
            on_file(index, total, path.name)
        docs.append(_read_attach_file(path))
    return docs, truncated


def _pdf_escape(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _guide_ascii(text: str) -> str:
    """Fold Markdown into PDF-safe ASCII. Em-dashes before dates become ': '."""
    body = str(text or "")
    body = re.sub(r"\s*[\u2014\u2013]\s+(?=\d{4}-\d{2}-\d{2})", ": ", body)
    for src, dst in (
        ("\u2014", " - "),
        ("\u2013", "-"),
        ("\u2212", "-"),
        ("\u2018", "'"),
        ("\u2019", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\u2026", "..."),
        ("\u00d7", "x"),
        ("\u2265", ">="),
        ("\u2264", "<="),
        ("\u2192", "->"),
        ("\u00a0", " "),
        ("\u2022", "-"),
        ("\\", "/"),
    ):
        body = body.replace(src, dst)
    return "".join(ch if ord(ch) < 128 else " " for ch in body)


_GUIDE_PAGE = (612, 792)
_GUIDE_LEFT = 54
_GUIDE_RIGHT = 558
_GUIDE_TOP = 746
_GUIDE_BOTTOM = 48
_GUIDE_WIDTH = _GUIDE_RIGHT - _GUIDE_LEFT
_H1 = {"font": "F2", "size": 22, "lead": 26, "before": 0, "after": 14, "color": (0.08, 0.16, 0.36)}
_H2 = {"font": "F2", "size": 15, "lead": 20, "before": 18, "after": 8, "color": (0.10, 0.22, 0.42)}
_H3 = {"font": "F2", "size": 12.5, "lead": 17, "before": 12, "after": 6, "color": (0.12, 0.12, 0.14)}
_P = {"font": "F1", "size": 11, "lead": 15, "before": 0, "after": 8, "color": (0.16, 0.16, 0.18)}
_CODE = {"font": "F4", "size": 9, "lead": 12, "before": 6, "after": 10, "color": (0.18, 0.18, 0.20)}
_QUOTE = {"font": "F3", "size": 11, "lead": 15, "before": 4, "after": 8, "color": (0.32, 0.32, 0.34)}
_LI = {"font": "F1", "size": 11, "lead": 15, "before": 1, "after": 2, "color": (0.16, 0.16, 0.18)}
_INLINE_CODE_COLOR = (0.62, 0.13, 0.23)
_BODY_COLOR = (0.16, 0.16, 0.18)


def _guide_width(text: str, font: str, size: float) -> float:
    unit = 0.60 if font == "F4" else 0.50
    return len(text) * size * unit


def _guide_inline(text: str, size: float) -> list[tuple[str, str, float, tuple[float, float, float]]]:
    """Split Markdown inline markup into (font, text, size, rgb) runs."""
    runs: list[tuple[str, str, float, tuple[float, float, float]]] = []
    i = 0
    n = len(text)
    while i < n:
        if text.startswith("**", i):
            end = text.find("**", i + 2)
            if end >= 0:
                runs.append(("F2", text[i + 2 : end], size, _BODY_COLOR))
                i = end + 2
                continue
        if text.startswith("`", i):
            end = text.find("`", i + 1)
            if end > i:
                runs.append(("F4", text[i + 1 : end], max(9.0, size - 1), _INLINE_CODE_COLOR))
                i = end + 1
                if i < n and not text[i].isspace() and text[i] not in ",.;:!?)]":
                    runs.append(("F1", " ", size, _BODY_COLOR))
                continue
        if text.startswith("[", i):
            match = re.match(r"\[([^\]]+)\]\(([^)]+)\)", text[i:])
            if match:
                runs.append(("F2", match.group(1), size, (0.10, 0.35, 0.72)))
                runs.append(("F1", " (" + match.group(2) + ")", size, (0.40, 0.40, 0.42)))
                i += match.end()
                continue
        if text[i] == "*" and (i + 1 >= n or text[i + 1] != "*"):
            end = text.find("*", i + 1)
            if end > i:
                runs.append(("F3", text[i + 1 : end], size, _BODY_COLOR))
                i = end + 1
                continue
        nxt = n
        for tok in ("**", "`", "[", "*"):
            found = text.find(tok, i + 1)
            if found >= 0:
                nxt = min(nxt, found)
        chunk = text[i:nxt]
        if chunk:
            runs.append(("F1", chunk, size, _BODY_COLOR))
        i = nxt
    return [(f, t, s, c) for f, t, s, c in runs if t]


def _guide_pieces(text: str) -> list[str]:
    if not text:
        return []
    lead = re.match(r"^\s+", text)
    rest = text
    parts: list[str] = []
    if lead:
        parts.append(lead.group(0))
        rest = text[lead.end() :]
    parts.extend(re.findall(r"\S+\s*", rest) or ([rest] if rest else []))
    return parts


def _wrap_guide_runs(
    runs: list[tuple[str, str, float, tuple[float, float, float]]],
    max_width: float,
) -> list[list[tuple[str, str, float, tuple[float, float, float]]]]:
    lines: list[list[tuple[str, str, float, tuple[float, float, float]]]] = []
    current: list[tuple[str, str, float, tuple[float, float, float]]] = []
    width = 0.0
    for font, text, size, color in runs:
        for piece in _guide_pieces(text):
            w = _guide_width(piece, font, size)
            if current and width + w > max_width:
                lines.append(current)
                piece = piece.lstrip()
                current = [(font, piece, size, color)] if piece else []
                width = _guide_width(piece, font, size) if piece else 0.0
                continue
            current.append((font, piece, size, color))
            width += w
    if current:
        lines.append(current)
    return lines or [[]]


def _split_table_row(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def _is_table_sep(line: str) -> bool:
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(re.match(r"^:?-{3,}:?$", cell.replace(" ", "")) for cell in cells if cell)


def _is_table_row(line: str) -> bool:
    text = line.strip()
    return text.startswith("|") and text.count("|") >= 2


def _pad_table(rows: list[list[str]], max_chars: int = 100) -> list[str]:
    if not rows:
        return []
    width = max(len(row) for row in rows)
    grid = [row + [""] * (width - len(row)) for row in rows]
    caps = [max((len(grid[r][c]) for r in range(len(grid))), default=0) for c in range(width)]
    caps = [max(1, min(cap, 28)) for cap in caps]
    while sum(caps) + 3 * (width - 1) > max_chars and max(caps) > 4:
        caps[caps.index(max(caps))] -= 1

    def cell(text: str, cap: int) -> str:
        body = (text or "").replace("\n", " ")
        if len(body) > cap:
            body = body[: max(1, cap - 2)] + ".."
        return body.ljust(cap)

    lines: list[str] = []
    for i, row in enumerate(grid):
        lines.append(" | ".join(cell(row[c], caps[c]) for c in range(width)))
        if i == 0:
            lines.append("-+-".join("-" * caps[c] for c in range(width)))
    return lines


def _parse_guide_blocks(markdown: str) -> list[dict]:
    lines = _guide_ascii(markdown).replace("\r\n", "\n").split("\n")
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i].replace("\t", "    "))
                i += 1
            if i < len(lines):
                i += 1
            blocks.append({"kind": "code", "lines": body or [""], **_CODE})
            continue
        if re.match(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", line):
            blocks.append({"kind": "rule"})
            i += 1
            continue
        if _is_table_row(line):
            grid: list[list[str]] = [_split_table_row(line)]
            i += 1
            while i < len(lines) and (_is_table_row(lines[i]) or _is_table_sep(lines[i])):
                if _is_table_sep(lines[i]):
                    i += 1
                    continue
                grid.append(_split_table_row(lines[i]))
                i += 1
            blocks.append({"kind": "table", "lines": _pad_table(grid), **_CODE})
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            style = _H1 if level == 1 else _H2 if level == 2 else _H3
            blocks.append(
                {
                    "kind": "heading",
                    "runs": _guide_inline(heading.group(2).strip(), style["size"]),
                    **style,
                }
            )
            i += 1
            continue
        quote = re.match(r"^>\s?(.*)$", line)
        if quote:
            bits = [quote.group(1)]
            i += 1
            while i < len(lines):
                nxt = re.match(r"^>\s?(.*)$", lines[i])
                if not nxt:
                    break
                bits.append(nxt.group(1))
                i += 1
            blocks.append(
                {
                    "kind": "quote",
                    "runs": _guide_inline(" ".join(bits), _QUOTE["size"]),
                    **_QUOTE,
                }
            )
            continue
        ul = re.match(r"^[-*+]\s+(.*)$", line)
        ol = re.match(r"^(\d+)\.\s+(.*)$", line)
        if ul or ol:
            ordered = ol is not None
            while i < len(lines):
                m_ol = re.match(r"^(\d+)\.\s+(.*)$", lines[i])
                m_ul = re.match(r"^[-*+]\s+(.*)$", lines[i])
                if ordered and m_ol:
                    marker = m_ol.group(1) + ". "
                    item_body = m_ol.group(2)
                elif not ordered and m_ul:
                    marker = "-  "
                    item_body = m_ul.group(1)
                else:
                    break
                blocks.append(
                    {
                        "kind": "li",
                        "runs": [("F2", marker, _LI["size"], _BODY_COLOR)]
                        + _guide_inline(item_body, _LI["size"]),
                        **_LI,
                    }
                )
                i += 1
            blocks.append({"kind": "gap", "after": 6})
            continue
        if not line.strip():
            i += 1
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip():
            if (
                lines[i].startswith("#")
                or lines[i].strip().startswith("```")
                or re.match(r"^[-*+]\s+", lines[i])
                or re.match(r"^\d+\.\s+", lines[i])
                or re.match(r"^>\s?", lines[i])
                or re.match(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", lines[i])
                or _is_table_row(lines[i])
            ):
                break
            para.append(lines[i])
            i += 1
        blocks.append(
            {
                "kind": "p",
                "runs": _guide_inline(" ".join(p.strip() for p in para), _P["size"]),
                **_P,
            }
        )
    return blocks


def _guide_line_ops(
    runs: list[tuple[str, str, float, tuple[float, float, float]]],
    x: float,
    y: float,
) -> list[str]:
    ops = ["BT", f"1 0 0 1 {x:.1f} {y:.1f} Tm"]
    last_font = ""
    last_size = 0.0
    last_color = None
    for font, text, size, color in runs:
        if last_color != color:
            ops.append(f"{color[0]:.2f} {color[1]:.2f} {color[2]:.2f} rg")
            last_color = color
        if font != last_font or size != last_size:
            ops.append(f"/{font} {size:g} Tf")
            last_font = font
            last_size = size
        ops.append(f"({_pdf_escape(text)}) Tj")
    ops.append("ET")
    return ops


def build_guide_pdf(title: str, markdown: str) -> bytes:
    """Markdown-ish guide PDF: headings, bold, code, lists. Not the transcript dump."""
    del title
    blocks = _parse_guide_blocks(markdown)
    page_w, page_h = _GUIDE_PAGE
    pages: list[list[str]] = []
    ops: list[str] = []
    y = _GUIDE_TOP
    first_on_page = True

    def flush_page() -> None:
        nonlocal ops, y, first_on_page
        pages.append(ops)
        ops = []
        y = _GUIDE_TOP
        first_on_page = True

    def need(space: float) -> None:
        if y - space < _GUIDE_BOTTOM:
            flush_page()

    for block in blocks:
        kind = block["kind"]
        if kind == "gap":
            y -= float(block.get("after") or 0)
            continue
        if kind == "rule":
            need(16)
            y -= 8
            ops.extend(
                [
                    "q",
                    "0.75 0.78 0.82 RG",
                    "0.8 w",
                    f"{_GUIDE_LEFT:.1f} {y:.1f} m {_GUIDE_RIGHT:.1f} {y:.1f} l S",
                    "Q",
                ]
            )
            y -= 10
            first_on_page = False
            continue
        if kind == "code" or kind == "table":
            code_lines = list(block["lines"])
            lead = float(block["lead"])
            y -= 4
            for raw in code_lines:
                need(lead + 4)
                fill = "0.96 0.96 0.97 rg" if kind == "code" else "0.93 0.95 0.98 rg"
                ops.extend(
                    [
                        "q",
                        fill,
                        f"{_GUIDE_LEFT:.1f} {y - 3:.1f} {_GUIDE_WIDTH:.1f} {lead + 2:.1f} re f",
                        "Q",
                    ]
                )
                ops.extend(
                    _guide_line_ops(
                        [("F4", raw if raw else " ", 8 if kind == "table" else 9, block["color"])],
                        _GUIDE_LEFT + 8,
                        y,
                    )
                )
                y -= lead
            y -= float(block["after"])
            first_on_page = False
            continue
        indent = 22 if kind in {"li", "quote"} else 0
        max_w = _GUIDE_WIDTH - indent - (10 if kind == "quote" else 0)
        runs = list(block.get("runs") or [])
        if kind == "heading":
            runs = [(block["font"], text, block["size"], block["color"]) for _f, text, _s, _c in runs]
        wrapped = _wrap_guide_runs(runs, max_w)
        before = 0.0 if first_on_page else float(block.get("before") or 0)
        need(before + float(block["lead"]) * max(1, len(wrapped)) + 4)
        y -= before
        if kind == "quote":
            bar_top = y + 2
            bar_bot = y - float(block["lead"]) * max(1, len(wrapped)) - 2
            ops.extend(
                [
                    "q",
                    "0.75 0.80 0.88 rg",
                    f"{_GUIDE_LEFT:.1f} {bar_bot:.1f} 3 {bar_top - bar_bot:.1f} re f",
                    "Q",
                ]
            )
        for line in wrapped:
            need(float(block["lead"]))
            ops.extend(_guide_line_ops(line, _GUIDE_LEFT + indent, y))
            y -= float(block["lead"])
        y -= float(block.get("after") or 0)
        first_on_page = False
    if ops:
        pages.append(ops)
    if not pages:
        pages = [_guide_line_ops([("F1", "USB chat", 12, _BODY_COLOR)], _GUIDE_LEFT, _GUIDE_TOP)]

    objects: list[bytes] = [b""]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>")
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")
    font_res = "/F1 3 0 R /F2 4 0 R /F3 5 0 R /F4 6 0 R"
    page_ids: list[int] = []
    for page_ops in pages:
        stream = "\n".join(page_ops).encode("latin-1", "replace")
        page_id = len(objects)
        page_ids.append(page_id)
        objects.append(b"")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Contents {page_id + 1} 0 R /Resources << /Font << {font_res} >> >> >>"
        ).encode("ascii")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for i, obj in enumerate(objects):
        if i == 0:
            continue
        offsets.append(sum(len(c) for c in chunks))
        chunks.append(f"{i} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref_at = sum(len(c) for c in chunks)
    xref = [f"xref\n0 {len(objects)}\n", "0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n")
    chunks.append("".join(xref).encode("ascii"))
    chunks.append(
        (
            f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    return b"".join(chunks)


def _wrap_pdf_line(text: str, width: int = 92) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw:
            lines.append("")
            continue
        while len(raw) > width:
            cut = raw.rfind(" ", 0, width)
            if cut < 20:
                cut = width
            lines.append(raw[:cut])
            raw = raw[cut:].lstrip()
        lines.append(raw)
    return lines


def build_transcript_pdf(title: str, blocks: list[tuple[str, str]]) -> bytes:
    wrapped: list[str] = [title, ""]
    for role, body in blocks:
        wrapped.append(f"[{role}]")
        wrapped.extend(_wrap_pdf_line(body))
        wrapped.append("")
    if not wrapped[-1]:
        wrapped.pop()

    page_h = 792
    page_w = 612
    top = 738
    bottom = 54
    leading = 13
    lines_per_page = max(1, (top - bottom) // leading)
    pages: list[list[str]] = []
    for i in range(0, len(wrapped), lines_per_page):
        pages.append(wrapped[i : i + lines_per_page])
    if not pages:
        pages = [[title]]

    objects: list[bytes] = [b""]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{4 + i * 2} 0 R" for i in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("ascii"))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_lines in pages:
        cmds = ["BT", "/F1 11 Tf", f"54 {top} Td"]
        for i, line in enumerate(page_lines):
            if i:
                cmds.append(f"0 -{leading} Td")
            cmds.append(f"({_pdf_escape(line)}) Tj")
        cmds.append("ET")
        stream = "\n".join(cmds).encode("latin-1", "replace")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Contents {len(objects) + 1} 0 R /Resources << /Font << /F1 3 0 R >> >> >>".encode(
                "ascii"
            )
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream")

    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for i, obj in enumerate(objects):
        if i == 0:
            continue
        offsets.append(sum(len(c) for c in chunks))
        chunks.append(f"{i} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref_at = sum(len(c) for c in chunks)
    xref = [f"xref\n0 {len(objects)}\n", "0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n")
    chunks.append("".join(xref).encode("ascii"))
    chunks.append(
        (
            f"trailer\n<< /Size {len(objects)} /Root 1 0 R >>\n"
            f"startxref\n{xref_at}\n%%EOF\n"
        ).encode("ascii")
    )
    return b"".join(chunks)


def print_or_open_pdf(data: bytes) -> Path:
    handle = tempfile.NamedTemporaryFile(prefix="usb-chat-", suffix=".pdf", delete=False)
    handle.write(data)
    handle.close()
    path = Path(handle.name)
    if sys.platform == "win32":
        os.startfile(path, "print")  # type: ignore[attr-defined]
    elif shutil.which("lpr"):
        subprocess.Popen(["lpr", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        opener = shutil.which("xdg-open") or shutil.which("open")
        if opener:
            subprocess.Popen([opener, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            raise RuntimeError("no print command")
    return path


def find_llama_cli(here: Path | None = None) -> Path | None:
    here = (here or Path(__file__).resolve().parent).resolve()
    names = ["llama-cli.exe", "llama-cli"]
    search = [
        here / "bin",
        here / "win64",
        here / "linux-x64",
        here.parent / "win64",
        here.parent / "linux-x64",
        here.parent / "bin",
    ]
    for folder in search:
        for name in names:
            cand = folder / name
            if cand.is_file():
                return cand
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def gpu_layers() -> int:
    raw = os.environ.get("USB_CHAT_N_GPU_LAYERS") or os.environ.get("N_GPU_LAYERS") or "0"
    raw = raw.strip().lower()
    if raw in {"auto", ""}:
        return 0
    try:
        return int(raw)
    except ValueError:
        return 0


class LlamaCppEngine:
    def __init__(self, model_path: Path, n_ctx: int = N_CTX_DEFAULT, n_gpu_layers: int | None = None):
        from llama_cpp import Llama  # type: ignore

        self.model_path = model_path
        self.n_ctx = n_ctx
        self.llm = Llama(
            model_path=str(model_path),
            n_ctx=n_ctx,
            n_gpu_layers=gpu_layers() if n_gpu_layers is None else n_gpu_layers,
            verbose=False,
        )
        self.last_usage = (0, 0)
        self._no_system_role = False

    def stream(self, messages: list[dict[str, str]], stop_event, max_tokens: int | None = None):
        payload = fold_system_messages(messages) if self._no_system_role else messages
        n_pred = max(16, int(max_tokens or MAX_TOKENS_DEFAULT))
        try:
            chunks = self.llm.create_chat_completion(
                payload,
                stream=True,
                max_tokens=n_pred,
            )
        except Exception as exc:
            if self._no_system_role or "system role not supported" not in str(exc).lower():
                raise
            self._no_system_role = True
            payload = fold_system_messages(messages)
            chunks = self.llm.create_chat_completion(
                payload,
                stream=True,
                max_tokens=n_pred,
            )
        text: list[str] = []
        prompt_tokens = 0
        completion_tokens = 0
        for chunk in chunks:
            if stop_event is not None and stop_event.is_set():
                break
            choice = chunk.get("choices") or [{}]
            delta = (choice[0].get("delta") or {}).get("content") or ""
            if delta:
                text.append(delta)
                yield delta
            usage = chunk.get("usage") or {}
            if usage:
                prompt_tokens = int(usage.get("prompt_tokens") or 0)
                completion_tokens = int(usage.get("completion_tokens") or 0)
        if not prompt_tokens:
            prompt_tokens = estimate_tokens(flatten_prompt(messages))
        if not completion_tokens:
            completion_tokens = estimate_tokens("".join(text))
        self.last_usage = (prompt_tokens, completion_tokens)


class LlamaCliEngine:
    def __init__(self, cli: Path, model_path: Path, n_ctx: int = N_CTX_DEFAULT):
        self.cli = cli
        self.model_path = model_path
        self.n_ctx = n_ctx
        self.last_usage = (0, 0)
        self._proc: subprocess.Popen[str] | None = None

    def stream(self, messages: list[dict[str, str]], stop_event, max_tokens: int | None = None):
        prompt = flatten_prompt(messages)
        n_pred = max(16, int(max_tokens or MAX_TOKENS_DEFAULT))
        cmd = [
            str(self.cli),
            "-m",
            str(self.model_path),
            "-n",
            str(n_pred),
            "-c",
            str(self.n_ctx),
            "--simple-io",
            "-no-cnv",
            "-p",
            prompt,
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        text: list[str] = []
        assert self._proc.stdout is not None
        try:
            while True:
                if stop_event is not None and stop_event.is_set():
                    self._proc.kill()
                    break
                piece = self._proc.stdout.read(32)
                if not piece:
                    break
                text.append(piece)
                yield piece
        finally:
            if self._proc.poll() is None:
                self._proc.kill()
            self._proc = None
        joined = "".join(text)
        self.last_usage = (estimate_tokens(prompt), estimate_tokens(joined))


def make_engine(model_path: Path, n_ctx: int = N_CTX_DEFAULT, here: Path | None = None):
    try:
        import llama_cpp  # noqa: F401

        return LlamaCppEngine(model_path, n_ctx=n_ctx)
    except ImportError:
        pass
    cli = find_llama_cli(here)
    if cli is None:
        raise RuntimeError(
            "Need llama-cpp-python on this machine, or llama-cli in scripts/bin/."
        )
    return LlamaCliEngine(cli, model_path, n_ctx=n_ctx)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
