# Changelog

Newest first. Hand-written. Update when a set of files is copied onto the USB, not on every save.

## 1.0.4 — 2026-09-26

Setup popup now says the **llama-cpp-python** library is missing when that install fails.

## 1.0.3 — 2026-09-26

Setup installs `llama-cpp-python` from the official CPU wheel index so Windows does not try to compile it (that failed without Visual Studio / nmake).

## 1.0.2 — 2026-09-26

Setup leaves the system interpreter alone. Python 3.11+ builds or updates a host-only venv; older or missing Python shows a dialog (need 3.11+, found YY). Chat launchers start that venv.

## 1.0.1 — 2026-09-26

Backup layout matches the USB `chat\` folder: scripts sit next to this README. Dropped the nested `chat\` directory and the factory `.env.example`.

## 1.0.0 — 2026-09-26

First USB-only backup of the standalone chat.

- Chat UI, RAM-fit model picker, document attach, Reply/quote
- Session JSONL logs, 30-day purge, scroll-back as older context
- Confirmed `notes.md`, in-memory Save/Print PDF
- Host setup scripts (no venv on the stick)
