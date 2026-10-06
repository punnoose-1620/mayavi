"""Download small backup GGUFs into BACKUP_MODELS_DIR (laptop SSD).

Usage:
  pip install -U huggingface_hub
  python download_models_local.py --path D:\\backup-models
  python download_models_local.py --path D:\\backup-models --login

Gated models (Llama): accept the license on the Hugging Face repo page, then login.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, login

# Router + thinner stand-ins so the project runs without the USB (~7GB total).
MODELS: list[dict[str, str]] = [
    {
        "role": "router",
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
    },
    {
        "role": "executor",
        "repo_id": "Qwen/Qwen2.5-Coder-3B-Instruct-GGUF",
        "filename": "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
    },
    {
        "role": "builder_qwen",
        "repo_id": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
    },
    {
        "role": "builder_llama",
        "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    },
]


def download_all(dest: Path, do_login: bool) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    if do_login:
        login()
    failed = 0
    for item in MODELS:
        print(f"[{item['role']}] {item['repo_id']} / {item['filename']}", flush=True)
        try:
            path = hf_hub_download(
                repo_id=item["repo_id"],
                filename=item["filename"],
                local_dir=str(dest),
            )
            print(f"  -> {path}", flush=True)
        except Exception as exc:
            failed += 1
            print(f"  FAIL: {exc}", file=sys.stderr, flush=True)
            print(
                "  If this is gated, open the repo in a browser, accept the license, then --login.",
                file=sys.stderr,
                flush=True,
            )
    print(f"DONE failed={failed}", flush=True)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Download small local/backup GGUFs from Hugging Face.")
    parser.add_argument("--path", required=True, help="Destination folder (BACKUP_MODELS_DIR).")
    parser.add_argument("--login", action="store_true", help="Interactive Hugging Face login (token).")
    args = parser.parse_args()
    return download_all(Path(args.path), args.login)


if __name__ == "__main__":
    sys.exit(main())
