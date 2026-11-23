"""Device-scoped memory index. Agents never import this file.

Logs and notebook JSON stay the source of truth. Chroma is a search index.
The host retrieves a short pack; models do not query Chroma themselves.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from typing import Any

import blackboard
import config
import tenant

COLLECTION = "mayavi_memory"
PACK_CAP = 1800
HIT_CAP = 400
N_HITS = 6
SMALL_TALK = 24
_LOCK = threading.Lock()
_CLIENT: Any = None
_COL: Any = None
_HASH_ONLY = False

_SAFE_ID = re.compile(r"[^a-zA-Z0-9:_-]+")


class _HashEmbedding:
    """Deterministic stand-in when Chroma's MiniLM is unavailable (tests / --no-model).

    Chroma 1.5 queries call embed_query; upserts call __call__. Both must exist.
    """

    @staticmethod
    def name() -> str:
        return "hash-32"

    def __call__(self, input: list[str] | str) -> list[list[float]]:
        texts = input if isinstance(input, list) else [input]
        out: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(str(text or "").encode("utf-8")).digest()
            out.append([(b - 128) / 128.0 for b in digest[:32]])
        return out

    def embed_query(self, input: list[str] | str) -> list[list[float]]:
        return self(input)

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(_config: dict[str, Any] | None = None) -> "_HashEmbedding":
        return _HashEmbedding()


def reset() -> None:
    global _CLIENT, _COL
    with _LOCK:
        _CLIENT = None
        _COL = None


def use_hash_embeddings() -> None:
    """Tests: skip MiniLM download. Call before the first collection use."""
    global _HASH_ONLY
    _HASH_ONLY = True
    reset()


def retrieve_pack(
    device_id: str | None,
    prompt: str,
    *,
    workbook: str = "",
    force: bool = False,
    coding: bool = False,
    web: bool = False,
) -> str:
    """Host-owned retrieval. Empty if Chroma is missing or there is nothing to pin."""
    did = tenant.parse_device_id(device_id)
    if not did:
        return ""
    if not _should_retrieve(prompt, workbook, force=force, coding=coding, web=web):
        return ""
    hits = search_memory(did, prompt, workbook=workbook, n=N_HITS)
    if not hits:
        return ""
    lines = ["Retrieved notes (related earlier turns; not the current request):"]
    used = 0
    for hit in hits:
        kind = str(hit.get("kind") or "turn")
        text = " ".join(str(hit.get("text") or "").split())[:HIT_CAP]
        if not text:
            continue
        line = f"- [{kind}] {text}"
        if used + len(line) + 1 > PACK_CAP:
            break
        lines.append(line)
        used += len(line) + 1
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def index_run(run: Any, answer: str | None) -> None:
    did = tenant.parse_device_id(getattr(run, "device_id", None))
    if not did:
        return
    prompt = str(getattr(run, "user_prompt", "") or "").strip()
    reply = str(answer or "").strip()
    workbook = str(getattr(run, "thread_id", "") or "").strip()
    run_id = str(getattr(run, "run_id", "") or "").strip() or _stamp()
    blob = (prompt + "\n" + reply).strip()
    if blob:
        upsert(
            _row_id(did, "turn", run_id),
            blob[:2000],
            device=did,
            workbook=workbook,
            kind="turn",
        )
    thread = getattr(run, "thread", None)
    if isinstance(thread, dict) and workbook:
        card = blackboard.context_card(thread)
        if card.strip():
            upsert(
                _row_id(did, "card", workbook),
                card[:2000],
                device=did,
                workbook=workbook,
                kind="card",
            )


def upsert(row_id: str, text: str, *, device: str, workbook: str, kind: str) -> None:
    col = _collection()
    if col is None:
        return
    body = str(text or "").strip()
    if not body:
        return
    meta = {
        "device": device,
        "workbook": workbook or "none",
        "kind": kind if kind in {"turn", "card", "log"} else "turn",
        "ts": _stamp(),
    }
    with _LOCK:
        col.upsert(ids=[row_id], documents=[body], metadatas=[meta])


def search_memory(device_id: str, query: str, *, workbook: str = "", n: int = N_HITS) -> list[dict[str, Any]]:
    did = tenant.parse_device_id(device_id)
    col = _collection()
    if not did or col is None:
        return []
    q = str(query or "").strip()
    if not q:
        return []
    wb = _workbook_id(did, workbook)
    n = max(1, min(int(n or N_HITS), 12))
    try:
        total = int(col.count() or 0)
    except Exception:
        total = n
    if total <= 0:
        return []
    want = min(n, total)
    raw = _query(col, q, want, _where(did, wb))
    if raw is None and wb:
        raw = _query(col, q, min(max(want * 3, want), total), _where(did, ""))
    if raw is None:
        return []
    return _hits(raw, did, wb, n)


def list_notebooks(device_id: str) -> list[dict[str, Any]]:
    did = tenant.parse_device_id(device_id)
    if not did:
        return []
    return blackboard.list_workbooks(did)


def get_notebook(device_id: str, workbook: str) -> dict[str, Any] | None:
    did = tenant.parse_device_id(device_id)
    if not did:
        return None
    return blackboard.resolve_workbook(did, workbook)


def read_log_span(device_id: str, *, workbook: str = "", n: int = 20) -> list[dict[str, Any]]:
    did = tenant.parse_device_id(device_id)
    folder = tenant.device_dir(did or "")
    if folder is None:
        return []
    n = max(1, min(int(n or 20), 50))
    wb = _workbook_id(did, workbook)
    slug = blackboard.agent_slug(wb or workbook) if (wb or workbook) else None
    path = folder / "session.jsonl"
    filter_thread = ""
    if slug:
        candidate = folder / "agents" / f"{slug}.jsonl"
        if candidate.is_file():
            path = candidate
        elif wb:
            filter_thread = wb
    elif wb:
        filter_thread = wb
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    picked: list[dict[str, Any]] = []
    for raw in reversed(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            blob = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(blob, dict):
            continue
        tid = str(blob.get("thread_id") or blob.get("workbook") or "")
        if filter_thread and tid != filter_thread:
            continue
        picked.append(
            {
                "prompt": str(blob.get("prompt") or blob.get("user") or "")[:400],
                "answer": str(blob.get("answer") or blob.get("response") or "")[:400],
                "time": str(blob.get("time") or ""),
                "thread_id": tid,
            }
        )
        if len(picked) >= n:
            break
    picked.reverse()
    return picked


def _should_retrieve(
    prompt: str,
    workbook: str,
    *,
    force: bool,
    coding: bool,
    web: bool,
) -> bool:
    if force or str(workbook or "").strip() or coding or web:
        return True
    return len(str(prompt or "").strip()) >= SMALL_TALK


def _workbook_id(device_id: str, workbook: str) -> str:
    wanted = str(workbook or "").strip()
    if not wanted:
        return ""
    blob = blackboard.resolve_workbook(device_id, wanted)
    if blob and blob.get("id"):
        return str(blob["id"])
    return blackboard.agent_thread_id(wanted) or wanted


def _where(device_id: str, workbook: str) -> dict[str, Any]:
    if workbook:
        return {"$and": [{"device": {"$eq": device_id}}, {"workbook": {"$eq": workbook}}]}
    return {"device": {"$eq": device_id}}


def _query(col: Any, query: str, n: int, where: dict[str, Any]) -> dict[str, Any] | None:
    include = ["documents", "metadatas"]
    try:
        with _LOCK:
            return col.query(query_texts=[query], n_results=max(1, n), where=where, include=include)
    except Exception:
        return None


def _hits(raw: dict[str, Any], device_id: str, workbook: str, n: int) -> list[dict[str, Any]]:
    docs = (raw.get("documents") or [[]])[0]
    metas = (raw.get("metadatas") or [[]])[0]
    rows: list[dict[str, Any]] = []
    for text, meta in zip(docs, metas):
        info = meta if isinstance(meta, dict) else {}
        if str(info.get("device") or "") != device_id:
            continue
        if workbook and str(info.get("workbook") or "") != workbook:
            continue
        body = str(text or "")
        if not body:
            continue
        rows.append(
            {
                "text": body,
                "kind": str(info.get("kind") or "turn"),
                "workbook": str(info.get("workbook") or ""),
                "ts": str(info.get("ts") or ""),
            }
        )
        if len(rows) >= n:
            break
    return rows


def _collection() -> Any:
    global _CLIENT, _COL
    with _LOCK:
        if _COL is not None:
            return _COL
        try:
            import chromadb
        except ImportError:
            return None
        path = config.DATA_DIR / "chroma"
        path.mkdir(parents=True, exist_ok=True)
        ef = _embedding()
        _CLIENT = chromadb.PersistentClient(path=str(path))
        kwargs: dict[str, Any] = {"name": COLLECTION}
        if ef is not None:
            kwargs["embedding_function"] = ef
        _COL = _CLIENT.get_or_create_collection(**kwargs)
        return _COL


def _embedding() -> Any:
    if _HASH_ONLY:
        return _HashEmbedding()
    try:
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        return DefaultEmbeddingFunction()
    except Exception:
        return _HashEmbedding()


def _row_id(*parts: str) -> str:
    raw = ":".join(str(p or "") for p in parts)
    return _SAFE_ID.sub("-", raw)[:180]


def _stamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
