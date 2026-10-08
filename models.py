"""Local GGUF resolve/load. Agents never import this file."""

from __future__ import annotations

import gc
import hashlib
import importlib.util
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
_LETTER = None
_LETTER_LOCK = threading.Lock()
_LETTER_ROLE: str | None = None
_NO_SYSTEM_ROLE = False
RESERVE_BYTES = 2 * 1024 ** 3
GENERATE_MIN_AVAILABLE = 256 * 1024 ** 2
_GPU_CHECK = None


def _gpu_check():
    global _GPU_CHECK
    if _GPU_CHECK is None:
        path = Path(__file__).resolve().parent / "gpu-check.py"
        spec = importlib.util.spec_from_file_location("gpu_check", path)
        if spec is None or spec.loader is None:
            raise ImportError("gpu-check.py missing")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _GPU_CHECK = mod
    return _GPU_CHECK


def usb_manifest_path() -> Path | None:
    if config.MODELS_DIR and config.MODELS_DIR.is_dir():
        path = config.MODELS_DIR / "models.json"
        if path.is_file():
            return path
    return None


def manifest_path() -> Path:
    return usb_manifest_path() or config.MODELS_JSON


def load_manifest() -> dict[str, Any]:
    return json.loads(manifest_path().read_text(encoding="utf-8"))


def save_manifest(data: dict[str, Any]) -> None:
    manifest_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


_THIN_ROLES = {"router", "executor", "builder_qwen", "builder_llama"}


def roles_for_use(use: str) -> list[str]:
    """Role names tagged for this job, in manifest order, only if a GGUF is on disk."""
    wanted = str(use or "").strip()
    found: list[str] = []
    for name, spec in (load_manifest().get("roles") or {}).items():
        tags = spec.get("use") or []
        if wanted in tags and role_is_ready(name):
            found.append(name)
    return found


def role_is_ready(role: str) -> bool:
    spec = (load_manifest().get("roles") or {}).get(role)
    if not spec:
        return False
    primary_name = (spec.get("primary") or {}).get("filename") or ""
    for item in _candidates(role, spec):
        path = item.get("path")
        if not path or not Path(path).is_file():
            continue
        try:
            if not _ram_ok(Path(path)):
                continue
        except OSError:
            continue
        if item.get("filename") == primary_name:
            return True
        if role in _THIN_ROLES:
            return True
    return False


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
        size = item.get("bytes") or 0
        if size and path.stat().st_size != size:
            last_error = "size_mismatch"
            continue
        digest = ""
        if config.VERIFY_MODEL_HASH:
            digest = _sha256(path)
            if expected and digest != expected:
                last_error = "hash_mismatch"
                continue
            _pin_file(role, item["filename"], digest, path.stat().st_size)
        elif not size:
            _pin_file(role, item["filename"], expected, path.stat().st_size)
        chosen = {**item, "path": str(path), "sha256": digest or expected, "ok": True}
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
    path = Path(resolved["path"])
    if _LLM is not None and _LOADED_ROLE == role and _LOADED_PATH == path:
        return logger.finish(
            event="factory",
            tool="loadModel",
            run_id=run_id,
            agent_name=agent,
            result={"ok": True, "role": role, "root": _LOADED_ROOT, "path": str(path), "reused": True},
            summary=f"role={role} reused",
        )
    if _LLM is not None:
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
    try:
        gpu = _gpu_check().use_gpu(role, path)
    except Exception as exc:
        gpu = {"n_gpu_layers": 0, "reason": f"check_failed:{type(exc).__name__}"}
    layers = int(gpu.get("n_gpu_layers") or 0)
    try:
        _LLM = Llama(
            model_path=str(path),
            use_mmap=True,
            n_ctx=4096,
            n_gpu_layers=layers,
            embedding=True,
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
            result={
                "ok": True,
                "role": role,
                "root": _LOADED_ROOT,
                "path": str(path),
                "n_gpu_layers": layers,
                "gpu": gpu.get("reason"),
            },
        )
    except Exception as exc:
        if layers:
            try:
                _LLM = Llama(
                    model_path=str(path),
                    use_mmap=True,
                    n_ctx=4096,
                    n_gpu_layers=0,
                    embedding=True,
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
                    result={
                        "ok": True,
                        "role": role,
                        "root": _LOADED_ROOT,
                        "path": str(path),
                        "n_gpu_layers": 0,
                        "gpu": "fallback_cpu",
                    },
                    summary=f"gpu_fail={type(exc).__name__} cpu_fallback",
                )
            except Exception as retry_exc:
                exc = retry_exc
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
    llm = _LLM
    _LLM = None
    _LOADED_ROLE = None
    _LOADED_PATH = None
    _LOADED_ROOT = None
    if llm is not None:
        close = getattr(llm, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass
        del llm
        gc.collect()
    return logger.finish(
        event="factory",
        tool="unloadModel",
        run_id=run_id,
        agent_name=agent,
        result={"ok": True, "role": role},
    )


def canPair(role: str) -> dict[str, Any]:
    """True when free memory can hold a second copy of this role beside the one about to load."""
    resolved = resolveModel(role)
    if not resolved.get("ok"):
        return {"ok": False, "role": role, "gpu_copies": 0}
    path = Path(resolved["path"])
    weight = int(path.stat().st_size * 1.2)
    together = _available_ram() >= weight * 2 + RESERVE_BYTES
    copies = _gpu_check().gpu_copies(path, 2) if together else 0
    return {"ok": together, "role": role, "path": str(path), "gpu_copies": copies}


def loadLetter(role: str, *, gpu: bool) -> dict[str, Any]:
    """Load a second copy for the cover letter. The resume model stays loaded."""
    global _LETTER, _LETTER_ROLE
    run_id, agent = _ctx()
    resolved = resolveModel(role)
    if not resolved.get("ok"):
        return {"ok": False, "error": resolved.get("error", "resolve_failed"), "role": role}
    path = Path(resolved["path"])
    layers = 999 if gpu else 0
    try:
        _LETTER = _open_llama(path, layers)
        _LETTER_ROLE = role
    except Exception:
        if layers:
            try:
                _LETTER = _open_llama(path, 0)
                _LETTER_ROLE = role
                layers = 0
            except Exception as exc:
                _LETTER = None
                _LETTER_ROLE = None
                return logger.finish(
                    event="factory",
                    tool="loadLetter",
                    run_id=run_id,
                    agent_name=agent,
                    result={"ok": False, "error": type(exc).__name__, "role": role},
                )
        else:
            _LETTER = None
            _LETTER_ROLE = None
            return logger.finish(
                event="factory",
                tool="loadLetter",
                run_id=run_id,
                agent_name=agent,
                result={"ok": False, "error": "load_failed", "role": role},
            )
    device = "gpu" if layers else "cpu"
    return logger.finish(
        event="factory",
        tool="loadLetter",
        run_id=run_id,
        agent_name=agent,
        result={"ok": True, "role": role, "device": device, "path": str(path)},
        summary=f"role={role} device={device}",
    )


def unloadLetter() -> None:
    global _LETTER, _LETTER_ROLE
    llm = _LETTER
    _LETTER = None
    _LETTER_ROLE = None
    if llm is None:
        return
    close = getattr(llm, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass
    del llm
    gc.collect()


def generateLetter(role: str, messages: list[dict[str, str]] | None = None, **kwargs: Any) -> dict[str, Any]:
    run_id, agent = _ctx()
    if _LETTER is None or _LETTER_ROLE != role:
        return logger.finish(
            event="tool",
            tool="generate",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "not_loaded", "role": role},
        )
    with _LETTER_LOCK:
        try:
            text = _chat(_LETTER, messages or [], **kwargs)
        except Exception as exc:
            return logger.finish(
                event="tool",
                tool="generate",
                run_id=run_id,
                agent_name=agent,
                result={"ok": False, "error": type(exc).__name__, "role": role},
            )
    return logger.finish(
        event="tool",
        tool="generate",
        run_id=run_id,
        agent_name=agent,
        result={"ok": True, "role": role, "text": text},
        summary=f"role={role} letter",
    )


def _open_llama(path: Path, layers: int):
    from llama_cpp import Llama

    return Llama(
        model_path=str(path),
        use_mmap=True,
        n_ctx=4096,
        n_gpu_layers=layers,
        embedding=True,
        verbose=False,
    )


def _chat(llm, messages: list[dict[str, str]], **kwargs: Any) -> str:
    payload = _fold_system_messages(messages) if _NO_SYSTEM_ROLE else list(messages)
    try:
        out = llm.create_chat_completion(
            messages=payload,
            temperature=kwargs.get("temperature", 0.2),
            max_tokens=kwargs.get("max_tokens", config.GENERATE_MAX_TOKENS),
        )
    except Exception as exc:
        if "system role not supported" not in str(exc).lower():
            raise
        globals()["_NO_SYSTEM_ROLE"] = True
        payload = _fold_system_messages(messages)
        out = llm.create_chat_completion(
            messages=payload,
            temperature=kwargs.get("temperature", 0.2),
            max_tokens=kwargs.get("max_tokens", config.GENERATE_MAX_TOKENS),
        )
    return out["choices"][0]["message"]["content"] or ""


def embed(texts: list[str]) -> dict[str, Any]:
    """Vectors for the model already loaded. Used to compare a project description with resume text."""
    run_id, agent = _ctx()
    role = _LOADED_ROLE
    if _LLM is None or not role:
        return logger.finish(
            event="tool",
            tool="embed",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "not_loaded"},
        )
    if not _INFER_LOCK.acquire(blocking=False):
        return logger.finish(
            event="tool",
            tool="embed",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": "busy", "role": role},
        )
    try:
        vectors = _LLM.embed([str(text or "") for text in texts], normalize=True)
        if vectors and not isinstance(vectors[0], list):
            vectors = [vectors]
        return logger.finish(
            event="tool",
            tool="embed",
            run_id=run_id,
            agent_name=agent,
            result={"ok": True, "role": role, "vectors": vectors},
            summary=f"role={role} n={len(texts)}",
        )
    except Exception as exc:
        return logger.finish(
            event="tool",
            tool="embed",
            run_id=run_id,
            agent_name=agent,
            result={"ok": False, "error": type(exc).__name__, "role": role},
        )
    finally:
        _INFER_LOCK.release()


def generate(role: str, prompt: str | None = None, messages: list[dict[str, str]] | None = None, agent_name: str | None = None, **kwargs: Any) -> dict[str, Any]:
    run_id, agent = _ctx()
    if agent_name:
        agent = agent_name
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
        payload = _fold_system_messages(messages) if _NO_SYSTEM_ROLE else list(messages)
        if _available_ram() < GENERATE_MIN_AVAILABLE:
            unloadModel()
            return logger.finish(
                event="tool",
                tool="generate",
                run_id=run_id,
                agent_name=agent,
                result={"ok": False, "error": "ram_dropped", "role": role},
            )
        try:
            out = _LLM.create_chat_completion(
                messages=payload,
                temperature=kwargs.get("temperature", 0.2),
                max_tokens=kwargs.get("max_tokens", config.GENERATE_MAX_TOKENS),
            )
        except Exception as exc:
            if "system role not supported" not in str(exc).lower():
                raise
            globals()["_NO_SYSTEM_ROLE"] = True
            payload = _fold_system_messages(messages)
            out = _LLM.create_chat_completion(
                messages=payload,
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


def _fold_system_messages(messages: list[dict[str, str]]) -> list[dict[str, str]]:
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
        return rest or messages
    prefix = "\n\n".join(systems)
    for i, msg in enumerate(rest):
        if msg.get("role") == "user":
            rest[i] = {"role": "user", "content": prefix + "\n\n" + msg.get("content", "")}
            return rest
    return [{"role": "user", "content": prefix}] + rest


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
    primary = spec.get("primary") or {}
    backup = spec.get("backup") or {}
    if config.MODELS_DIR and config.MODELS_DIR.is_dir():
        if primary.get("filename"):
            out.append(_candidate(role, "usb", primary, config.MODELS_DIR / primary["filename"]))
        if backup.get("filename") and backup.get("filename") != primary.get("filename"):
            out.append(_candidate(role, "usb", backup, config.MODELS_DIR / backup["filename"]))
    if config.BACKUP_MODELS_DIR and config.BACKUP_MODELS_DIR.is_dir():
        if backup.get("filename"):
            out.append(_candidate(role, "backup", backup, config.BACKUP_MODELS_DIR / backup["filename"]))
        if primary.get("filename"):
            out.append(_candidate(role, "backup", primary, config.BACKUP_MODELS_DIR / primary["filename"]))
    return out


def _candidate(role: str, root: str, slot: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "role": role,
        "root": root,
        "repo_id": slot.get("repo_id") or "",
        "filename": slot.get("filename") or "",
        "revision": slot.get("revision") or "main",
        "sha256": slot.get("sha256") or "",
        "bytes": slot.get("bytes") or 0,
        "path": path,
    }


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
        _pin_file(role, slot["filename"], digest, Path(path).stat().st_size)
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


def _pin_file(role: str, filename: str, digest: str, size: int) -> None:
    """First good copy of a file records its pin; later loads check the pin instead of trusting the name."""
    try:
        data = load_manifest()
        spec = data.get("roles", {}).get(role) or {}
        changed = False
        for key in ("primary", "backup"):
            slot = spec.get(key) or {}
            if slot.get("filename") != filename:
                continue
            if digest and not slot.get("sha256"):
                slot["sha256"] = digest
                changed = True
            if size and not slot.get("bytes"):
                slot["bytes"] = size
                changed = True
        if changed:
            save_manifest(data)
    except Exception:
        return


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
