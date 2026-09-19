"""Paths, env, and closed lists. Agents never import this file."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")

def _env_path(name: str, default: Path | None = None) -> Path | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    path = Path(raw)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path.resolve()


DATA_DIR = _env_path("ID10T_DATA_DIR", REPO_ROOT / "state")
LOG_DIR = DATA_DIR / "logs"
SESSION_DIR = DATA_DIR / "sessions"
TOKEN_DIR = DATA_DIR / "tokens"
THREADS_DIR = DATA_DIR / "threads"
UI_SESSION_DIR = DATA_DIR / "ui-session"
CREATED_INDEX = DATA_DIR / "createdIndex.json"
SANDBOX_ROOT = _env_path("ID10T_SANDBOX_ROOT", REPO_ROOT / "sandboxes")
WORKSPACE = _env_path("ID10T_WORKSPACE", REPO_ROOT / "input")
OUTPUTS = _env_path("ID10T_OUTPUTS", REPO_ROOT / "outputs")
MODELS_DIR = _env_path("MODELS_DIR")
BACKUP_MODELS_DIR = _env_path("BACKUP_MODELS_DIR")
HF_TOKEN = os.environ.get("HF_TOKEN")
ALLOW_HF_DOWNLOAD = os.environ.get("ID10T_HF_DOWNLOAD", "").strip() in {"1", "true", "yes"}
# Downloads are always hashed. Re-hashing multi-GB weights on every load is opt-in.
VERIFY_MODEL_HASH = os.environ.get("ID10T_VERIFY_MODEL_HASH", "").strip() in {"1", "true", "yes"}
CODING_RULES_PATH = REPO_ROOT / "coding-rules.md"
MODELS_JSON = REPO_ROOT / "models.json"

ALLOWED_DOC_TYPES = ("xlsx", "csv", "doc", "docx", "txt")
SANDBOX_EXTENSIONS = (".py", ".html", ".css", ".js")
CHAR_PAGE = 4000
ROW_PAGE = 50
MAX_PAGE_SPAN = 5
SEARCH_CAP = 50
BLACKBOARD_MAX_LEN = 4000
BLACKBOARD_MAX_COUNT = 200
EXECUTE_TIMEOUT = 30
FETCH_TIMEOUT = 10
GENERATE_MAX_TOKENS = 512
N_GPU_LAYERS = (os.environ.get("N_GPU_LAYERS") or "auto").strip()

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_LOGIN_HINT = os.environ.get("GOOGLE_LOGIN_HINT") or os.environ.get("login_hint")
MS_CLIENT_ID = os.environ.get("MS_CLIENT_ID")
MS_TENANT = os.environ.get("MS_TENANT", "common")
MS_LOGIN_HINT = os.environ.get("MS_LOGIN_HINT")

INPUT_PATHS: list[Path] = []
WRITE_PATHS: list[Path] = []
ALLOWED_PATHS: list[Path] = []
BLOCKED_PATHS: list[Path] = []


def _ensure_dirs() -> None:
    for path in (DATA_DIR, LOG_DIR, SESSION_DIR, TOKEN_DIR, THREADS_DIR, UI_SESSION_DIR, SANDBOX_ROOT, WORKSPACE, OUTPUTS):
        path.mkdir(parents=True, exist_ok=True)


def refresh_paths() -> None:
    """Rebuild allowed/blocked lists from current dirs."""
    global INPUT_PATHS, WRITE_PATHS, ALLOWED_PATHS, BLOCKED_PATHS
    INPUT_PATHS = [WORKSPACE.resolve()]
    WRITE_PATHS = [OUTPUTS.resolve()]
    ALLOWED_PATHS = list(dict.fromkeys(INPUT_PATHS + WRITE_PATHS))
    blocked: list[Path] = [
        REPO_ROOT.resolve(),
        DATA_DIR.resolve(),
        LOG_DIR.resolve(),
        SESSION_DIR.resolve(),
        TOKEN_DIR.resolve(),
        CREATED_INDEX.resolve(),
        SANDBOX_ROOT.resolve(),
        (REPO_ROOT / ".env").resolve(),
        (REPO_ROOT / "file_tools.py").resolve(),
        (REPO_ROOT / "logger.py").resolve(),
        (REPO_ROOT / "prompts").resolve(),
    ]
    if MODELS_DIR is not None:
        blocked.append(MODELS_DIR)
    if BACKUP_MODELS_DIR is not None:
        blocked.append(BACKUP_MODELS_DIR)
    BLOCKED_PATHS = blocked


def _unpinned_manifest() -> str:
    """The tracked manifest with every sha256/bytes pin cleared."""
    blob = json.loads((REPO_ROOT / "models.json").read_text(encoding="utf-8"))
    for spec in (blob.get("roles") or {}).values():
        for slot in spec.values():
            if isinstance(slot, dict):
                slot.pop("bytes", None)
                if "sha256" in slot:
                    slot["sha256"] = ""
    return json.dumps(blob, indent=2)


def use_temp(root: Path, *, allow_hf: bool = False) -> None:
    """Point all mutable state at a temp tree (tests)."""
    global DATA_DIR, LOG_DIR, SESSION_DIR, TOKEN_DIR, THREADS_DIR, UI_SESSION_DIR, CREATED_INDEX
    global SANDBOX_ROOT, WORKSPACE, OUTPUTS, ALLOW_HF_DOWNLOAD
    global MODELS_DIR, BACKUP_MODELS_DIR, MODELS_JSON
    root = Path(root).resolve()
    DATA_DIR = root / "state"
    LOG_DIR = DATA_DIR / "logs"
    SESSION_DIR = DATA_DIR / "sessions"
    TOKEN_DIR = DATA_DIR / "tokens"
    THREADS_DIR = DATA_DIR / "threads"
    UI_SESSION_DIR = DATA_DIR / "ui-session"
    CREATED_INDEX = DATA_DIR / "createdIndex.json"
    SANDBOX_ROOT = root / "sandboxes"
    WORKSPACE = root / "input"
    OUTPUTS = root / "outputs"
    MODELS_DIR = None
    BACKUP_MODELS_DIR = None
    ALLOW_HF_DOWNLOAD = allow_hf
    # Pin rewrites are real writes; keep them off the tracked manifest. Strip the pins too, so a
    # real run that has already recorded sizes cannot make the fake GGUFs in tests look tampered.
    manifest = root / "models.json"
    manifest.write_text(_unpinned_manifest(), encoding="utf-8")
    MODELS_JSON = manifest
    _ensure_dirs()
    refresh_paths()


_ensure_dirs()
refresh_paths()
