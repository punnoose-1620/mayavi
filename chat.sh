#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [[ -n "${XDG_DATA_HOME:-}" ]]; then
  VPY="$XDG_DATA_HOME/usb-chat/venv/bin/python"
else
  VPY="$HOME/.local/share/usb-chat/venv/bin/python"
fi

if [[ -x "$VPY" ]]; then
  exec "$VPY" "$HERE/scripts/chat.py" "$@"
fi

MSG="USB chat is not set up on this PC. Run setup.sh first. It will use Python 3.11 or newer in a private host venv and will not change the system Python."
echo "$MSG" >&2
if command -v zenity >/dev/null 2>&1; then
  zenity --error --title="USB chat" --width=420 --text="$MSG" || true
elif command -v kdialog >/dev/null 2>&1; then
  kdialog --title "USB chat" --error "$MSG" || true
fi
exit 1
