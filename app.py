"""Loopback chat UI. Agents never import this file."""

from __future__ import annotations

import argparse
import html
import json
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import blackboard
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


def set_active(prompt: str, thread_id: str | None, progress: str = "Working…", *, device_id: str) -> None:
    global _ACTIVE
    _ACTIVE = {"prompt": prompt, "thread_id": thread_id, "progress": progress, "device": device_id}
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


def run_turn(
    prompt: str,
    thread_id: str | None,
    *,
    coding: Any = False,
    git_remote: str | None = None,
    web: Any = False,
) -> dict[str, Any]:
    fields = main._route_fields(prompt, NO_MODEL)
    fields = router.apply_user_controls(fields, coding=coding, git_remote=git_remote, web=web)
    generate_fn = main.stub_generate if NO_MODEL else None
    return executor.run_session(prompt, fields, generate_fn=generate_fn, thread_id=thread_id)


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
            device = parse_device_id((qs.get("device") or [""])[0])
            if not device:
                self._send_json(400, {"ok": False, "error": "missing_device"})
                return
            self._note_device(device, language=(qs.get("language") or [""])[0])
            board = profile.public_board()
            self._send_json(200, {"ok": True, **board})
            return
        if path == "/web-status":
            self._send_json(200, search.status())
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/profile":
            self._save_profile()
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
        if not prompt:
            self._send_json(400, {"ok": False, "error": "empty_prompt"})
            return
        wanted = str((body or {}).get("thread_id") or "").strip() or None
        coding = (body or {}).get("coding")
        web = (body or {}).get("web")
        git_remote = str((body or {}).get("git_remote") or "").strip() or None
        user_agent = str((body or {}).get("user_agent") or "")
        language = str((body or {}).get("language") or "")
        if not _BUSY.acquire(blocking=False):
            self._send_json(409, {"ok": False, "error": "busy"})
            return
        try:
            self._stream_turn(
                prompt,
                wanted,
                coding=coding,
                git_remote=git_remote,
                web=web,
                device_id=device,
                user_agent=user_agent,
                language=language,
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
        device_id: str,
        user_agent: str = "",
        language: str = "",
    ) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        set_active(prompt, thread_id, "Working…", device_id=device_id)
        self._note_device(device_id, user_agent=user_agent, language=language)
        self._sse("progress", {"text": "Working…"})

        def on_log(record: dict[str, Any]) -> None:
            line = progress_line(record)
            if line:
                update_active_progress(line)
                self._sse("progress", {"text": line})

        logger.add_listener(on_log)
        try:
            try:
                result = run_turn(prompt, thread_id, coding=coding, git_remote=git_remote, web=web)
            except Exception as exc:
                text = main._failure_text(exc)
                update_active_progress(text)
                self._sse("error", {"text": text})
                self._sse("done", {"ok": False})
                return
            turn = {
                "id": result.get("run_id"),
                "time": datetime.now(timezone.utc).isoformat(),
                "prompt": prompt,
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
                "pdfs": list(result.get("pdfs") or []),
                "profile_update": result.get("profile_update"),
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
                    "pdfs": painted.get("pdfs") or [],
                    "profile_update": painted.get("profile_update"),
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

    def _send_index(self) -> None:
        if not UI_FILE.is_file():
            self._send_json(500, {"ok": False, "error": "ui_missing"})
            return
        payload = UI_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

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
