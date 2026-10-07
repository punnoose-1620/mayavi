"""Professional profile, job applications, and document text for the HTML chat."""

from __future__ import annotations

import re
import secrets
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import config
import file_tools
import jobapp
import models
import profiledoc

N_CTX = 4096
_DOC_EXT = {".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv", ".html", ".py"}
_MAX_FILES = 40
_MAX_FILE_BYTES = 20 * 1024 * 1024
_TEXT_CAP = 80_000
_UPLOADS: dict[str, dict[str, str]] = {}
_UPLOAD_LOCK = threading.Lock()


_DEVICE_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def resume_root(device_id: str) -> Path:
    did = str(device_id or "").strip().lower()
    if not _DEVICE_RE.fullmatch(did):
        raise ValueError("missing_device")
    root = config.UI_SESSION_DIR.resolve()
    target = (root / did).resolve()
    target.relative_to(root)
    target.mkdir(parents=True, exist_ok=True)
    return target


def resume_path(device_id: str) -> Path:
    return profiledoc.profile_json_path(resume_root(device_id))


def read_resume(device_id: str) -> dict:
    return profiledoc.load_profile(resume_path(device_id))


def profile_is_empty(device_id: str) -> bool:
    return profiledoc.profile_is_empty(read_resume(device_id))


def profile_text(device_id: str) -> str:
    return profiledoc.job_profile_text(resume_root(device_id))


def save_resume(device_id: str, data: dict, *, merge: bool = False) -> dict:
    path = resume_path(device_id)
    incoming = profiledoc.normalize_profile(data if isinstance(data, dict) else None)
    if merge:
        current = profiledoc.load_profile(path)
        merged, _conflicts = profiledoc.merge_profile(current, incoming)
        profiledoc.save_profile(path, merged)
        return merged
    profiledoc.save_profile(path, incoming)
    return profiledoc.load_profile(path)


def _text_of(path: Path, cap: int) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".py", ".html", ".json"}:
        return path.read_text(encoding="utf-8", errors="replace")[:cap]
    data = file_tools._read_dispatch(path, 1, 400)
    return str(data.get("text") or "")[:cap]


def _safe_rel(name: str) -> Path | None:
    raw = str(name or "").replace("\\", "/").strip("/")
    parts = [part for part in raw.split("/") if part and part not in {".", ".."}]
    if not parts:
        return None
    return Path(*parts)


def _summarize(files: list[Path], label: str, *, kind: str = "folder") -> tuple[str, str]:
    lines = [files[0].name] if kind == "file" and files else [label]
    chunks: list[str] = []
    used = 0
    for path in files:
        if kind != "file":
            lines.append(f"- {path.name}")
        if used >= _TEXT_CAP:
            continue
        try:
            text = _text_of(path, _TEXT_CAP - used)
        except Exception:
            text = ""
        if not text.strip():
            continue
        piece = f"## {path.name}\n{text.strip()}"
        chunks.append(piece)
        used += len(piece)
    if len(files) >= _MAX_FILES:
        lines.append(f"- … only the first {_MAX_FILES} files")
    return "\n".join(lines), "\n\n".join(chunks)


def store_files(items: list[tuple[str, bytes]], *, label: str, kind: str = "folder") -> dict:
    """Save an uploaded file or folder, then read the accepted documents."""
    upload_id = secrets.token_hex(8)
    root = config.DATA_DIR / "uploads" / upload_id
    root.mkdir(parents=True, exist_ok=True)
    kept: list[Path] = []
    for rel, blob in items:
        if not blob or len(blob) > _MAX_FILE_BYTES:
            continue
        safe = _safe_rel(rel)
        if safe is None or safe.suffix.lower() not in _DOC_EXT:
            continue
        dest = (root / safe).resolve()
        try:
            dest.relative_to(root.resolve())
        except ValueError:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        kept.append(dest)
        if len(kept) >= _MAX_FILES:
            break
    if not kept:
        raise ValueError("no_readable_files")
    listing, body = _summarize(kept, label, kind=kind)
    entries = [{"name": path.name} for path in kept]
    with _UPLOAD_LOCK:
        _UPLOADS[upload_id] = {
            "name": label,
            "kind": kind,
            "listing": listing,
            "body": body,
            "entries": entries,
            "truncated": len(kept) >= _MAX_FILES,
        }
    return {
        "ok": True,
        "id": upload_id,
        "name": label,
        "kind": kind,
        "listing": listing,
        "entries": entries,
        "truncated": len(kept) >= _MAX_FILES,
        "files": len(kept),
    }


def get_upload(upload_id: str) -> dict[str, str] | None:
    key = str(upload_id or "").strip()
    if not key:
        return None
    with _UPLOAD_LOCK:
        row = _UPLOADS.get(key)
    return dict(row) if row else None


def text_from_folder(folder: str) -> tuple[str, str]:
    """Return a short listing and the extracted text."""
    root = Path(str(folder or "")).expanduser()
    if not root.is_dir():
        raise ValueError("folder_not_found")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _DOC_EXT:
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        files.append(path)
        if len(files) >= _MAX_FILES:
            break
    return _summarize(files, f"Folder: {root.name}")


def pdf_bytes(title: str, body: str) -> bytes:
    dest_dir = Path(tempfile.mkdtemp(prefix="id10t-pdf-"))
    dest = dest_dir / "doc.pdf"
    file_tools._write_pdf_bytes(dest, body, {"title": title})
    return dest.read_bytes()


def _pick_role() -> str:
    roles = models.load_manifest().get("roles") or {}
    ready = [name for name in roles if models.role_is_ready(name)]

    def rank(name: str) -> tuple[int, str]:
        blob = (name + " " + str(roles.get(name) or "")).lower()
        if any(mark in blob for mark in ("14b", "32b", "70b", "72b")):
            return (2, name)
        if any(mark in blob for mark in ("3b", "7b", "8b", "6.7", "9b")):
            return (0, name)
        return (1, name)

    ready.sort(key=rank)
    if not ready:
        raise RuntimeError("no_model_fits_ram")
    return ready[0]


def _complete(role: str):
    loaded = models.loadModel(role)
    if not loaded.get("ok"):
        raise RuntimeError(str(loaded.get("error") or "model_unavailable"))

    def complete(messages, max_tokens: int = 512) -> str:
        result = models.generate(role, messages=messages, max_tokens=max_tokens)
        if not result.get("ok"):
            raise RuntimeError(str(result.get("error") or "generate_failed"))
        return str(result.get("text") or "")

    return complete


def _doc_dir() -> tuple[Path, str]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"profile-{stamp}"
    folder = config.OUTPUTS / name
    folder.mkdir(parents=True, exist_ok=True)
    return folder, name


def documents_for(dir_name: str) -> list[dict[str, str]]:
    folder = config.OUTPUTS / dir_name
    rows: list[dict[str, str]] = []
    if not folder.is_dir():
        return rows
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        rows.append({"name": path.name, "dir": dir_name, "kind": path.suffix.lower().lstrip(".")})
    return rows


def run_job(job_text: str, status, *, device_id: str, no_model: bool = False) -> dict:
    if no_model:
        return {
            "ok": True,
            "answer": "Job application needs a local model. Start the app without --no-model.",
            "level": "job",
            "shape": "job",
            "documents": [],
            "notices": [],
        }
    if profile_is_empty(device_id):
        return {"ok": False, "error": "empty_profile", "answer": ""}
    role = _pick_role()
    complete = _complete(role)
    try:
        return _run_job(complete, job_text, status, device_id)
    finally:
        models.unloadModel()


def _run_job(complete, job_text: str, status, device_id: str) -> dict:
    folder, dir_name = _doc_dir()
    result = jobapp.run_job_application(
        complete=complete,
        job_text=job_text,
        profile_text=profile_text(device_id),
        n_ctx=N_CTX,
        stop_event=None,
        status=status,
        build_pdf=pdf_bytes,
        out_dir=folder,
    )
    reply = str(result.get("reply") or "").strip()
    written = (
        ("resume", "Resume", str(result.get("resume") or "")),
        ("cover-letter", "Cover letter", str(result.get("letter") or "")),
        ("summary", "Match summary", reply),
    )
    for stem, title, body in written:
        if body.strip():
            (folder / f"{stem}.md").write_text(f"# {title}\n\n{body.strip()}\n", encoding="utf-8")
    return {
        "ok": True,
        "answer": reply or "Job application finished without a summary.",
        "level": "job",
        "shape": "job",
        "documents": documents_for(dir_name),
        "notices": [] if result.get("passed") else ["claim_check"],
        "stopped": bool(result.get("stopped")),
    }


def run_update(source_text: str, instruction: str, status, *, device_id: str = "", no_model: bool = False) -> dict:
    if no_model:
        return {
            "ok": True,
            "answer": "Update profile needs a local model. Start the app without --no-model.",
            "level": "profile",
            "shape": "profile",
            "profile_record": None,
            "documents": [],
            "notices": [],
        }
    current = profiledoc.empty_profile()
    if device_id:
        try:
            current = read_resume(device_id)
        except ValueError:
            current = profiledoc.empty_profile()
    follow_up = profiledoc.is_follow_up(current)
    role = _pick_role()
    complete = _complete(role)
    try:
        return _run_update(complete, source_text, instruction, status, current, follow_up)
    finally:
        models.unloadModel()


def _run_update(complete, source_text: str, instruction: str, status, current: dict, follow_up: bool) -> dict:
    status("Update profile: reading the resume")
    if follow_up:
        prose = complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Update the current profile using the resume and the user's request. "
                        "Keep details the resume does not change. "
                        "Use only facts from the resume or the current profile. "
                        "Sections: contact, summary, experience, projects, skills, education."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        instruction.strip()
                        + "\n\nCurrent profile:\n"
                        + profiledoc.render_profile(current).strip()
                        + "\n\nResume:\n"
                        + source_text
                    ).strip(),
                },
            ]
        )
    else:
        prose = complete(
            [
                {
                    "role": "system",
                    "content": (
                        "Read the resume and write the person's professional background. "
                        "Use only facts from the document. Sections: contact, summary, experience, "
                        "projects, skills, education."
                    ),
                },
                {"role": "user", "content": (instruction.strip() + "\n\n" + source_text).strip()},
            ]
        )
    built = profiledoc.build_update(
        complete,
        prose,
        instruction,
        source_text,
        status=status,
        stop_event=None,
        n_ctx=N_CTX,
        existing=current if follow_up else None,
    )
    answer = str(built.get("reply") or prose or "").strip()
    return {
        "ok": True,
        "answer": answer or "Update profile finished.",
        "level": "profile",
        "shape": "profile",
        "profile_record": built.get("profile_record"),
        "documents": [],
        "notices": list(built.get("dropped") or []),
        "stopped": bool(built.get("stopped")),
    }
