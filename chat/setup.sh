#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "USB chat setup"
echo "This PC needs Python 3.11+ and llama-cpp-python, or llama-cli in chat/bin/"
echo "This script will not create a venv on the USB stick."
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 was not found."
  echo "On Ubuntu: sudo apt install python3 python3-pip python3-venv"
  echo "Then run ./setup.sh again."
  echo "This script cannot install Python for you."
  exit 1
fi

if ! python3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"; then
  echo "This python3 is too old. Need 3.11+."
  exit 1
fi

exec python3 "$HERE/setup.py"
