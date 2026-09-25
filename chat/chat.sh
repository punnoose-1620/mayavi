#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"
if [[ -x "$HERE/../.venv/bin/python" ]]; then
  exec "$HERE/../.venv/bin/python" "$HERE/chat.py" "$@"
fi
exec python3 "$HERE/chat.py" "$@"
