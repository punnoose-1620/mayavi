"""Local GGUF resolve/load. Agents never import this file."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

import config
import logger

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore

_INFER_LOCK = threading.Lock()
_LLM = None
_LOADED_ROLE: str | None = None
_LOADED_PATH: Path | None = None
_LOADED_ROOT: str | None = None
RESERVE_BYTES = 2 * 1024 ** 3
GENERATE_MIN_AVAILABLE = 256 * 1024 ** 2


def load_manifest() -> dict[str, Any]:
    return json.loads(config.MODELS_JSON.read_text(encoding="utf-8"))


def save_manifest(data: dict[str, Any]) -> None:
    config.MODELS_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def checkRam(role: str, file_path: str | Path | None = None) -> dict[str, Any]:
    run_id, agent = _ctx()
    path = Path(file_path) if file_path else None
    size = path.stat().st_size if path and path.is_file() else 0
    need = int(size * 1.2) + RESERVE_BYTES
    avail = _available_ram()
    ok = avail >= need if size else avail >= RESERVE_BYTES
    result = {
        "ok": ok,
        "role": role,
        "need": need,
        "available": avail,
        "path": str(path) if path else None,
    }
    return logger.finish(
        event="factory",
        tool="checkRam",
        run_id=run_id,
        agent_name=agent,
        result=result,
        summary=f"role={role} available={avail} need={need}",
    )


def resolveModel(role: str) -> dict[str, Any]:
    run_id, agent = _ctx()
    manifest = load_manifest()
    spec = manifest.get("roles", {}).get(role)
    if not spec:
        return logger.finish(
            event="factory",
            tool="resolveModel",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "unknown_role", "role": role},
        )
    candidates = _candidates(role, spec)
    chosen = None
    last_error = "not_found"
    for item in candidates:
        path = item["path"]
        if not path.is_file():
            continue
        ram = _ram_ok(path)
        if not ram:
            last_error = "ram"
            continue
        expected = item.get("sha256") or ""
        if expected:
            digest = _sha256(path)
            if digest != expected:
                last_error = "hash_mismatch"
                continue
        else:
            digest = ""
        chosen = {**item, "path": str(path), "sha256": digest, "ok": True}
        break
    if chosen is None and config.ALLOW_HF_DOWNLOAD:
        chosen = _download_backup(role, spec)
        last_error = chosen.get("error", last_error) if not chosen.get("ok") else last_error
    if not chosen or not chosen.get("ok"):
        return logger.finish(
            event="factory",
            tool="resolveModel",
            run_id=run_id,
            agent_name=agent,
            result={
                "ok": False,
                "error": last_error,
                "role": role,
                "filename": spec["primary"]["filename"],
            },
            summary=f"role={role} {last_error}",
        )
    return logger.finish(
        event="factory",
        tool="resolveModel",
        run_id=run_id,
        agent_name=agent,
        result=chosen,
        summary=f"role={role} root={chosen.get('root')}",
    )


def loadModel(role: str) -> dict[str, Any]:
    """Load one GGUF with mmap. Not exercised until weights exist on disk."""
    global _LLM, _LOADED_ROLE, _LOADED_PATH, _LOADED_ROOT
    run_id, agent = _ctx()
    resolved = resolveModel(role)
    if not resolved.get("ok"):
        return logger.finish(
            event="factory",
            tool="loadModel",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": resolved.get("error", "resolve_failed"), "role": role},
        )
    if _LOADED_ROLE and _LOADED_ROLE != role:
        unloadModel()
    try:
        from llama_cpp import Llama
    except ImportError:
        return logger.finish(
            event="factory",
            tool="loadModel",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "llama_cpp_missing", "role": role},
        )
    path = Path(resolved["path"])
    try:
        _LLM = Llama(
            model_path=str(path),
            use_mmap=True,
            n_ctx=4096,
            n_gpu_layers=config.N_GPU_LAYERS,
            verbose=False,
        )
        _LOADED_ROLE = role
        _LOADED_PATH = path
        _LOADED_ROOT = resolved.get("root")
        return logger.finish(
            event="factory",
            tool="loadModel",
            run_id=run_id,
            agent_name=agent,
            result={"ok": True, "role": role, "root": _LOADED_ROOT, "path": str(path)},
        )
    except Exception as exc:
        _LLM = None
        _LOADED_ROLE = None
        return logger.finish(
            event="factory",
            tool="loadModel",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": type(exc).__name__, "role": role},
        )


def unloadModel() -> dict[str, Any]:
    global _LLM, _LOADED_ROLE, _LOADED_PATH, _LOADED_ROOT
    run_id, agent = _ctx()
    role = _LOADED_ROLE
    _LLM = None
    _LOADED_ROLE = None
    _LOADED_PATH = None
    _LOADED_ROOT = None
    return logger.finish(
        event="factory",
        tool="unloadModel",
        run_id=run_id,
        agent_name=agent,
        result={"ok": True, "role": role},
    )


def generate(role: str, prompt: str | None = None, messages: list[dict[str, str]] | None = None, **kwargs: Any) -> dict[str, Any]:
    run_id, agent = _ctx()
    if _LLM is None or _LOADED_ROLE != role:
        return logger.finish(
            event="tool",
            tool="generate",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "not_loaded", "role": role},
        )
    if not _INFER_LOCK.acquire(blocking=False):
        return logger.finish(
            event="tool",
            tool="generate",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "busy", "role": role},
        )
    try:
        if messages is None:
            messages = [{"role": "user", "content": prompt or ""}]
        if _available_ram() < GENERATE_MIN_AVAILABLE:
            unloadModel()
            return logger.finish(
                event="tool",
                tool="generate",
                run_id=run_id,
                agent_name=agent,
                result={"ok": False, "error": "ram_dropped", "role": role},
            )
        out = _LLM.create_chat_completion(
            messages=messages,
            temperature=kwargs.get("temperature", 0.2),
            max_tokens=kwargs.get("max_tokens", config.GENERATE_MAX_TOKENS),
        )
        text = out["choices"][0]["message"]["content"] or ""
        return logger.finish(
            event="tool",
            tool="generate",
            run_id=run_id,
            agent_name=agent,
            result={"ok": True, "role": role, "text": text},
            summary=f"role={role}",
        )
    except Exception as exc:
        return logger.finish(
            event="tool",
            tool="generate",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": type(exc).__name__, "role": role},
        )
    finally:
        _INFER_LOCK.release()


def checkAndUpdateModels(used_root: str | None = None) -> dict[str, Any]:
    run_id, agent = _ctx()
    if not config.ALLOW_HF_DOWNLOAD:
        return logger.finish(
            event="factory",
            tool="checkAndUpdateModels",
            run_id=run_id,
            agent_name=agent,
            result={"ok": True, "skipped": True, "reason": "download_disabled"},
        )
    try:
        from huggingface_hub import HfApi, hf_hub_download
    except ImportError:
        return logger.finish(
            event="factory",
            tool="checkAndUpdateModels",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "huggingface_hub_missing"},
        )
    dest_root = _root_dir(used_root)
    if dest_root is None:
        return logger.finish(
            event="factory",
            tool="checkAndUpdateModels",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "no_dest_root"},
        )
    manifest = load_manifest()
    api = HfApi(token=config.HF_TOKEN)
    updated = []
    failed = []
    for role, spec in manifest.get("roles", {}).items():
        slot = spec["primary"] if used_root == "usb" else spec["backup"]
        try:
            info = api.model_info(slot["repo_id"], revision=None, token=config.HF_TOKEN)
            latest = getattr(info, "sha", None) or "main"
            if latest == slot.get("revision"):
                continue
            path = hf_hub_download(
                repo_id=slot["repo_id"],
                filename=slot["filename"],
                revision=latest,
                local_dir=str(dest_root),
                token=config.HF_TOKEN,
            )
            slot["revision"] = latest
            slot["sha256"] = _sha256(Path(path))
            updated.append(role)
        except Exception:
            failed.append(role)
    save_manifest(manifest)
    ok = not failed
    return logger.finish(
        event="factory",
        tool="checkAndUpdateModels",
        run_id=run_id,
        agent_name=agent,
        result={"ok": ok, "updated": updated, "failed": failed, "root": used_root},
    )


def expected_filename(role: str) -> str:
    spec = load_manifest()["roles"].get(role) or {}
    return (spec.get("primary") or {}).get("filename") or role


def usb_present() -> bool:
    return bool(config.MODELS_DIR and config.MODELS_DIR.is_dir())


def _candidates(role: str, spec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if config.MODELS_DIR and config.MODELS_DIR.is_dir():
        primary = spec["primary"]
        out.append(
            {
                "role": role,
                "root": "usb",
                "repo_id": primary["repo_id"],
                "filename": primary["filename"],
                "revision": primary.get("revision") or "main",
                "sha256": primary.get("sha256") or "",
                "path": config.MODELS_DIR / primary["filename"],
            }
        )
    backup = spec["backup"]
    if config.BACKUP_MODELS_DIR and config.BACKUP_MODELS_DIR.is_dir():
        out.append(
            {
                "role": role,
                "root": "backup",
                "repo_id": backup["repo_id"],
                "filename": backup["filename"],
                "revision": backup.get("revision") or "main",
                "sha256": backup.get("sha256") or "",
                "path": config.BACKUP_MODELS_DIR / backup["filename"],
            }
        )
        out.append(
            {
                "role": role,
                "root": "backup",
                "repo_id": spec["primary"]["repo_id"],
                "filename": spec["primary"]["filename"],
                "revision": spec["primary"].get("revision") or "main",
                "sha256": spec["primary"].get("sha256") or "",
                "path": config.BACKUP_MODELS_DIR / spec["primary"]["filename"],
            }
        )
    return out


def _download_backup(role: str, spec: dict[str, Any]) -> dict[str, Any]:
    if not config.BACKUP_MODELS_DIR:
        return {"ok": False, "error": "no_backup_dir", "role": role}
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        return {"ok": False, "error": "huggingface_hub_missing", "role": role}
    config.BACKUP_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    slot = spec["backup"]
    try:
        path = hf_hub_download(
            repo_id=slot["repo_id"],
            filename=slot["filename"],
            revision=slot.get("revision") or "main",
            local_dir=str(config.BACKUP_MODELS_DIR),
            token=config.HF_TOKEN,
        )
        digest = _sha256(Path(path))
        if slot.get("sha256") and digest != slot["sha256"]:
            return {"ok": False, "error": "hash_mismatch", "role": role}
        return {
            "ok": True,
            "role": role,
            "root": "hf_to_backup",
            "repo_id": slot["repo_id"],
            "filename": slot["filename"],
            "revision": slot.get("revision") or "main",
            "sha256": digest,
            "path": str(path),
        }
    except Exception as exc:
        return {"ok": False, "error": type(exc).__name__, "role": role}


def _ram_ok(path: Path) -> bool:
    size = path.stat().st_size
    need = int(size * 1.2) + RESERVE_BYTES
    # Spec is approximate; mmap does not copy the file, and Windows available RAM jitters.
    return _available_ram() + 256 * 1024 * 1024 >= need


def _available_ram() -> int:
    if psutil is None:
        return RESERVE_BYTES * 4
    return int(psutil.virtual_memory().available)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _root_dir(tag: str | None) -> Path | None:
    if tag == "usb":
        return config.MODELS_DIR
    if tag in {"backup", "hf_to_backup", None}:
        return config.BACKUP_MODELS_DIR
    return config.BACKUP_MODELS_DIR


def _ctx() -> tuple[str | None, str | None]:
    import store

    for run in list(store._RUNS.values()):  # noqa: SLF001
        if run.router_agent:
            return run.run_id, run.router_agent
        if run.agents:
            name = next(iter(run.agents))
            return run.run_id, name
    return None, "script"
