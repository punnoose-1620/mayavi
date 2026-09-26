# Changelog

Newest first. Hand-written. Update when a set of files is copied onto the USB, not on every save.

## 1.0.11 — 2026-09-26

The window is vertically scrollable when it is smaller than the full layout, so the message box padding still works outside fullscreen.

## 1.0.10 — 2026-09-26

Looser page gutter (16px) and more space under the message box so the compose area is not flush against the window edge or the buttons.

## 1.0.9 — 2026-09-26

When no older session log remains, History shows a one-time line that nothing is stored before this (or older logs were deleted).

## 1.0.8 — 2026-09-26

Attach lines in history and logs use a document icon plus the **full path**. Older logs that only stored a name show the icon and that name.

## 1.0.7 — 2026-09-26

↩ shows *Reply to this message* on hover. Logs store the attach note (`shown` / `attached`); reloaded history paints `[attached name]` again.

## 1.0.6 — 2026-09-26

History and Message are labeled separately. Empty history and a type-here hint. Send sits on the right of the box. Each You/Model line is bold with a user/bot mark and a ↩ control to quote that message. Clear quote is hidden until a reply is pending.

## 1.0.5 — 2026-09-26

Setup also installs **pypdf** so attached PDFs can be read. If a library fails to install, the popup names that library (llama-cpp-python or pypdf) and says it is missing.

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
