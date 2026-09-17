"""Download full committee GGUFs onto a USB (MODELS_DIR).

Sized for a ~32GB USB 3.2 stick: Q4_K_M only (~26GB). Do not download whole repos.

Usage:
  pip install -U huggingface_hub
  python download_models_usb.py --path E:\\models
  python download_models_usb.py --path E:\\models --login

Llama 3.1 and Gemma 2 are gated: accept licenses on Hugging Face, then --login.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, login

# ~26GB Q4_K_M. Leaves a few GB free on a 32GB stick (format overhead).
MODELS: list[dict[str, str]] = [
    {
        "role": "router",
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "approx": "1.1GB",
    },
    {
        "role": "executor",
        "repo_id": "Qwen/Qwen2.5-Coder-7B-Instruct-GGUF",
        "filename": "qwen2.5-coder-7b-instruct-q4_k_m.gguf",
        "approx": "4.7GB",
    },
    {
        "role": "builder_llama",
        "repo_id": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "approx": "4.9GB",
    },
    {
        "role": "builder_qwen",
        "repo_id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "approx": "4.7GB",
    },
    {
        "role": "builder_mistral",
        "repo_id": "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
        "filename": "Mistral-7B-Instruct-v0.3-Q4_K_M.gguf",
        "approx": "4.4GB",
    },
    {
        "role": "builder_gemma",
        "repo_id": "bartowski/gemma-2-9b-it-GGUF",
        "filename": "gemma-2-9b-it-Q4_K_M.gguf",
        "approx": "5.8GB",
    },
]


def download_all(dest: Path, do_login: bool) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    if do_login:
        login()
    failed = 0
    for item in MODELS:
        print(f"[{item['role']}] ~{item['approx']}  {item['repo_id']} / {item['filename']}")
        try:
            path = hf_hub_download(
                repo_id=item["repo_id"],
                filename=item["filename"],
                local_dir=str(dest),
            )
            print(f"  -> {path}")
        except Exception as exc:
            failed += 1
            print(f"  FAIL: {exc}", file=sys.stderr)
            print("  Gated? Accept the license on the repo page, then rerun with --login.")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Download USB/committee GGUFs from Hugging Face.")
    parser.add_argument("--path", required=True, help="Destination folder on the USB (MODELS_DIR).")
    parser.add_argument("--login", action="store_true", help="Interactive Hugging Face login (token).")
    args = parser.parse_args()
    return download_all(Path(args.path), args.login)


if __name__ == "__main__":
    sys.exit(main())
