"""Loopback chat UI. Agents never import this file."""

from __future__ import annotations

import argparse
import email
import html
import json
import re
import threading
from email.policy import default as email_default
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import blackboard
import career
import config
import executor
import formatter
import logger
import main
import profile
import router
import search

HOST = "127.0.0.1"
PORT = 8765
UI_FILE = config.REPO_ROOT / "ui" / "index.html"
PROFILE_FILE = config.REPO_ROOT / "ui" / "profile.html"
_DOWNLOAD_NAME = re.compile(
    r"^[A-Za-z0-9._-]+\.(pdf|md|markdown|html|txt|py|csv|json|js|css)$",
    re.I,
)
NO_MODEL = False
KEEP_SUMMARY_FILE = "SUMMARY.md"
_KEEP_DIR_OK = re.compile(r"^[A-Za-z0-9._-]+$")
_KEEP_PDF = re.compile(r"^[A-Za-z0-9._-]+\.pdf$", re.I)
_BUSY = threading.Lock()
_SESSION_LOCK = threading.Lock()
_ACTIVE: dict[str, Any] | None = None
_DEVICE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)

SKIP_TOOLS = {
    "sendMessageToBlackboard",
    "viewBlackboardMessages",
    "viewSessionDetails",
    "createThread",
    "startThread",
    "endThread",
    "deleteThread",
    "createLog",
    "checkLogExists",
    "createAgent",
    "deleteAgent",
    "setBlackBoardRules",
    "createBlackBoard",
    "viewBlackBoard",
    "setSessionDetails",
}

TOOL_PHRASES = {
    "read_file": "Reading",
    "search_dir": "Searching",
    "write_doc": "Writing",
    "write_file": "Writing",
    "write_pdf": "Writing PDF",
    "write_json": "Writing JSON",
    "append_file": "Appending",
    "mkdir": "Making folder",
    "get_url": "Fetching",
    "search_web": "Searching",
    "post_url": "Posting to",
    "sandbox_read": "Reading sandbox",
    "sandbox_write": "Writing sandbox",
    "executeScriptInSandbox": "Running sandbox script",
    "getResultsFromSandbox": "Reading sandbox results",
    "sandbox_fetch": "Checking sandbox app",
    "openSandbox": "Opening sandbox",
    "createSandbox": "Creating sandbox",
    "deleteSandbox": "Removing sandbox",
    "createKeepDir": "Creating keep folder",
    "updateBoard": "Updating board",
    "viewCommitteeBoard": "Reading board",
    "viewSourceBoard": "Reading source board",
    "callVote": "Opening vote",
    "git_login": "Git login",
    "git_commit": "Git commit",
    "git_push": "Git push",
    "committeeTurn": "Committee",
    "listMails": "Listing mail",
    "openMail": "Opening mail",
    "sendMail": "Sending mail",
    "searchMails": "Searching mail",
    "replyMail": "Replying to mail",
    "mapRoute": "Routing",
}


def parse_device_id(raw: Any) -> str | None:
    text = str(raw or "").strip()
    if not _DEVICE_RE.fullmatch(text):
        return None
    return text.lower()


def device_dir(device_id: str) -> Path | None:
    did = parse_device_id(device_id)
    if not did:
        return None
    root = config.UI_SESSION_DIR.resolve()
    target = (root / did).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    return target


def rotate_ui_session() -> None:
    """Ensure the UI session root exists. Per-device tapes survive process start."""
    config.UI_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    (config.UI_SESSION_DIR / "active.json").unlink(missing_ok=True)


def read_history(device_id: str) -> list[dict[str, Any]]:
    folder = device_dir(device_id)
    if folder is None:
        return []
    path = folder / "session.jsonl"
    if not path.is_file():
        return []
    turns: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            blob = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(blob, dict):
            turns.append(blob)
    return turns


def decorate_turn(turn: dict[str, Any], device_id: str | None = None) -> dict[str, Any]:
    """Format at display time. Session tape keeps the raw answer."""
    blob = dict(turn)
    formatted = formatter.format_answer(str(blob.get("answer") or ""))
    run_id = str(blob.get("run_id") or blob.get("id") or "none")
    blob["answer_html"] = formatted["html"]
    blob["html_pages"] = formatter.save_pages(run_id, formatted["pages"], device_id=device_id)
    return blob


def read_active(device_id: str | None = None) -> dict[str, Any] | None:
    if _ACTIVE is None:
        return None
    if device_id and str(_ACTIVE.get("device") or "") != device_id:
        return None
    return dict(_ACTIVE)


def set_active(
    prompt: str,
    thread_id: str | None,
    progress: str = "Working…",
    *,
    device_id: str,
    started: str,
    attachments: list[dict[str, Any]] | None = None,
) -> None:
    global _ACTIVE
    _ACTIVE = {
        "prompt": prompt,
        "thread_id": thread_id,
        "progress": progress,
        "device": device_id,
        "started": started,
        "attachments": list(attachments or []),
    }
    _write_active()


def update_active_progress(text: str) -> None:
    if _ACTIVE is None:
        return
    _ACTIVE["progress"] = text
    _write_active()


def clear_active() -> None:
    global _ACTIVE
    device = None if _ACTIVE is None else str(_ACTIVE.get("device") or "")
    _ACTIVE = None
    if device:
        folder = device_dir(device)
        if folder is not None:
            (folder / "active.json").unlink(missing_ok=True)
            return
    (config.UI_SESSION_DIR / "active.json").unlink(missing_ok=True)


def _write_active() -> None:
    if _ACTIVE is None:
        return
    folder = device_dir(str(_ACTIVE.get("device") or ""))
    if folder is None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "active.json"
    with _SESSION_LOCK:
        path.write_text(json.dumps(_ACTIVE, ensure_ascii=False), encoding="utf-8")


def append_turn(turn: dict[str, Any], device_id: str) -> None:
    folder = device_dir(device_id)
    if folder is None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "session.jsonl"
    row = dict(turn)
    row.setdefault("device", device_id)
    with _SESSION_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def log_device_meta(
    device_id: str,
    *,
    ip: str,
    user_agent: str,
    language: str,
    path: str,
) -> None:
    """Sidecar for later analytics. Never used to look up a session."""
    folder = device_dir(device_id)
    if folder is None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    row = {
        "time": datetime.now(timezone.utc).isoformat(),
        "device": device_id,
        "ip": str(ip or "")[:80],
        "user_agent": str(user_agent or "")[:400],
        "language": str(language or "")[:32],
        "path": str(path or "")[:80],
    }
    with _SESSION_LOCK:
        with (folder / "meta.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def resolve_keep_summary(dir_name: str | None, file_name: str | None) -> Path | None:
    """Map /keep query args to SUMMARY.md or a PDF under outputs/."""
    return resolve_output_file(dir_name, file_name)


def resolve_output_file(dir_name: str | None, file_name: str | None) -> Path | None:
    folder = unquote(str(dir_name or "")).strip().replace("\\", "/")
    name = unquote(str(file_name or "")).strip()
    parts = [p for p in folder.split("/") if p]
    if not parts or any(p in {".", ".."} for p in parts) or not all(_KEEP_DIR_OK.fullmatch(p) for p in parts):
        return None
    if name != KEEP_SUMMARY_FILE and not _KEEP_PDF.fullmatch(name):
        return None
    root = config.OUTPUTS.resolve()
    target = root.joinpath(*parts, name).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def resolve_download(dir_name: str | None, file_name: str | None) -> Path | None:
    folder = unquote(str(dir_name or "")).strip().replace("\\", "/")
    name = unquote(str(file_name or "")).strip()
    parts = [p for p in folder.split("/") if p]
    if not parts or any(p in {".", ".."} for p in parts) or not all(_KEEP_DIR_OK.fullmatch(p) for p in parts):
        return None
    if not _DOWNLOAD_NAME.fullmatch(name):
        return None
    root = config.OUTPUTS.resolve()
    target = root.joinpath(*parts, name).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def _preview_page(title: str, inner: str) -> bytes:
    page = (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        "<style>"
        "body{margin:0 auto;max-width:820px;padding:24px 16px 48px;background:#141414;color:#ececec;"
        "font:15px/1.5 system-ui,Segoe UI,sans-serif}"
        "a{color:#c8a45a} pre{background:#111;border:1px solid #2e2e2e;padding:12px;overflow:auto;"
        "white-space:pre-wrap} code{font-family:ui-monospace,Consolas,monospace}"
        "h1,h2,h3{font-weight:600} blockquote{border-left:3px solid #c8a45a;margin-left:0;padding-left:10px;color:#9a9a9a}"
        "</style></head><body>"
        f"<p><a href=\"/\">Back to chat</a></p>"
        f"{inner}</body></html>"
    )
    return page.encode("utf-8")


def find_turn(run_id: str, device_id: str) -> dict[str, Any] | None:
    rid = str(run_id or "").strip()
    if not rid:
        return None
    for turn in reversed(read_history(device_id)):
        if str(turn.get("run_id") or turn.get("id") or "") == rid:
            return turn
    return None


def progress_line(record: dict[str, Any]) -> str | None:
    """One operator sentence from an audit record. Never a transcript."""
    event = record.get("event")
    if event == "spawn":
        role = str(record.get("role") or "agent").replace("_", " ")
        return f"Started {role}"
    tool = str(record.get("tool") or "")
    if not tool or tool in SKIP_TOOLS:
        return None
    status = record.get("status")
    detail = _summary_detail(str(record.get("summary") or ""))
    if tool == "committeeTurn":
        role = detail or "agent"
        stage = _stage_detail(str(record.get("summary") or ""))
        return f"Committee {role}" + (f" ({stage})" if stage else "")
    verb = TOOL_PHRASES.get(tool)
    if event == "route" or tool == "mapRoute":
        return f"Routed as {detail}" if detail else "Routed"
    if status == "fail":
        base = verb or tool
        return f"{base} failed" + (f" ({detail})" if detail else "")
    if verb:
        return f"{verb} {detail}".strip() if detail else verb
    return None


def _summary_detail(summary: str) -> str:
    for key in ("path", "host", "name", "directory", "role"):
        match = re.search(rf"{key}=([^\s]+)", summary)
        if not match:
            continue
        value = match.group(1).strip().strip("'\"")
        if key == "host":
            return value
        return Path(value).name if key in {"path", "directory"} else value
    match = re.search(r"level=(\w+)", summary)
    if match:
        return match.group(1)
    return ""


def _stage_detail(summary: str) -> str:
    match = re.search(r"stage=([^\s]+)", summary)
    return match.group(1) if match else ""


def google_account_ready() -> bool:
    import google_backend

    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET and google_backend.HAS_GOOGLE)


def source_documents(name: str, kind: str, body: str) -> list[dict[str, str]]:
    """Split extracted upload text into board entries. The text stays out of the user prompt."""
    text = str(body or "").strip()
    if not text:
        return []
    label = str(name or kind or "document").strip() or "document"
    if kind == "file":
        return [{"name": label, "kind": "file", "text": text}]
    docs: list[dict[str, str]] = []
    for part in re.split(r"\n(?=## )", text):
        part = part.strip()
        if not part:
            continue
        if part.startswith("## "):
            title, _, rest = part.partition("\n")
            title = title[3:].strip() or label
            docs.append({"name": title, "kind": kind, "text": rest.strip() or part})
        else:
            docs.append({"name": label, "kind": kind, "text": part})
    return docs or [{"name": label, "kind": kind, "text": text}]


def _applicant_line(device_id: str) -> str:
    """Name and place from the saved profile. Job history stays out of the report notes."""
    try:
        contact = (career.read_resume(device_id) or {}).get("contact") or {}
    except (OSError, ValueError):
        return ""
    if not isinstance(contact, dict):
        return ""
    name = str(contact.get("name") or "").strip()
    location = str(contact.get("location") or "").strip()
    return ", ".join(bit for bit in (name, location) if bit)


def run_turn(
    prompt: str,
    thread_id: str | None,
    *,
    coding: Any = False,
    git_remote: str | None = None,
    web: Any = False,
    gmail: Any = False,
    calendar: Any = False,
    sources: list[dict[str, str]] | None = None,
    applicant: str = "",
) -> dict[str, Any]:
    fields = main._route_fields(prompt, NO_MODEL)
    fields = router.apply_user_controls(
        fields,
        coding=coding,
        git_remote=git_remote,
        web=web,
        gmail=gmail,
        calendar=calendar,
    )
    generate_fn = main.stub_generate if NO_MODEL else None
    return executor.run_session(
        prompt,
        fields,
        generate_fn=generate_fn,
        thread_id=thread_id,
        sources=sources,
        applicant=applicant,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "id10t-ui"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _client_ip(self) -> str:
        if not self.client_address:
            return ""
        return str(self.client_address[0] or "")

    def _note_device(self, device_id: str, *, user_agent: str = "", language: str = "") -> None:
        ua = str(user_agent or "").strip() or (self.headers.get("User-Agent") or "")
        lang = str(language or "").strip() or (self.headers.get("Accept-Language") or "").split(",")[0]
        log_device_meta(
            device_id,
            ip=self._client_ip(),
            user_agent=ua,
            language=lang,
            path=urlparse(self.path).path,
        )

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        qs = parse_qs(urlparse(self.path).query)
        if path == "/":
            self._send_index()
            return
        if path == "/threads":
            self._send_json(200, {"ok": True, "threads": blackboard.list_threads()})
            return
        if path == "/history":
            device = parse_device_id((qs.get("device") or [""])[0])
            if not device:
                self._send_json(400, {"ok": False, "error": "missing_device"})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "turns": [decorate_turn(t, device) for t in read_history(device)],
                    "active": read_active(device),
                },
            )
            return
        if path == "/keep":
            self._send_keep()
            return
        if path == "/html":
            self._send_html()
            return
        if path == "/profile":
            self._send_ui(PROFILE_FILE)
            return
        if path == "/read-profile":
            device = parse_device_id((qs.get("device") or [""])[0])
            if not device:
                self._send_json(400, {"ok": False, "error": "missing_device"})
                return
            self._send_json(200, {"ok": True, "profile": career.read_resume(device)})
            return
        if path == "/board":
            device = parse_device_id((qs.get("device") or [""])[0])
            if not device:
                self._send_json(400, {"ok": False, "error": "missing_device"})
                return
            self._note_device(device, language=(qs.get("language") or [""])[0])
            board = profile.public_board()
            self._send_json(200, {"ok": True, **board})
            return
        if path == "/download":
            self._send_download()
            return
        if path == "/web-status":
            self._send_json(200, search.status())
            return
        if path == "/google-status":
            ready = google_account_ready()
            self._send_json(200, {"available": ready, "reason": "" if ready else "not_configured"})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/profile":
            self._save_profile()
            return
        if path == "/update-profile":
            self._update_resume()
            return
        if path == "/upload-folder":
            self._upload(kind="folder")
            return
        if path == "/upload-file":
            self._upload(kind="file")
            return
        if path != "/turns":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"ok": False, "error": "bad_length"})
            return
        raw = self.rfile.read(max(length, 0)) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "bad_json"})
            return
        device = parse_device_id((body or {}).get("device"))
        if not device:
            self._send_json(400, {"ok": False, "error": "missing_device"})
            return
        prompt = str((body or {}).get("prompt") or "").strip()
        wanted = str((body or {}).get("thread_id") or "").strip() or None
        coding = bool((body or {}).get("coding"))
        job = bool((body or {}).get("job"))
        update_profile = bool((body or {}).get("update_profile"))
        web = (body or {}).get("web")
        account = google_account_ready() and not job and not update_profile
        gmail = bool((body or {}).get("gmail")) and account
        calendar = bool((body or {}).get("calendar")) and account
        git_remote = str((body or {}).get("git_remote") or "").strip() or None
        seed_id = str((body or {}).get("seed_id") or "").strip()
        folder_id = str((body or {}).get("folder_id") or "").strip()
        file_id = str((body or {}).get("file_id") or "").strip()
        user_agent = str((body or {}).get("user_agent") or "")
        language = str((body or {}).get("language") or "")
        if update_profile and not file_id:
            self._send_json(400, {"ok": False, "error": "resume_required"})
            return
        if not prompt and not update_profile:
            self._send_json(400, {"ok": False, "error": "empty_prompt"})
            return
        if job and coding:
            self._send_json(400, {"ok": False, "error": "job_and_coding"})
            return
        if job and update_profile:
            self._send_json(400, {"ok": False, "error": "job_and_update"})
            return
        if coding and git_remote and seed_id:
            self._send_json(400, {"ok": False, "error": "git_and_folder"})
            return
        if job and career.profile_is_empty(device):
            self._send_json(400, {"ok": False, "error": "empty_profile"})
            return
        document_text = ""
        seed_listing = ""
        file_row = career.get_upload(file_id) if file_id else None
        folder_row = career.get_upload(folder_id) if folder_id and not job and not update_profile else None
        seed_row = career.get_upload(seed_id) if seed_id and coding else None
        if file_id and file_row is None:
            self._send_json(400, {"ok": False, "error": "unknown_upload"})
            return
        if folder_id and not job and not update_profile and folder_row is None:
            self._send_json(400, {"ok": False, "error": "unknown_upload"})
            return
        if seed_id and coding and seed_row is None:
            self._send_json(400, {"ok": False, "error": "unknown_upload"})
            return
        if file_row:
            document_text = file_row["body"]
        if seed_row:
            seed_listing = seed_row["listing"]
        sources: list[dict[str, str]] = []
        if file_row and not update_profile and not job:
            sources.extend(source_documents(str(file_row.get("name") or "file"), "file", str(file_row.get("body") or "")))
        if folder_row:
            sources.extend(source_documents(str(folder_row.get("name") or "folder"), "folder", str(folder_row.get("body") or "")))
        if seed_row:
            sources.extend(source_documents(str(seed_row.get("name") or "project"), "project", str(seed_row.get("body") or "")))
        attachments: list[dict[str, Any]] = []
        if file_row and not job:
            attachments.append(file_row)
        if folder_row:
            attachments.append(folder_row)
        if seed_row:
            attachments.append(seed_row)
        if not _BUSY.acquire(blocking=False):
            self._send_json(409, {"ok": False, "error": "busy"})
            return
        try:
            self._stream_turn(
                prompt,
                wanted,
                coding=coding,
                git_remote=git_remote,
                web=web and not job and not update_profile,
                gmail=gmail,
                calendar=calendar,
                device_id=device,
                user_agent=user_agent,
                language=language,
                job=job,
                update_profile=update_profile,
                document_text=document_text,
                seed_listing=seed_listing,
                attachments=attachments,
                sources=sources,
            )
        finally:
            _BUSY.release()

    def _stream_turn(
        self,
        prompt: str,
        thread_id: str | None,
        *,
        coding: Any = False,
        git_remote: str | None = None,
        web: Any = False,
        gmail: Any = False,
        calendar: Any = False,
        device_id: str,
        user_agent: str = "",
        language: str = "",
        job: bool = False,
        update_profile: bool = False,
        document_text: str = "",
        seed_listing: str = "",
        attachments: list[dict[str, Any]] | None = None,
        sources: list[dict[str, str]] | None = None,
    ) -> None:
        shown = prompt
        saved_attachments = [
            {
                "kind": "file" if row.get("kind") == "file" else "folder",
                "name": row.get("name") or "",
                "entries": list(row.get("entries") or []),
                "truncated": bool(row.get("truncated")),
            }
            for row in (attachments or [])
        ]
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        started = datetime.now(timezone.utc)
        set_active(
            shown,
            thread_id,
            "Working…",
            device_id=device_id,
            started=started.isoformat(),
            attachments=saved_attachments,
        )
        self._note_device(device_id, user_agent=user_agent, language=language)
        self._sse("progress", {"text": "Working…"})

        def on_log(record: dict[str, Any]) -> None:
            line = progress_line(record)
            if line:
                update_active_progress(line)
                self._sse("progress", {"text": line})

        def status(text: str) -> None:
            update_active_progress(text)
            self._sse("progress", {"text": text})

        logger.add_listener(on_log)
        try:
            try:
                if job:
                    result = career.run_job(prompt, status, device_id=device_id, no_model=NO_MODEL)
                elif update_profile:
                    result = career.run_update(document_text, prompt, status, device_id=device_id, no_model=NO_MODEL)
                else:
                    result = run_turn(
                        prompt,
                        thread_id,
                        coding=coding,
                        git_remote=None if seed_listing else git_remote,
                        web=web,
                        gmail=gmail,
                        calendar=calendar,
                        sources=sources,
                        applicant=_applicant_line(device_id) if sources else "",
                    )
            except Exception as exc:
                text = main._failure_text(exc)
                update_active_progress(text)
                self._sse("error", {"text": text})
                self._sse("done", {"ok": False})
                return
            finished = datetime.now(timezone.utc)
            turn = {
                "id": result.get("run_id"),
                "time": finished.isoformat(),
                "started": started.isoformat(),
                "elapsed_s": max(0, int((finished - started).total_seconds())),
                "prompt": shown,
                "attachments": saved_attachments,
                "answer": result.get("answer") or "",
                "thread_id": result.get("thread_id"),
                "summary_url": result.get("summary_url"),
                "level": result.get("level"),
                "run_id": result.get("run_id"),
                "stakes": result.get("stakes"),
                "shape": result.get("shape"),
                "coding": result.get("coding"),
                "git_remote": result.get("git_remote"),
                "web": result.get("web"),
                "gmail": result.get("gmail"),
                "calendar": result.get("calendar"),
                "pdfs": list(result.get("pdfs") or []),
                "documents": list(result.get("documents") or []),
                "profile_update": result.get("profile_update"),
                "profile_record": result.get("profile_record"),
                "notices": list(result.get("notices") or []),
                "committee": result.get("committee"),
            }
            if result.get("ok"):
                append_turn(turn, device_id)
            painted = decorate_turn(turn, device_id)
            notices = [
                main.NOTICE_TEXT.get(str(item).split(":", 1)[0], str(item))
                for item in turn["notices"]
            ]
            self._sse(
                "answer",
                {
                    "text": painted["answer"],
                    "answer_html": painted.get("answer_html") or "",
                    "html_pages": painted.get("html_pages") or [],
                    "level": painted["level"],
                    "run_id": painted["run_id"],
                    "thread_id": painted["thread_id"],
                    "summary_url": painted["summary_url"],
                    "stakes": painted["stakes"],
                    "shape": painted.get("shape"),
                    "coding": painted.get("coding"),
                    "git_remote": painted.get("git_remote"),
                    "web": painted.get("web"),
                    "gmail": painted.get("gmail"),
                    "calendar": painted.get("calendar"),
                    "pdfs": painted.get("pdfs") or [],
                    "documents": painted.get("documents") or [],
                    "profile_update": painted.get("profile_update"),
                    "profile_record": painted.get("profile_record"),
                    "elapsed_s": painted.get("elapsed_s"),
                    "started": painted.get("started"),
                    "notices": notices,
                    "committee": painted.get("committee"),
                },
            )
            self._sse("done", {"ok": bool(result.get("ok")), "thread_id": turn["thread_id"]})
        finally:
            logger.remove_listener(on_log)
            clear_active()

    def _save_profile(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"ok": False, "error": "bad_length"})
            return
        raw = self.rfile.read(max(length, 0)) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "bad_json"})
            return
        device = parse_device_id((body or {}).get("device"))
        if not device:
            self._send_json(400, {"ok": False, "error": "missing_device"})
            return
        run_id = str((body or {}).get("run_id") or "").strip()
        turn = find_turn(run_id, device)
        if turn is None:
            self._send_json(404, {"ok": False, "error": "turn_not_found"})
            return
        self._note_device(
            device,
            user_agent=str((body or {}).get("user_agent") or ""),
            language=str((body or {}).get("language") or ""),
        )
        update = turn.get("profile_update")
        result = profile.apply_update(update, run_id)
        if not result.get("ok"):
            self._send_json(400, result)
            return
        self._send_json(200, result)

    def _send_html(self) -> None:
        qs = parse_qs(urlparse(self.path).query)
        device = parse_device_id((qs.get("device") or [""])[0])
        if not device:
            self._send_json(400, {"ok": False, "error": "missing_device"})
            return
        target = formatter.resolve_page(
            (qs.get("run") or [""])[0],
            (qs.get("n") or [""])[0],
            device_id=device,
        )
        if target is None:
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        self._note_device(device)
        payload = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Security-Policy", formatter.CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_keep(self) -> None:
        qs = parse_qs(urlparse(self.path).query)
        folder = (qs.get("dir") or [""])[0]
        name = (qs.get("file") or [""])[0]
        download = str((qs.get("download") or [""])[0]).strip() in {"1", "true", "yes"}
        target = resolve_output_file(folder, name)
        if target is None:
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        if target.suffix.lower() in {".md", ".markdown"}:
            body = target.read_text(encoding="utf-8", errors="replace")
            page = _preview_page(target.name, formatter.render_markdown(body))
            self._send_bytes(page, "text/html; charset=utf-8")
            return
        if target.suffix.lower() == ".pdf":
            payload = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "Content-Disposition",
                f'{"attachment" if download else "inline"}; filename="{target.name}"',
            )
            self.end_headers()
            self.wfile.write(payload)
            return
        body = target.read_text(encoding="utf-8", errors="replace")
        page = (
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            f"<title>{html.escape(target.name)}</title></head><body>"
            f"<pre style=\"white-space:pre-wrap;font:14px/1.45 system-ui,sans-serif\">{html.escape(body)}</pre>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def _form_parts(self, raw: bytes) -> tuple[str, list[tuple[str, bytes]]]:
        ctype = self.headers.get("Content-Type") or ""
        if "multipart/" not in ctype.lower():
            raise ValueError("bad_upload")
        header = f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        msg = email.message_from_bytes(header + raw, policy=email_default)
        label = ""
        pending = ""
        files: list[tuple[str, bytes]] = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            payload = part.get_payload(decode=True) or b""
            field = str(part.get_param("name", header="content-disposition") or "")
            filename = part.get_filename()
            if field == "name":
                label = payload.decode("utf-8", "replace").strip()
            elif field == "rel":
                pending = payload.decode("utf-8", "replace").strip()
            elif filename or field == "file":
                files.append((pending or filename or "upload", payload))
                pending = ""
        return label, files

    def _upload(self, *, kind: str) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"ok": False, "error": "bad_length"})
            return
        if length <= 0 or length > 80 * 1024 * 1024:
            self._send_json(400, {"ok": False, "error": "file_too_large"})
            return
        raw = self.rfile.read(length)
        try:
            label, files = self._form_parts(raw)
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        if kind == "file":
            if len(files) != 1:
                self._send_json(400, {"ok": False, "error": "one_file"})
                return
            label = label or Path(files[0][0]).name
        else:
            label = label or "Folder"
        try:
            result = career.store_files(files, label=label, kind=kind)
        except ValueError as exc:
            self._send_json(400, {"ok": False, "error": str(exc)})
            return
        self._send_json(200, result)

    def _update_resume(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            self._send_json(400, {"ok": False, "error": "bad_length"})
            return
        raw = self.rfile.read(max(length, 0)) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "bad_json"})
            return
        device = parse_device_id((body or {}).get("device"))
        if not device:
            self._send_json(400, {"ok": False, "error": "missing_device"})
            return
        data = (body or {}).get("profile")
        if not isinstance(data, dict):
            self._send_json(400, {"ok": False, "error": "bad_profile"})
            return
        saved = career.save_resume(device, data, merge=bool((body or {}).get("merge")))
        self._send_json(200, {"ok": True, "profile": saved})

    def _send_download(self) -> None:
        qs = parse_qs(urlparse(self.path).query)
        target = resolve_download((qs.get("dir") or [""])[0], (qs.get("file") or [""])[0])
        if target is None:
            self._send_json(404, {"ok": False, "error": "not_found"})
            return
        download = str((qs.get("download") or [""])[0]).strip() in {"1", "true", "yes"}
        suffix = target.suffix.lower()
        if download or suffix == ".pdf":
            payload = target.read_bytes()
            kind = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
            if suffix in {".md", ".markdown", ".txt", ".py", ".csv", ".json", ".js", ".css", ".html"}:
                kind = "text/plain; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            disposition = "attachment" if download else "inline"
            self.send_header("Content-Disposition", f'{disposition}; filename="{target.name}"')
            self.end_headers()
            self.wfile.write(payload)
            return
        body = target.read_text(encoding="utf-8", errors="replace")
        if suffix in {".html", ".htm"}:
            self._send_bytes(formatter.wrap_document(body).encode("utf-8"), "text/html; charset=utf-8")
            return
        if suffix in {".md", ".markdown"}:
            inner = formatter.render_markdown(body)
        else:
            lang = html.escape(suffix.lstrip(".") or "text")
            inner = f'<pre class="code" data-lang="{lang}"><code>{html.escape(body)}</code></pre>'
        self._send_bytes(_preview_page(target.name, inner), "text/html; charset=utf-8")

    def _send_ui(self, path: Path) -> None:
        if not path.is_file():
            self._send_json(500, {"ok": False, "error": "ui_missing"})
            return
        self._send_bytes(path.read_bytes(), "text/html; charset=utf-8")

    def _send_bytes(self, payload: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_index(self) -> None:
        self._send_ui(UI_FILE)

    def _send_json(self, code: int, payload: dict[str, Any]) -> None:
        blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)

    def _sse(self, event: str, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False)
        try:
            self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
            self.wfile.flush()
        except OSError:
            return


def serve(host: str = HOST, port: int = PORT, *, no_model: bool = False) -> None:
    global NO_MODEL
    NO_MODEL = no_model
    rotate_ui_session()
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"id10t ui  http://{host}:{port}/", flush=True)
    if no_model:
        print("stub replies (--no-model); weights are not loaded", flush=True)
    httpd.serve_forever()


def main_cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="id10t local chat UI (loopback only)")
    parser.add_argument("--no-model", action="store_true", help="Heuristic route + stub reply (no GGUF load)")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    serve(HOST, args.port, no_model=args.no_model)
    return 0


if __name__ == "__main__":
    raise SystemExit(main_cli())
