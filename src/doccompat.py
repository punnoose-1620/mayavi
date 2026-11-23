"""Small helpers the USB profile and job modules expect."""

from __future__ import annotations

import json
import re
from pathlib import Path

N_CTX_DEFAULT = 4096
MAX_TOKENS_DEFAULT = 512
CTX_SLACK = 64
HTML_CHARS_PER_TOKEN = 3
WEB_MAX_CHUNKS = 8


def profile_path(root: Path) -> Path:
    return root / "profile.md"


def read_profile(path: Path, cap: int = 24_000) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:cap]


def estimate_tokens(text: str) -> int:
    raw = text or ""
    if not raw:
        return 0
    return max(1, len(raw) // 4)


def flatten_prompt(messages: list[dict]) -> str:
    return "\n".join(str(item.get("content") or "") for item in messages or [])


def messages_tokens(messages: list[dict]) -> int:
    return estimate_tokens(flatten_prompt(messages))


def token_budget(n_ctx: int) -> int:
    return max(256, int(n_ctx) - MAX_TOKENS_DEFAULT - CTX_SLACK)


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


def _blob_char_budget(n_ctx: int, user_text: str, system: str, chars_per_token: int = HTML_CHARS_PER_TOKEN) -> int:
    overhead = estimate_tokens(system) + estimate_tokens(f"User request:\n{user_text}\n\n") + 32
    room = max(64, token_budget(n_ctx) - overhead)
    return max(400, room * chars_per_token)


def _stopped(stop_event) -> bool:
    return stop_event is not None and stop_event.is_set()


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
