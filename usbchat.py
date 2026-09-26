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
WEB_MAX_URLS = 3
WEB_HTML_CAP = 12_000
WEB_PAGE_CAP = 8_000
WEB_HTML_TOTAL_CAP = 80_000
WEB_MAX_CHUNKS = 8
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
ATTACH_ICON = "📄"
_ATTACH_MARK = re.compile(r"\[attached ([^\]]+)\]")


@dataclass(frozen=True)
class ModelChoice:
    path: Path
    label: str
    size: int
    required_ram: int


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


def pickable_models(root: Path, free: int | None) -> list[ModelChoice]:
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
            )
        )
    choices.sort(key=lambda c: c.size, reverse=True)
    return choices


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


def usb_root(models_root: Path, here: Path | None = None) -> Path:
    here = (here or Path(__file__).resolve().parent).resolve()
    if not discover_ggufs(models_root):
        return here
    if models_root.name.lower() == "models":
        return here
    return models_root


def notes_path(root: Path) -> Path:
    return root / "notes.md"


def logs_dir(root: Path) -> Path:
    return root / "logs"


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


def attach_label(path_or_name: str) -> str:
    return f"{ATTACH_ICON} {path_or_name}"


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


def chunk_text(text: str, max_chars: int) -> list[str]:
    text = text or ""
    if not text:
        return []
    limit = max(400, int(max_chars))
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + limit, len(text))
        if end < len(text):
            cut = text.rfind("\n", start + limit // 2, end)
            if cut > start:
                end = cut + 1
        chunks.append(text[start:end])
        start = end
        if len(chunks) >= WEB_MAX_CHUNKS:
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


def extract_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages[:20]:
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


def extract_document(path: Path, cap: int = DOC_CAP) -> str:
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
        text = extract_pdf(path)
        if not text:
            text = "(Could not extract text from this PDF.)"
    text = text.strip()
    if len(text) > cap:
        return text[:cap] + "\n…[truncated]"
    return text


def _pdf_escape(text: str) -> str:
    safe = text.encode("latin-1", "replace").decode("latin-1")
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


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

    def stream(self, messages: list[dict[str, str]], stop_event):
        payload = fold_system_messages(messages) if self._no_system_role else messages
        try:
            chunks = self.llm.create_chat_completion(
                payload,
                stream=True,
                max_tokens=MAX_TOKENS_DEFAULT,
            )
        except Exception as exc:
            if self._no_system_role or "system role not supported" not in str(exc).lower():
                raise
            self._no_system_role = True
            payload = fold_system_messages(messages)
            chunks = self.llm.create_chat_completion(
                payload,
                stream=True,
                max_tokens=MAX_TOKENS_DEFAULT,
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

    def stream(self, messages: list[dict[str, str]], stop_event):
        prompt = flatten_prompt(messages)
        cmd = [
            str(self.cli),
            "-m",
            str(self.model_path),
            "-n",
            str(MAX_TOKENS_DEFAULT),
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
            "Need llama-cpp-python on this machine, or llama-cli in chat/bin/."
        )
    return LlamaCliEngine(cli, model_path, n_ctx=n_ctx)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
