#!/usr/bin/env bash
# Setup only: venv, dependencies, .env. No models, no committee logic, no secrets.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$repo"

MIN_MAJOR=3
MIN_MINOR=11

find_python() {
    for candidate in python3.13 python3.12 python3.11 python3 python; do
        command -v "$candidate" >/dev/null 2>&1 || continue
        if "$candidate" -c "import sys; raise SystemExit(0 if sys.version_info >= ($MIN_MAJOR, $MIN_MINOR) else 1)" 2>/dev/null; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

if ! PY="$(find_python)"; then
    echo "Python ${MIN_MAJOR}.${MIN_MINOR} or newer is required and was not found." >&2
    echo "On Ubuntu: sudo apt install python3.11 python3.11-venv" >&2
    exit 1
fi
echo "Using $("$PY" --version)"

if [ ! -d .venv ]; then
    echo "Creating .venv"
    "$PY" -m venv .venv
else
    echo ".venv already exists; reusing it"
fi

venv_py=".venv/bin/python"
if [ ! -x "$venv_py" ]; then
    echo "The virtual environment is incomplete: $venv_py is missing." >&2
    echo "On Ubuntu you may need: sudo apt install python3-venv" >&2
    exit 1
fi

echo "Installing requirements.txt"
"$venv_py" -m pip install --upgrade pip
"$venv_py" -m pip install -r requirements.txt

echo "Installing requirements-inference.txt (llama-cpp-python)"
if ! "$venv_py" -m pip install -r requirements-inference.txt; then
    echo "WARNING: the inference wheel did not install. The factory still runs with --no-model." >&2
fi

if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env from .env.example"
else
    echo ".env already exists; left untouched"
fi

cat <<'EOF'

Edit .env before the first real run:
  HF_TOKEN            Hugging Face *Read* token (needed for gated Llama/Gemma)
  BACKUP_MODELS_DIR   where the small GGUF set lives, e.g. models
  MODELS_DIR          the USB library, if you have one
  ID10T_WORKSPACE     read root for source documents (default input)
  ID10T_OUTPUTS       write root for results (default outputs)
  GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / MS_CLIENT_ID   only for mail and calendar

Models are not downloaded by this script. Accept the gated licenses on Hugging Face first
(see README > Gated models), then run:
  ./.venv/bin/python downloader-scripts/download_models_local.py --path models

Then run it:
  source .venv/bin/activate
  python main.py --no-model "hi"     # no weights needed
  python main.py "hi"                # loads the router GGUF
EOF
