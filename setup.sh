#!/usr/bin/env bash
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "USB chat setup"
echo "Needs Python 3.11 or newer. Will not replace or upgrade the system interpreter."
echo

FOUND="none"
PY=""

try_py() {
  local cmd="$1"
  local ver
  ver="$($cmd -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>/dev/null)" || return 0
  if [[ "$FOUND" == "none" ]]; then
    FOUND="$ver"
  fi
  if $cmd -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; then
    if [[ -z "$PY" ]]; then
      PY="$cmd"
    fi
  fi
}

try_py python3.13
try_py python3.12
try_py python3.11
try_py python3
try_py python
try_py python2

dialog() {
  local msg="$1"
  echo "$msg" >&2
  if command -v zenity >/dev/null 2>&1; then
    zenity --error --title="USB chat setup" --width=420 --text="$msg" || true
  elif command -v kdialog >/dev/null 2>&1; then
    kdialog --title "USB chat setup" --error "$msg" || true
  fi
}

if [[ -n "$PY" ]]; then
  echo "Using compatible interpreter: $PY"
  exec "$PY" "$HERE/setup.py"
fi

if [[ "$FOUND" == "none" ]]; then
  dialog "USB chat needs Python 3.11 or newer to run. This PC has no Python on PATH. Setup will not install or replace a system Python. Install Python 3.11 or newer alongside any existing projects, then run setup.sh again."
else
  dialog "USB chat needs Python 3.11 or newer to run. This PC has Python ${FOUND}. That interpreter will not be replaced or upgraded, so other projects keep using it. Install Python 3.11 or newer alongside, then run setup.sh again."
fi
exit 1
