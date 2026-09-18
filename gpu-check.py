"""Decide whether this GGUF load may use GPU offload. Factory only; agents never import this."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import config

DESKTOP_RESERVE = 1024 ** 3
FILE_HEADROOM = 1.2
FULL_OFFLOAD = 999
CPU_ONLY_ROLES = ("router",)


def use_gpu(role: str, file_path: str | Path | None = None) -> dict[str, Any]:
    """Public: whether this agent's GGUF should run with GPU layers."""
    path = Path(file_path) if file_path else None
    forced = _override()
    dedicated = _dedicated_vram()
    need = _need_bytes(path)
    base = {
        "ok": False,
        "n_gpu_layers": 0,
        "role": role,
        "path": str(path) if path else None,
        "dedicated": dedicated,
        "need": need,
    }
    if forced == 0:
        return {**base, "reason": "forced"}
    if forced is None and _cpu_only_role(role):
        return {**base, "reason": "cpu_role"}
    if not _driver_ok():
        return {**base, "reason": "driver"}
    if not _device_ok():
        return {**base, "reason": "device"}
    if not _wheel_ok():
        return {**base, "reason": "wheel"}
    if forced is not None:
        return {**base, "ok": True, "n_gpu_layers": forced, "reason": "forced"}
    if path is None or not path.is_file():
        return {**base, "reason": "no_file"}
    if dedicated is None:
        return {**base, "reason": "device"}
    usable = dedicated - DESKTOP_RESERVE
    if usable <= 0 or usable < need:
        return {**base, "reason": "vram"}
    return {**base, "ok": True, "n_gpu_layers": FULL_OFFLOAD, "reason": "auto"}


def _cpu_only_role(role: str) -> bool:
    """The router is a short warm call; GPU layers go to the agents doing the work."""
    return str(role or "").strip().lower() in CPU_ONLY_ROLES


def _override() -> int | None:
    raw = str(getattr(config, "N_GPU_LAYERS", "") or os.environ.get("N_GPU_LAYERS") or "auto").strip().lower()
    if raw in {"", "auto", "true", "yes"}:
        return None
    if raw in {"0", "false", "no", "cpu"}:
        return 0
    try:
        n = int(raw)
    except ValueError:
        return 0
    return n if n > 0 else 0


def _driver_ok() -> bool:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return False
    try:
        proc = subprocess.run([exe, "-L"], capture_output=True, timeout=8, text=True)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and bool((proc.stdout or "").strip())


def _device_ok() -> bool:
    dedicated = _dedicated_vram()
    return dedicated is not None and dedicated > 0


def _dedicated_vram() -> int | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            timeout=8,
            text=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    sizes: list[int] = []
    for line in (proc.stdout or "").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            sizes.append(int(float(text) * 1024 * 1024))
        except ValueError:
            continue
    if not sizes:
        return None
    return max(sizes)


def _wheel_ok() -> bool:
    try:
        import llama_cpp
    except ImportError:
        return False
    fn = getattr(llama_cpp, "llama_supports_gpu_offload", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            return False
    lib = getattr(llama_cpp, "llama_cpp", llama_cpp)
    for name in ("GGML_USE_CUBLAS", "GGML_USE_CUDA", "GGML_USE_METAL", "GGML_USE_VULKAN", "GGML_USE_HIP"):
        if bool(getattr(lib, name, False)):
            return True
    return False


def _need_bytes(path: Path | None) -> int:
    if path is None or not path.is_file():
        return 0
    try:
        return int(path.stat().st_size * FILE_HEADROOM)
    except OSError:
        return 0


if __name__ == "__main__":
    role = sys.argv[1] if len(sys.argv) > 1 else "executor"
    file_path = sys.argv[2] if len(sys.argv) > 2 else None
    out = use_gpu(role, file_path)
    print(out)
