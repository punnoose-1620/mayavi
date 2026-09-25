"""Standalone USB chat helpers. No factory imports."""

from __future__ import annotations

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

LOG_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})_\d{6}\.log$")
_QUANT = re.compile(
    r"(?i)[-_.](Q\d+_K[_-][SML]|Q\d+_[01]|IQ\d+_X[SML]|IQ\d+_XXS|F16|F32|BF16)$"
)
_INSTRUCT = re.compile(r"(?i)[-_](Instruct|Chat|it)$")
_SS_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

ALLOWED_ATTACH = {".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv"}


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


def purge_old_logs(log_root: Path, today: date | None = None, keep_days: int = LOG_KEEP_DAYS) -> list[Path]:
    today = today or date.today()
    cutoff = today - timedelta(days=keep_days)
    removed: list[Path] = []
    if not log_root.is_dir():
        return removed
    for path in log_root.iterdir():
        stamped = session_date(path)
        if stamped is None or stamped >= cutoff:
            continue
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed


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
        name = str(att.get("name") or "document")
        body = str(att.get("text") or "")[:DOC_CAP]
        parts.append(f"Attached {name}:\n{body}")
    parts.append(user_text)
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages


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

    def stream(self, messages: list[dict[str, str]], stop_event):
        chunks = self.llm.create_chat_completion(
            messages,
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
