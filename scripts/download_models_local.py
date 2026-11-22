"""Download the USB chat GGUFs into one folder (the stick root).

Usage:
  pip install -U huggingface_hub
  python download_models_local.py --path E:\\
  python download_models_local.py --path E:\\ --login

A file already at the expected size is left in place. Gated models (Llama, Gemma)
need the license accepted on the Hugging Face repo, then --login, on a fresh stick.

Qwen3 GGUFs ship with thinking on. This chat has no thinking switch, so those
two files can ramble until thinking is turned off in the app.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download, login

# Same-size chat set. Q4_K_M except the 7B, which is Q4_K_S so it stays near 4.5 GB.
# Q3 is omitted: that quant raises hallucinations.
MODELS: list[dict[str, str | int]] = [
    {
        "role": "1.5b",
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "bytes": 1117320736,
    },
    {
        "role": "3b",
        "repo_id": "bartowski/Qwen2.5-3B-Instruct-GGUF",
        "filename": "Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        "bytes": 1929903264,
    },
    {
        "role": "7b",
        "repo_id": "bartowski/Qwen2.5-7B-Instruct-GGUF",
        "filename": "Qwen2.5-7B-Instruct-Q4_K_S.gguf",
        "bytes": 4457769664,
    },
    {
        "role": "8b",
        "repo_id": "bartowski/Meta-Llama-3.1-8B-Instruct-GGUF",
        "filename": "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf",
        "bytes": 4920739232,
    },
    {
        "role": "8b-qwen3",
        "repo_id": "Qwen/Qwen3-8B-GGUF",
        "filename": "Qwen3-8B-Q4_K_M.gguf",
        "bytes": 5027783488,
    },
    {
        "role": "9b",
        "repo_id": "bartowski/gemma-2-9b-it-GGUF",
        "filename": "gemma-2-9b-it-Q4_K_M.gguf",
        "bytes": 5761057728,
    },
    {
        "role": "14b",
        "repo_id": "bartowski/Qwen2.5-14B-Instruct-GGUF",
        "filename": "Qwen2.5-14B-Instruct-Q4_K_M.gguf",
        "bytes": 8988110976,
    },
    {
        "role": "14b-qwen3",
        "repo_id": "bartowski/Qwen_Qwen3-14B-GGUF",
        "filename": "Qwen_Qwen3-14B-Q4_K_M.gguf",
        "bytes": 9001753632,
    },
]


def download_all(dest: Path, do_login: bool) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    if do_login:
        login()
    failed = 0
    for item in MODELS:
        filename = str(item["filename"])
        expected = int(item["bytes"])
        target = dest / filename
        if target.is_file() and target.stat().st_size == expected:
            print(f"[{item['role']}] skip {filename} ({expected} bytes)", flush=True)
            continue
        print(f"[{item['role']}] {item['repo_id']} / {filename}", flush=True)
        try:
            path = hf_hub_download(
                repo_id=str(item["repo_id"]),
                filename=filename,
                local_dir=str(dest),
            )
            got = Path(path).stat().st_size
            if got != expected:
                failed += 1
                print(f"  FAIL: {path} is {got} bytes, expected {expected}", file=sys.stderr, flush=True)
                continue
            print(f"  -> {path} ({got} bytes)", flush=True)
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
    parser = argparse.ArgumentParser(description="Download the USB chat GGUFs from Hugging Face.")
    parser.add_argument("--path", required=True, help="Destination folder (USB root).")
    parser.add_argument("--login", action="store_true", help="Interactive Hugging Face login (token).")
    args = parser.parse_args()
    return download_all(Path(args.path), args.login)


if __name__ == "__main__":
    sys.exit(main())
