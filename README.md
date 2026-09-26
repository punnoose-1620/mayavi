# USB chat

Backup of the **standalone USB chat** (`chat\` on the stick). This git branch is not a runnable app. Edit the files here, then copy them onto the USB when it is plugged in. If the stick is lost, copy this branch onto a new drive next to the GGUFs.

It is **not** the id10t committee. The stick does not need a Python venv.

See [`CHANGELOG.md`](CHANGELOG.md) for what landed in each version. Features below are what **1.0.11** can do.

## Features

- One GGUF at a time. The picker lists only files that fit **free RAM ≥ file size × 1.2 + 2 GB**, largest first, labeled like `Qwen2.5 Coder 14B (8.4 GB)`.
- Chat window: labeled History (empty-state hint) and Message (placeholder + Send on the right).
- Quote a turn with the ↩ control on each **You** / **Model** line (hover: *Reply to this message*). **Clear quote** and **Replying to:** appear only while a quote is pending.
- Read-only attach: `pdf`, `docx`, `xlsx`, `txt`, `md`, `csv`. History shows a document icon and the full path (older logs: icon and the stored name).
- Session logs in `logs/` (JSONL with prompt, optional `shown` / `attached`, reply, token counts). Scroll the transcript to the top to load an older log as earlier llama.cpp turns. When none remain, History says nothing is stored before this.
- Logs older than 30 days are deleted by the `YYYY-MM-DD_` prefix in the filename.
- `notes.md` is included (first 4000 characters). The model cannot write it; you confirm in **Notes…**.
- **Save PDF** / **Print** build the transcript in memory. Nothing is written unless you pick a save path or the OS print spooler needs a temp file.
- Host `setup.bat` / `setup.sh`: require **Python 3.11+**. Compatible interpreters only seed a **private host venv** (`%LOCALAPPDATA%\usb-chat\venv` or `~/.local/share/usb-chat/venv`); installs `llama-cpp-python` (CPU wheel) and **`pypdf`**. A failed install names the missing library in the popup. System Python is never replaced. If the PC has no 3.11+ (or only 2.7 / 3.9), a dialog names the version we need and the version we found. `chat.bat` / `chat.sh` boot that venv.
- Windows first; same scripts on Ubuntu.
- No committee, search, mail, or factory.

GPU offload is off unless you set `USB_CHAT_N_GPU_LAYERS` (or a numeric `N_GPU_LAYERS`) on the host.

## Layout on the USB

GGUFs stay at the stick root. This branch is the contents of `chat\`.

```
<USB>\
  *.gguf
  notes.md             (created on the stick; do not put in git)
  logs\
    YYYY-MM-DD_HHMMSS.log
  chat\                ← copy the files from this branch here
    README.md
    CHANGELOG.md
    chat.py
    usbchat.py
    setup.py
    chat.bat
    chat.sh
    setup.bat
    setup.sh
    bin\               (optional llama-cli; not required in git)
```

`models.json` on the stick is unused by this chat (committee leftover). `logs\` and `notes.md` stay on the USB only.

## Copy onto the stick

Overwrite `chat\` on the stick with the files from this branch root. Do not copy `.venv`, `logs\`, `notes.md`, or `*.gguf` into git.

On a **new** stick: put the GGUFs at the USB root, copy this backup into `chat\`, then run setup on the host.

## What the host needs (runtime, on the USB)

- Windows or Ubuntu
- Python **3.11 or newer** already on the machine (install *alongside* an older system Python; setup will not upgrade 3.9 / 2.7)
- `llama-cpp-python` in the host venv, **or** `llama-cli` in `chat/bin/`

From `chat\` on the stick:

```powershell
.\setup.bat
.\chat.bat
```

```bash
chmod +x setup.sh chat.sh
./setup.sh
./chat.sh
```

Optional: `--models D:\` if the GGUFs are not next to `chat\` and not on `E:\`…`P:\`.
