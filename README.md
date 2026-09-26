# USB chat

Backup of the **standalone USB chat** (`chat\` on the stick). This git branch is not a runnable app. Edit the files here, then copy them onto the USB when it is plugged in. If the stick is lost, copy this branch onto a new drive next to the GGUFs.

It is **not** the id10t committee. The stick does not need a Python venv.

See [`CHANGELOG.md`](CHANGELOG.md) for what landed in each version. Features below are what **1.1.3** can do.

## Features

- One GGUF at a time. The picker lists only files that fit **free RAM ≥ file size × 1.2 + 2 GB**, largest first, labeled like `Qwen2.5 Coder 14B (8.4 GB)`. If the file’s chat template rejects a system role, that text is folded into the first user message.
- Chat window: labeled History (empty-state hint) and Message (placeholder + Send on the right). While the model is working (including a long Web Search), the box is locked and Send becomes a spinner; Stop stays on.
- Quote a turn with the ↩ control on each **You** / **Model** line (hover: *Reply to this message*). **Clear quote** and **Replying to:** appear only while a quote is pending.
- Read-only attach: `pdf`, `docx`, `xlsx`, `txt`, `md`, `csv`. History shows a document icon and the full path (older logs: icon and the stored name).
- Session logs in `logs/` (JSONL with prompt, optional `shown` / `attached`, reply, token counts, and Web Search fields when used). Scroll the transcript to the top to load an older log as earlier llama.cpp turns. When none remain, History says nothing is stored before this.
- Logs older than 30 days are deleted by the `YYYY-MM-DD_` prefix in the filename (session `.log` and `web_*.jsonl`).
- `notes.md` is included (first 4000 characters). The model cannot write it; you confirm in **Notes…**.
- **Save PDF** / **Print** build the transcript in memory. Nothing is written unless you pick a save path or the OS print spooler needs a temp file.
- Optional **Web Search** — see below.
- Host `setup.bat` / `setup.sh`: require **Python 3.11+**. Compatible interpreters only seed a **private host venv** (`%LOCALAPPDATA%\usb-chat\venv` or `~/.local/share/usb-chat/venv`); installs `llama-cpp-python` (CPU wheel), **`pypdf`**, **`requests`**, and **`beautifulsoup4`**. A failed install names the missing library in the popup. System Python is never replaced. If the PC has no 3.11+ (or only 2.7 / 3.9), a dialog names the version we need and the version we found. `chat.bat` / `chat.sh` boot that venv.
- Windows first; same scripts on Ubuntu.
- No committee, mail, or factory. No SerpAPI / ScraperAPI keys.

## Web Search

Shown above Message only when the host can reach the internet. The toggle stays on until you turn it off. Hover the asterisk: it is slow and uses extra model passes; use it only when you need live web.

With the toggle on, **Send** runs this local path (`search.py`, no paid search API):

1. The model writes a Google query from the latest request.
2. `search_google` fetches `google.com/search` HTML and strips the cookie/consent chrome.
3. The model names CSS classes/ids to **remove** or **keep** (a keep pair is class and id on the same tag).
4. The model picks at most **3** http(s) URLs (Google wrapper links are unwrapped; google.com chrome is skipped). If it names none, the scrape falls back to links found in the HTML.
5. Each page is fetched, ads/search boxes stripped, then the same remove-or-keep pass.
6. The model answers from those excerpts. **Only that last reply is shown in History.**

If Google HTML or page text will not fit the local context window (default **4096** tokens, minus a **512**-token reply), it is split and processed in parts. Status can show `cleaning results (2/5)` or `summarizing page 1, part 2/3`. Chunk notes stay out of History. If a fetch is blocked or empty, the turn answers without the web and says so in the status line.

**Stop** cancels between steps. Query, raw HTML sizes, class/id specs, URLs, and summaries go to `logs/web_YYYY-MM-DD_HHMMSS.jsonl`, not the transcript. Session turns may store `web_search`, `web_query`, `web_urls`, and `web_log`.

Needs `requests` and `beautifulsoup4` in the host venv (setup installs them). Google HTML can still consent-wall or block; that is expected for a raw scrape.

GPU offload is off unless you set `USB_CHAT_N_GPU_LAYERS` (or a numeric `N_GPU_LAYERS`) on the host.

## Layout on the USB

GGUFs stay at the stick root. This branch is the contents of `chat\`.

```
<USB>\
  *.gguf
  notes.md             (created on the stick; do not put in git)
  logs\
    YYYY-MM-DD_HHMMSS.log
    web_YYYY-MM-DD_HHMMSS.jsonl   (Web Search side log; not History)
  chat\                ← copy the files from this branch here
    README.md
    CHANGELOG.md
    chat.py
    usbchat.py
    search.py
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
- `requests` and `beautifulsoup4` in that venv for Web Search (setup installs them)

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
