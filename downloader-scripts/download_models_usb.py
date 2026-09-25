"""Download the USB committee GGUFs (MODELS_DIR) and write models.json on the stick.

Q4_K_M only (~40GB). Leaves room on a 64GB stick for later image weights.
Do not download whole repos.

Usage (from the repo root):
  .\\.venv\\Scripts\\python.exe downloader-scripts\\download_models_usb.py --path E:\\ --login

Gated: Llama 3.1 8B, Llama 3.2 3B, Gemma 2 9B. Accept those licenses, then --login.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, login

# Preferred role order is the picker order (first tagged file is the lead).
USB_ROLES: dict[str, dict] = {
    "router": {
        "use": ["route"],
        "license": "apache-2.0",
        "primary": {
            "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
            "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "1.1GB",
        },
        "backup": {
            "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "2.0GB",
        },
    },
    "executor": {
        "use": ["code"],
        "license": "apache-2.0",
        "primary": {
            "repo_id": "Qwen/Qwen2.5-Coder-14B-Instruct-GGUF",
            "filename": "qwen2.5-coder-14b-instruct-q4_k_m.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "9.0GB",
        },
        "backup": {
            "repo_id": "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
            "filename": "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "2.0GB",
        },
    },
    "builder_coder": {
        "use": ["code"],
        "license": "apache-2.0",
        "primary": {
            "repo_id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
            "filename": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "4.7GB",
        },
        "backup": {
            "repo_id": "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
            "filename": "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "2.0GB",
        },
    },
    "builder_deepseek": {
        "use": ["code"],
        "license": "other",
        "primary": {
            "repo_id": "TheBloke/deepseek-coder-6.7B-instruct-GGUF",
            "filename": "deepseek-coder-6.7b-instruct.Q4_K_M.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "4.1GB",
        },
        "backup": {
            "repo_id": "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
            "filename": "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "2.0GB",
        },
    },
    "builder_yi": {
        "use": ["code"],
        "license": "apache-2.0",
        "primary": {
            "repo_id": "bartowski/Yi-Coder-9B-Chat-GGUF",
            "filename": "Yi-Coder-9B-Chat-Q4_K_M.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "5.3GB",
        },
        "backup": {
            "repo_id": "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
            "filename": "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "2.0GB",
        },
    },
    "builder_qwen": {
        "use": ["plan", "language"],
        "license": "apache-2.0",
        "primary": {
            "repo_id": "bartowski/Qwen_Qwen3-14B-GGUF",
            "filename": "Qwen_Qwen3-14B-Q4_K_M.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "9.0GB",
        },
        "backup": {
            "repo_id": "Qwen/Qwen2.5-3B-Instruct-GGUF",
            "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "2.0GB",
        },
    },
    "builder_llama": {
        "use": ["plan", "language"],
        "license": "llama3.1",
        "primary": {
            "repo_id": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
            "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "4.9GB",
        },
        "backup": {
            "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "2.0GB",
        },
    },
    "builder_gemma": {
        "use": ["plan", "language"],
        "license": "gemma",
        "primary": {
            "repo_id": "bartowski/gemma-2-9b-it-GGUF",
            "filename": "gemma-2-9b-it-Q4_K_M.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "5.8GB",
        },
        "backup": {
            "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
            "revision": "main",
            "sha256": "",
            "bytes": 0,
            "approx": "2.0GB",
        },
    },
}


def download_slots() -> list[dict[str, str]]:
    """Unique GGUFs to fetch. Router backup is the second route model; other backups stay on the SSD."""
    seen: set[str] = set()
    items: list[dict[str, str]] = []
    for role, spec in USB_ROLES.items():
        keys = ("primary", "backup") if role == "router" else ("primary",)
        for key in keys:
            slot = spec[key]
            name = slot["filename"]
            if name in seen:
                continue
            seen.add(name)
            items.append(
                {
                    "role": role,
                    "slot": key,
                    "repo_id": slot["repo_id"],
                    "filename": name,
                    "approx": slot.get("approx") or "",
                }
            )
    return items


def write_usb_manifest(dest: Path) -> Path:
    """Write MODELS_DIR/models.json with on-disk sizes. Safe to rerun."""
    dest = dest.resolve()
    roles: dict[str, dict] = {}
    for name, spec in USB_ROLES.items():
        entry = {"use": list(spec["use"]), "license": spec.get("license") or ""}
        for key in ("primary", "backup"):
            slot = dict(spec[key])
            slot.pop("approx", None)
            path = dest / slot["filename"]
            if path.is_file():
                slot["bytes"] = path.stat().st_size
            entry[key] = slot
        roles[name] = entry
    target = dest / "models.json"
    target.write_text(json.dumps({"format_version": 2, "roles": roles}, indent=2) + "\n", encoding="utf-8")
    return target


def download_all(dest: Path, do_login: bool) -> int:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    if do_login:
        login()
    failed = 0
    for item in download_slots():
        print(f"[{item['role']}/{item['slot']}] ~{item['approx']}  {item['repo_id']} / {item['filename']}")
        try:
            path = hf_hub_download(
                repo_id=item["repo_id"],
                filename=item["filename"],
                local_dir=str(dest),
            )
            final = dest / item["filename"]
            src = Path(path)
            if src.is_file() and src.resolve() != final.resolve():
                shutil.copy2(src, final)
            print(f"  -> {final}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL: {exc}", file=sys.stderr)
            print("  Gated? Accept the license on the repo page, then rerun with --login.")
    manifest = write_usb_manifest(dest)
    print(f"wrote {manifest}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Download USB/committee GGUFs from Hugging Face.")
    parser.add_argument("--path", required=True, help="Destination folder on the USB (MODELS_DIR).")
    parser.add_argument("--login", action="store_true", help="Interactive Hugging Face login (token).")
    args = parser.parse_args()
    return download_all(Path(args.path), args.login)


if __name__ == "__main__":
    sys.exit(main())
