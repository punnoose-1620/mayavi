"""Loopback chat UI. Agents never import this file."""

from __future__ import annotations

import argparse
import json
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import blackboard
import config
import executor
import logger
import main

HOST = "127.0.0.1"
PORT = 8765
UI_FILE = config.REPO_ROOT / "ui" / "index.html"
NO_MODEL = False
_BUSY = threading.Lock()
_SESSION_LOCK = threading.Lock()
_ACTIVE: dict[str, Any] | None = None

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
    "listMails": "Listing mail",
    "openMail": "Opening mail",
    "sendMail": "Sending mail",
    "searchMails": "Searching mail",
    "replyMail": "Replying to mail",
    "mapRoute": "Routing",
}


def rotate_ui_session() -> None:
    """Keep one previous tape, then start a fresh session.jsonl."""
    folder = config.UI_SESSION_DIR
    folder.mkdir(parents=True, exist_ok=True)
    session = folder / "session.jsonl"
    previous = folder / "previous.jsonl"
    if session.is_file():
        previous.unlink(missing_ok=True)
        session.replace(previous)
    clear_active()


def read_history() -> list[dict[str, Any]]:
    path = config.UI_SESSION_DIR / "session.jsonl"
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


def read_active() -> dict[str, Any] | None:
    if _ACTIVE is None:
        return None
    return dict(_ACTIVE)


def set_active(prompt: str, thread_id: str | None, progress: str = "Working…") -> None:
    global _ACTIVE
    _ACTIVE = {"prompt": prompt, "thread_id": thread_id, "progress": progress}
    _write_active()


def update_active_progress(text: str) -> None:
    if _ACTIVE is None:
        return
    _ACTIVE["progress"] = text
    _write_active()


def clear_active() -> None:
    global _ACTIVE
    _ACTIVE = None
    path = config.UI_SESSION_DIR / "active.json"
    path.unlink(missing_ok=True)


def _write_active() -> None:
    if _ACTIVE is None:
        return
    config.UI_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = config.UI_SESSION_DIR / "active.json"
    with _SESSION_LOCK:
        path.write_text(json.dumps(_ACTIVE, ensure_ascii=False), encoding="utf-8")


def append_turn(turn: dict[str, Any]) -> None:
    config.UI_SESSION_DIR.mkdir(parents=True, exist_ok=True)
    path = config.UI_SESSION_DIR / "session.jsonl"
    with _SESSION_LOCK:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(turn, ensure_ascii=False) + "\n")


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
    for key in ("path", "host", "name", "directory"):
        match = re.search(rf"{key}=([^\s]+)", summary)
        if not match:
            continue
        value = match.group(1).strip().strip("'\"")
        if key == "host":
            return value
        return Path(value).name
    match = re.search(r"level=(\w+)", summary)
    if match:
        return match.group(1)
    return ""


def run_turn(prompt: str, thread_id: str | None) -> dict[str, Any]:
    fields = main._route_fields(prompt, NO_MODEL)
    generate_fn = main.stub_generate if NO_MODEL else None
    return executor.run_session(prompt, fields, generate_fn=generate_fn, thread_id=thread_id)


class Handler(BaseHTTPRequestHandler):
    server_version = "id10t-ui"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_index()
            return
        if path == "/threads":
            self._send_json(200, {"ok": True, "threads": blackboard.list_threads()})
            return
        if path == "/history":
            self._send_json(200, {"ok": True, "turns": read_history(), "active": read_active()})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
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
        prompt = str((body or {}).get("prompt") or "").strip()
        if not prompt:
            self._send_json(400, {"ok": False, "error": "empty_prompt"})
            return
        wanted = str((body or {}).get("thread_id") or "").strip() or None
        if not _BUSY.acquire(blocking=False):
            self._send_json(409, {"ok": False, "error": "busy"})
            return
        try:
            self._stream_turn(prompt, wanted)
        finally:
            _BUSY.release()

    def _stream_turn(self, prompt: str, thread_id: str | None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        set_active(prompt, thread_id, "Working…")
        self._sse("progress", {"text": "Working…"})

        def on_log(record: dict[str, Any]) -> None:
            line = progress_line(record)
            if line:
                update_active_progress(line)
                self._sse("progress", {"text": line})

        logger.add_listener(on_log)
        try:
            try:
                result = run_turn(prompt, thread_id)
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
                "level": result.get("level"),
                "run_id": result.get("run_id"),
                "stakes": result.get("stakes"),
                "notices": list(result.get("notices") or []),
            }
            if result.get("ok"):
                append_turn(turn)
            notices = [
                main.NOTICE_TEXT.get(str(item).split(":", 1)[0], str(item))
                for item in turn["notices"]
            ]
            self._sse(
                "answer",
                {
                    "text": turn["answer"],
                    "level": turn["level"],
                    "run_id": turn["run_id"],
                    "thread_id": turn["thread_id"],
                    "stakes": turn["stakes"],
                    "notices": notices,
                },
            )
            self._sse("done", {"ok": bool(result.get("ok")), "thread_id": turn["thread_id"]})
        finally:
            logger.remove_listener(on_log)
            clear_active()

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
