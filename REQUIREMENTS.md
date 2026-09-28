# USB chat requirements

What this PC and this stick need. Setup does not replace system Python.

A visual copy is `REQUIREMENTS.pdf` in the same folder. Chat and setup do not open it.

## Hard minimum

- Windows or Ubuntu
- Python **3.11 or newer** already on PATH (install *alongside* 3.9 / 2.7; setup will not upgrade them)
- A **writable** USB stick: setup creates `logs\` and `outputs\` next to the GGUFs (not inside `chat\`)
- `llama-cpp-python` in the host venv, **or** `llama-cli` in `chat/bin/`
- Host venv libraries (setup installs these): `pypdf` (attached PDFs), `requests` and `beautifulsoup4` (Web Search)

If Python is missing or older than 3.11, setup names the version it found and stops. If a library cannot be installed, setup names that library. System Python is never changed.

Host venv location:

- Windows: `%LOCALAPPDATA%\usb-chat\venv`
- Ubuntu: `~/.local/share/usb-chat/venv` (or `$XDG_DATA_HOME/usb-chat/venv`)

## Optional

- **git** on PATH — only if you turn on **Coding** and paste a public `https://github.com/owner/repo` URL. Chat still runs without git.
- Internet — only for **Web Search**. Google HTML can still block; that is expected.
- GPU offload — off unless you set `USB_CHAT_N_GPU_LAYERS` (or a numeric `N_GPU_LAYERS`) on the host.

## Not required

- No SerpAPI / ScraperAPI keys
- No mail accounts
- No second GGUF
- `notes.md` is created when you save notes, not by setup

## Run setup then chat

From `chat\` on the stick:

Windows: `setup.bat` then `chat.bat`

Ubuntu: `./setup.sh` then `./chat.sh`
