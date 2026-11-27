# Project Mayavi

![Display Image](assets/displayImage.jpg)


Local multi-agent runtime that routes a user request into a **small**, **medium**, or **large** session, then runs local GGUF models one at a time with a locked-down tool set.

It is designed to run on a single machine (overnight / sequential). It does **not** keep five models in RAM. Weights come from Hugging Face as GGUF files. Inference uses llama.cpp (`llama-cpp-python`).

Release history lives in [`documentation/CHANGELOG.md`](documentation/CHANGELOG.md), newest version **first**. The current feature set is **1.3.3**.

## Documentation

| Doc | What it is |
| --- | --- |
| [`documentation/CHANGELOG.md`](documentation/CHANGELOG.md) | Release history, newest first |
| [`documentation/Hardware Requirements.md`](documentation/Hardware%20Requirements.md) | Ubuntu/Windows floors, RAM, GPU, disk |
| [`documentation/Server Hardware.md`](documentation/Server%20Hardware.md) | Headless box cart (CPU, GPU, disks) |
| [`documentation/Multi-Phase Testing (Testing Plan).md`](documentation/Multi-Phase%20Testing%20(Testing%20Plan).md) | Multi-phase eval plan |
| [`documentation/Multi-Phase Testing (Results).md`](documentation/Multi-Phase%20Testing%20(Results).md) | Multi-phase eval results |
| [`documentation/Memory Board Continuity (Results).md`](documentation/Memory%20Board%20Continuity%20(Results).md) | Memory-board continuity results |
| [`documentation/Quality Test Results.md`](documentation/Quality%20Test%20Results.md) | Quality-test results |

## What it does

1. A **router** inspects the prompt and emits effort/stakes fields (not a tier name). It does not answer the user, does not call tools, and does not decide whether the job is a coding task.
2. The script maps those fields to `small` | `medium` | `large`. The operator’s **coding** flag (CLI `--code` / UI checkbox) selects the sequential coding committee. High stakes without that flag selects the review committee. Operator **web** (`--web` / UI checkbox) is the only live-search switch; it does not pick a committee and does not jump the job to medium.
3. A **factory** (`executor.py`) creates agents, optional blackboard, optional sandbox, and (if requested) mail/calendar OAuth. If operator web is on, it searches first (CSE, then SerpAPI, then ScraperAPI) and pins a page digest. File tools are **gated** from the router counts (`file_ops=0` hides writers/readers). Live web tools are **gated by the operator Web control**, not by `web_ops`.
4. Workers prefer a direct `{"final": "..."}`. They only get a file or mail tool if the router counted that family. Live URL tools exist only when the operator marked **web**.
5. The CLI prints **one** user-facing answer (Prompt / Response / Meta). Tokens are not streamed. On medium/large, that answer comes from blackboard `vote` then `draft`. Factory `rules`, sandbox `debug`, and bare `ship` / `reject` / `saved` / `shipped` pointers are never the answer. After a large run ships, the answer is a summary of the keep folder; artifacts land in `outputs/<YYYY-MM-DD>_<intent-slug>/`. If they do not ship, the factory says so (and lists jail files / stdout when it has them) instead of the word `saved`. If the model only emits `final`, the script copies it onto the board.
6. A daily binary **audit log** records who spawned and which exported functions ran. It does not store transcripts, file bodies, mail bodies, or tokens.

## Tiers

The router never outputs `small` / `medium` / `large`. Mapping is:

| Condition | Tier / shape |
| --- | --- |
| Operator **coding** is on | **large** sequential coding committee (even if stakes are high) |
| else `stakes` is `high` | **large** review committee (builders + executor) |
| else `file_ops` is `3+` | **medium** |
| else | **small** |

`mail_cal` does not pick the tier. Coding tasks force `mail_cal` to `off`. The router does not emit `needs_code_exec`; that flag is set from the operator coding control. The operator **web** checkbox / `--web` is the only way to run live search (CSE, then SerpAPI, then ScraperAPI). It does **not** jump a job to medium. `web_ops` from the router is forced to `0` unless that control is on.

If the router is **unsure**, fields default **cheap**: `stakes=low`, `file_ops=0`, `web_ops=0` → **small** unless the operator marked coding. The factory then **clamps** `stakes=high` unless the prompt clearly matches legal/official/medical/financial (or similar). Greetings, chat, how-to, HTML pages, and summaries stay low even if the 1.5B router marked high. A write counts toward `file_ops` only if the user asked to create or save a file. Summarizing or reading code already under `outputs/` is a file read (`file_ops` at least 1), not a new sandbox build. Missing or garbage router JSON uses those same cheap defaults (it does **not** round up to large).

| Tier | Agents | Blackboard | Sandbox | Typical use |
| --- | --- | --- | --- | --- |
| Small | 1 drafter (code-tagged GGUF when the prompt is HTML/JS/snippet work) | no | no | cheap Q&A, light file/web, a flashy HTML page (untested unless Coding is on) |
| Medium | drafter + 2 checkers | yes + durable thread | no | more file/web work, review |
| Large (coding) | sequential committee (manager, coder, tester, critique, evaluator; documenter after commit) | sectioned board | **always** | operator marked coding |
| Large (review) | executor + builders | blackboard ship vote | **no** | high stakes, not coding |

Large **coding** always creates a sandbox and a keep folder, and injects `src/coding/rules.md`. Phase 0 is planning only. Then each round is coder → tester → critique → evaluator → manager → vote. ≥4/5 yes commits; push every 5 commits if a valid GitHub URL was given. Tester executes; coder writes. If the USB library is present, `use` tags pick `manage` / `code` / `test` / `critique` / `evaluate` / `document`. If not, thinner backups (router / 3B) are used when RAM is short.

Large **review** (high stakes, coding off) uses the older committee: builders and the executor write `write_doc` / PDF / JSON into the keep folder. No sandbox, no git tools. A majority blackboard **ship** vote records that the keep folder shipped.

Without the operator **coding** flag, a snippet request still gets the code in the answer and a note that it is not tested. A request to run, test, or use the sandbox says that is unavailable until Coding / `--code` is selected.

## Requirements

Machine-by-machine floors (Ubuntu vs Windows, headless vs desktop, named NVIDIA and Ryzen SKUs) are in [`documentation/Hardware Requirements.md`](documentation/Hardware%20Requirements.md). A sample headless cart is in [`documentation/Server Hardware.md`](documentation/Server%20Hardware.md).

- Python 3.11+
- Enough disk for GGUFs (~7GB backup set, or ~40GB full USB set on a 64GB stick)
- Enough RAM to load **one** GGUF at a time (file size × 1.2, plus a 2GB reserve)
- Hugging Face account + **Read** token (needed for gated Llama/Gemma)
- Optional: GPU via `N_GPU_LAYERS` (`auto` = detect CUDA wheel + dedicated VRAM vs this GGUF, working agents only; `0` = CPU)

Install with the setup script for your platform. It checks the Python version, creates `.venv`, installs both requirement files, copies `.env.example` to `.env` if you have no `.env` yet, and prints what to edit. It does **not** download models.

```powershell
.\scripts\install.ps1
```

```bash
./scripts/install.sh
```

Or do it by hand:

```powershell
python -m pip install -r requirements.txt -r requirements-inference.txt
```

## Quick start

```powershell
copy .env.example .env
# edit .env: HF_TOKEN, BACKUP_MODELS_DIR=models, folders as needed
```

Accept gated licenses in the browser (see [Gated models](#gated-models-hugging-face)), then download the small backup set into `models/`:

```powershell
$env:HF_TOKEN = (Get-Content .env | Where-Object { $_ -like "HF_TOKEN=*" }).Split("=",2)[1]
python src/downloader-scripts/download_models_local.py --path "d:\Documents\Github Repositories\mayavi\models"
```

Smoke-test the factory without loading weights:

```powershell
python main.py --no-model "How do I fix this issue on my electric scooter?"
python -m pytest
```

`--no-model` and `pytest` use **stubs**. They will not print a real 3B chat reply. `pytest` also prints each test’s captured call/result (`-s` is on by default); most of those 157 tests are gates (path deny, SSRF, mail policy), not conversations.

The USB GGUF stick can also run a **standalone chat** (one model, no committee) from [`usb-chat/`](usb-chat/README.md):

```powershell
.\usb-chat\setup.bat
.\usb-chat\chat.bat
```

Run for real (loads the router GGUF, then workers as needed):

```powershell
python main.py "hi"
python main.py "Summarize the files in the runtime/input folder"
python main.py --thread thr_abc123def4 "tweak the third bullet"
python app.py
```

`python app.py` serves a loopback chat UI at `http://127.0.0.1:8765/` (`GET /`, `GET /whoami`, `GET /threads`, `GET /history`, `GET /profile`, `GET /html`, `GET /web-status`, `POST /profile`, `POST /turns`, `POST /agent-turns`, `POST /v1/chat/completions`). Use `--host 0.0.0.0` so other devices on this Wi-Fi can open it. Double-click `run-id10t.bat` to start it on port **9001** and open the browser. The dropdown lists that device's durable notebooks (`thr_…`) from medium and large runs. Skill checkboxes come from `GET /skills`. Each skill is a module in `src/skills/` and shares `src/skills/host.py` (local model, the signed-in profile, claim checks, saved files). A **Career-ops** checkbox scores a pasted job with the local model. A **Humanizer** checkbox rewrites a pasted resume, cover letter, or other formal text once. It turns on when a `humanizer` checkout sits beside Mayavi (or `MAYAVI_HUMANIZER_ROOT` points at one). Career-ops cover letters get that same pass before the claim check. The host keeps the previous text when a name, date, or number disappears. On a coding run, each committee role can call `ui_guide` when a `ui-ux-pro-max-skill` checkout sits beside Mayavi (or `MAYAVI_UI_UX_ROOT` points at one). The host runs that repo's local search and returns a plain-CSS brief. No cloud model is called. The coder and the critique can call `code_graph` when a `graphify` checkout sits beside Mayavi (or `MAYAVI_GRAPHIFY_ROOT` points at one) and the Graphify package is installed. The host maps the sandbox's Python and JavaScript locally and returns a short answer. Docs, images, and video are not read. A URL is checked by the career-ops Node scripts first. The words `scan`, `tracker`, and `cover` are the other commands. No cloud language model is called. A **Web** checkbox sits left of **Coding**. Web is disabled when `GET /web-status` reports no network or no search keys (the JSON never includes keys). When **Coding** is on, a GitHub URL field appears (`https://github.com/owner/repo` only). Empty or invalid URLs hide git tools. Bot replies render as Markdown (raw HTML in the text is escaped). Fenced `html` blocks and full HTML documents get a **View HTML page** button on that reply (new tab, CSP, no scripts). PDFs the run wrote appear under that reply (icon, filename, **Save to PDF**). If the worker emitted a structured `profile_update`, that reply gets **Save to board**. Each client is keyed by a hashed LAN MAC when the server can see it (stable across Wi-Fi reconnects on this SSID), otherwise by an HttpOnly cookie / UUID. History hydrates from `runtime/state/ui-session/<device>/session.jsonl`. Notebooks sit in `threads/` under that folder. Other programs call `POST /agent-turns` with `device`, `agent`, and `user` (optional `system`, `web`, `coding`) to continue a named workbook (`agent_<slug>.json`) instead of a new chat. Career-ops scores jobs and tailors CVs with `POST /v1/chat/completions` (OpenAI chat shape, loopback only, no API key). That path is one generation: the caller’s full system text, no router, no tools, no workbook. The `model` field is ignored; Mayavi picks a loaded GGUF. `max_tokens` is the generation cap (context grows with it, up to 32k). `stream: true` is SSE; `stream: false` is JSON. Related earlier turns are retrieved by the host from a Chroma index (`runtime/state/chroma/`) and pinned as a short pack. Extra clients can call the same slice over MCP: `python src/mcp_server.py` (`list_notebooks`, `get_notebook`, `search_memory`, `read_log_span`; every tool needs `device`). Starting the server does not wipe those tapes. Peer IP, User-Agent, and language are appended to `meta.jsonl` in that folder for later analytics; they are not used to look up a session. `python app.py --no-model` uses the same stubs as the CLI.

Double-clickable live checks (open a cmd window, show Prompt / Response / Meta, pause):

- `tests\run_hi.bat`
- `tests\run_resume.bat` — expects resumes under `runtime/input/` (or wherever `MAYAVI_WORKSPACE` points)
- `tests\run_scooter.bat`

The CLI does **not** stream tokens. After the run finishes you get:

```text
---------- Prompt ----------
hi
---------- Response ----------
...model answer...
---------- Meta ----------
ok=True level=small stakes=low mail_cal=off run_id=run_...
```

If the model produced no `final`/vote/draft, Response is `(empty — the model produced no user-facing answer)` even when the process exits 0.

## Memory index

Chat logs and notebook JSON stay the source of truth. `runtime/state/chroma/` is a search index keyed by device (and workbook when the turn has one). On `/turns` and `/agent-turns` the host retrieves a short pack and pins it in the user message; the model does not query Chroma. Tests and `--no-model` use a hash embedder so MiniLM is not downloaded.

Extra clients can call the same slice over stdio MCP (`python src/mcp_server.py`, or `PYTHONPATH=src python -m mcp --packs web,profile`). Memory tools are always on (`list_notebooks`, `get_notebook`, `search_memory`, `read_log_span`). `--packs` may add `web`, `profile`, `files.read`, and `files.write`. Every tool requires `device`. Sandbox, board, mail, calendar, and git stay factory-only. Factory workers bind the same capability packs from `src/mcp/` in-process. They still emit `{"tool":…}`; they do not speak MCP. Coding committee roles and round order stay host-owned (`src/coding/`). Job and profile HTML selectors still walk `career.py` (prompts live in `static_prompts.py`).

## Configuration

Copy `.env.example` to `.env`. **Never put secrets in `.env.example`.** `.env` is gitignored. The app loads it from the repo root.

| Variable | Purpose |
| --- | --- |
| `HF_TOKEN` | Hugging Face **Read** token. Required for gated Llama/Gemma downloads. Never logged. |
| `MODELS_DIR` | Primary/USB GGUF library (14B coder + planners). Optional until the USB set exists. If that folder has `models.json`, the factory uses it. |
| `BACKUP_MODELS_DIR` | Small SSD copies (3B set). Point this at `models` for the local backup download. |
| `MAYAVI_WORKSPACE` | **Input** root agents may **read** (`runtime/input/` by default). |
| `MAYAVI_OUTPUTS` | **Output** root for **writes** (`runtime/outputs/` by default). |
| `MAYAVI_CAREER_OPS_ROOT` | Optional path to a career-ops checkout. When unset, Mayavi looks for a sibling folder named `career-ops`. `CAREER_OPS_ROOT` is also accepted. |
| `MAYAVI_UI_UX_ROOT` | Optional path to a ui-ux-pro-max-skill checkout. When unset, Mayavi looks for a sibling folder named `ui-ux-pro-max-skill`. |
| `MAYAVI_GRAPHIFY_ROOT` | Optional path to a graphify checkout. When unset, Mayavi looks for a sibling folder named `graphify`. |
| `MAYAVI_HUMANIZER_ROOT` | Optional path to a humanizer checkout. When unset, Mayavi looks for a sibling folder named `humanizer`. |
| `MAYAVI_HF_DOWNLOAD` | `1` to allow resolve/update to download from Hugging Face into `BACKUP_MODELS_DIR`. Default `0`. |
| `MAYAVI_VERIFY_MODEL_HASH` | `1` to sha256 every GGUF on load and pin the digest in `models.json`. Default `0`, because re-hashing multi-GB weights on every load is slow; downloads are hashed either way, and loads always check the recorded file size. |
| `N_GPU_LAYERS` | llama.cpp GPU offload. `auto` (default) uses GPU only if driver, device, GPU wheel, and dedicated VRAM beat this GGUF, and only for the working agents — the router always stays on CPU. `0` = CPU everywhere. A positive integer forces that many layers for every role, router included. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_LOGIN_HINT` | Gmail + Calendar OAuth (browser Allow). |
| `SERPAPI_API_KEY` / `SCRAPERAPI_API_KEY` | Web search backends. Keys never logged. |
| `GOOGLE_CLOUD_API_KEY` / `GOOGLE_CSE_ID` | Google Custom Search JSON. Used first when both are set; then SerpAPI; then ScraperAPI. Keys never logged. |
| `MS_CLIENT_ID` / `MS_TENANT` / `MS_LOGIN_HINT` | Microsoft Graph mail + calendar OAuth. |
| `MAYAVI_DATA_DIR` | Private state (logs, tokens, createdIndex). Default `runtime/state/`. |
| `MAYAVI_SANDBOX_ROOT` | Coding-run jails. Default `runtime/sandboxes/`. |
| `GH_TOKEN` | Optional GitHub token for coding-committee `git_push` when a valid GitHub URL was given. Stays in-process; never logged or returned to an agent. |

Relative paths in `.env` are resolved from the **repo root**, not the current working directory.

### Folders

| Folder | Role |
| --- | --- |
| `src/` | Python runtime (`app.py` / `main.py` stay at the repo root). |
| `scripts/` | `install.ps1` / `install.sh`. |
| `documentation/` | Changelog, hardware notes, server cart, eval plans and results. |
| `runtime/input/` | Allowed **read** root. Put source documents here. |
| `runtime/outputs/` | Allowed **write** root. `write_doc` / `write_pdf` / `write_json` / `append_file` / `mkdir` only write here. |
| `runtime/outputs/<YYYY-MM-DD>_<intent>/` | Keep folder for one large run. After ship: sandbox files, `result.txt`, and factory `SUMMARY.md`. |
| `runtime/state/` | Logs, OAuth token files, session JSON, `createdIndex.json`, Chroma. Blocked. |
| `runtime/sandboxes/` | Per-`run_id` jail. Blocked from file tools; sandbox APIs only. |
| `models/` | GGUF files. On `BLOCKED_PATHS` (agents cannot `read_file` weights). |
| `ui/` | Chat HTML. |
| `assets/` | Icons and images. |

Writes aimed at `runtime/input/` or anywhere else are denied.

## CLI

```text
python main.py PROMPT
python main.py --web PROMPT
python main.py --code --web PROMPT
python main.py --career-ops "menu"
python main.py --humanizer "menu"
python main.py --code --repo https://github.com/owner/repo PROMPT
python main.py --no-model PROMPT
python main.py --json PROMPT
python main.py --provider google PROMPT
python main.py --provider microsoft PROMPT
```

| Flag | Meaning |
| --- | --- |
| `--code` | Run the sequential coding committee. Without this flag the router never maps a job to that loop. |
| `--career-ops` | Host-owned career-ops path. The local GGUF scores and writes. Node scripts only check a URL or scan portals. A cover letter is rewritten once when the humanizer checkout is present. |
| `--humanizer` | Host-owned humanizer path. One local rewrite of pasted formal text. Same as `--skill humanizer`. |
| `--web` | Factory live search (CSE → SerpAPI → ScraperAPI). The only way workers get `search_web` / `get_url`. Does not pick the coding committee and does not jump the job to medium. Coding + web searches first, then pins a digest for the committee. |
| `--repo URL` | Coding only. `https://github.com/owner/repo` enables git tools; empty or invalid hides them. Local keep commits still happen. |
| `--no-model` | Heuristic routing + stub replies. Does not load GGUFs. Use this before weights exist. |
| `--json` | Print the full run record instead of the Prompt/Response block. |
| `--provider` | Prefer Google or Microsoft when `mail_cal` is not `off`. |

Stdout is the labeled Prompt / Response / Meta block (or JSON). Exit code 0 means the **session** finished, not that the answer is non-empty.

If `--no-model` is omitted and the router GGUF cannot load, routing falls back to the heuristic and workers still try to load models when their turn comes.

The download scripts **do not** load `.env`. Export `HF_TOKEN` in the shell, or pass `--login`.

## Models

All planned weights are **Q4_K_M GGUF**. Manifest: `models.json`. Only **one** model is loaded at a time (mmap). Resolve order: USB (`MODELS_DIR`) if the primary file is present and RAM is enough → backup dir → optional HF download into backup (only if `MAYAVI_HF_DOWNLOAD=1`).

### Backup / laptop set (~7GB)

`src/downloader-scripts/download_models_local.py`

| Role | Model | File |
| --- | --- | --- |
| router | Qwen2.5 1.5B Instruct | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| executor | Qwen2.5 Coder **3B** Instruct | `qwen2.5-coder-3b-instruct-q4_k_m.gguf` |
| builder_qwen | Qwen2.5 **3B** Instruct | `qwen2.5-3b-instruct-q4_k_m.gguf` |
| builder_llama | Llama 3.2 **3B** Instruct | `Llama-3.2-3B-Instruct-Q4_K_M.gguf` |

Gated for this set: **Llama 3.2 3B** only. Qwen files are public.

### Full / USB set (~40GB, 64GB stick)

`src/downloader-scripts/download_models_usb.py` writes `models.json` on the stick when it finishes. The factory reads that file when `MODELS_DIR` points at the USB. Roles have a closed `use` list (`route`, `code`, `plan`, `language`, plus committee tags `manage` / `test` / `critique` / `evaluate` / `document`). Coding large runs pick a RAM-safe `code` model (14B if it fits, else 7B). Medium planning uses the `plan` models. Language prompts (translate / resume / rewrite) use `language`. Leave the leftover space for later image weights.

| Role | Model | Use | Approx |
| --- | --- | --- | --- |
| router | Qwen2.5 1.5B Instruct | route, evaluate, test | 1.1GB |
| router (backup) | Llama 3.2 **3B** Instruct | route | 2.0GB |
| executor | Qwen2.5 Coder **14B** Instruct | code | 9.0GB |
| builder_coder | Qwen2.5 Coder **7B** Instruct | code | 4.7GB |
| builder_deepseek | DeepSeek Coder **6.7B** Instruct | code | 4.1GB |
| builder_yi | Yi-Coder **9B** Chat | code | 5.3GB |
| builder_qwen | Qwen3 **14B** Instruct | plan, manage, document, language | 9.0GB |
| builder_llama | Llama **3.1 8B** Instruct | plan, language, document, critique, manage | 4.9GB |
| builder_gemma | Gemma 2 **9B** Instruct | plan, critique | 5.8GB |

Gated for this set: **Llama 3.2 3B**, **Llama 3.1 8B**, and **Gemma 2 9B**.

After a **large** teardown only, `checkAndUpdateModels` can refresh pins from Hugging Face. It is skipped unless `MAYAVI_HF_DOWNLOAD=1`.

## Gated models (Hugging Face)

Use a **Read** token from the same account that accepts the licenses. Log in, then open the original model pages and use **Agree and access repository**:

Backup set:

- [meta-llama/Llama-3.2-3B-Instruct](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct)
- [bartowski/Llama-3.2-3B-Instruct-GGUF](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF) (accept if it asks)

USB set, additionally:

- [meta-llama/Llama-3.1-8B-Instruct](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct)
- [google/gemma-2-9b-it](https://huggingface.co/google/gemma-2-9b-it)

The USB downloader also fetches Llama 3.2 3B as the second router. Accept that license if you did not already for the backup set.

Do **not** use Write, Inference, CI/CD, or Full access tokens for this project.

## Tools agents can see

Agents never import `executor.py`, `logger.py`, `models.py`, `google_backend.py`, or `microsoft.py`. The runtime injects `agent_id`; models must not pass their own id.

The worker system prompt tells them to **answer directly** unless the user asked for a file, a live URL, mail/calendar, or sandbox code. The factory also **removes tools they should not have**:

| Router field | Tools exposed |
| --- | --- |
| `file_ops` is `0` | No `search_dir` / `read_file` / `write_doc` / `write_pdf` / `write_json` / `append_file` / `mkdir` |
| Operator **web** is off | No `search_web` / `get_url` / `post_url` / `resetSession` (even on medium/large, even if the prompt has URLs) |
| Operator **web** is on | Factory live-search pass, plus those scrape tools |
| `mail_cal` is `off` | No mail/calendar tools |
| not coding | No sandbox tools |
| coding before the ship vote | No durable writers; the sandbox is the only place to build |
| coding without a valid GitHub URL | No `git_login` |

A model that still calls a hidden tool gets `unknown_tool` and can finish with `{"final": "..."}`. That is why a greeting must not invoke `write_doc`. A writer called too early on a **coding** run gets `ship_locked`.

**Files** (`file_tools.py`): `search_dir`, `read_file`, `write_doc`, `write_pdf`, `write_json`, `append_file`, `mkdir` (only if `file_ops` ≠ `0`).

- Reads: `runtime/input/` and `runtime/outputs/` (allowed roots).
- Writes: `outputs/` only. On a **coding** run they are locked until the ship vote, then remapped into that run's keep folder. On a **review** run they go to the keep folder immediately.
- Original files that exist on disk but are not in `createdIndex` cannot be overwritten.
- Created files are tracked in `runtime/state/createdIndex.json` (agents cannot read that index).
- Reads/writes are paged (max 5 pages per call).

**Web** (`web_scrape.py`, backends in `search.py`, factory pipeline in `web_research.py`): `search_web`, `get_url`, `post_url`, `resetSession` only if the operator marked **Web** / `--web`. Medium and large jobs do not get scrape tools from a router `web_ops` count.

- The factory asks the small router GGUF for a query, calls `search.webSearch` (CSE if `GOOGLE_CLOUD_API_KEY` + `GOOGLE_CSE_ID`, else SerpAPI, else ScraperAPI), picks up to three result URLs, and `get_url`s pages 1–2 of each. A larger worker then answers from that digest in chunks. Medium/review/coding runs pin the digest on the blackboard instead.
- Agent `search_web` uses the same `search.webSearch` backends and returns `{title, url, snippet}` rows. Do not scrape `google.com/search`.
- http/https only on fetches. Loopback, private, and link-local IPs are rejected (SSRF).
- No captcha solving, no contacts, no places lookups. The public tool name stays `search_web`.

**Mail / calendar** (`mailAndCalendar.py`): list/search/open mail, send/reply (no delete), calendars, events, free/busy.

- `mail_cal`: `off` | `read` | `write`.
- Only the manager agent: small/medium = drafter; coding large = manager role; review large = executor.
- Outbound bodies are scanned for tokens/JWTs; matches are denied without echoing the secret.
- OAuth is browser **Allow**, not mailbox password. Tokens stay on blocked paths.

**Committee** (`blackboard.py`, used by `runtime.py` / `executor.py`, medium/large): `viewSessionDetails`, blackboard send/view.

Allowed blackboard kinds: `draft`, `critique`, `debug`, `vote`, `rules`, `memory`. Only the factory may post `rules` (coding-rules pin on coding runs) and `memory` (a context card from a durable thread). `select_vote` uses `vote`, then `draft`, then worker `final` text. It never returns `rules`, `debug`, `memory`, or pointer words (`saved` / `shipped` / `ship` / `reject`).

Medium and large runs also write a **thread** under `runtime/state/threads/` (`thr_…`, title from `intent`). Pass `--thread thr_…` on the next command to attach it: a mapped-small prompt is raised to medium; a thread that already shipped artifacts also unlocks `read_file` / `search_dir` so follow-ups can inspect the keep folder. Small without `--thread` never creates or reads a thread. The live committee board is still unique per run and is dropped at teardown.

**Sandbox** (`runtime.py`, coding only): `openSandbox`, `sandbox_read`, `sandbox_write` (coder), `executeScriptInSandbox` / `sandbox_fetch` (tester), `getResultsFromSandbox`. Review runs do not get these tools.

Sandbox v1: `.py` / `.html` / `.css` / `.js` only. Execute is `python <file.py>` under the sandbox root, timed, host env stripped. One exclusive lock covers write, execute, and fetch. HTML/CSS/JS are written as UI, not run as a GUI. `getResultsFromSandbox` returns `not_run` until a script has actually executed, so a committee cannot vote on output that was never produced. Full rules: `src/coding/rules.md`.

### Keep vs wipe on a large run

The factory makes `outputs/<YYYY-MM-DD>_<intent-slug>/` at the start of every large run. On a **coding** run, durable writers stay shut until a **≥4/5** vote; the coder uses `sandbox_write` and the tester executes; then the factory copies the sandbox into the keep folder and records a local git commit (push only if a valid GitHub URL was given). On a **review** run, builders and the executor write `write_doc` / PDF / JSON straight into that keep folder; there is no jail. `write_doc` may use type `md` the same way as `txt`. On a coding run that does not ship, the sandbox is wiped at teardown and nothing durable survives — the user answer is a factory note that they did not ship (plus any jail file names and captured stdout), never the pointer word `saved`. The UI links **view complete summary** to `GET /keep?dir=<keep-folder>&file=SUMMARY.md` (outputs only).

## Path policy

`ALLOWED_PATHS`: `runtime/input/` and `runtime/outputs/`.

`BLOCKED_PATHS` always wins: repo source, `.env`, model dirs, logs, createdIndex, `file_tools.py`, `logger.py`, OAuth token files, `runtime/sandboxes/`, `runtime/state/`. Agents cannot patch this repo through file tools.

## Logging

`logger.py` writes one binary file per local calendar day under `runtime/state/logs/` (`YYYY-MM-DD.mayavi.log`).
The chat UI keeps a separate prompt/answer tape per device in `runtime/state/ui-session/<device>/` (not the audit log). `meta.jsonl` in that folder is an analytics sidecar (time, device id, socket IP, User-Agent, language, path).

Every exported function logs once on return (`ok` or `fail`): factory, tools, and the route mapping step. Spawn records bind `agent_name` → GGUF filename. Summaries are short; bodies and tokens are never stored.

If a log write fails: warn and continue only on small/medium with `mail_cal=off`. Large, high stakes, or mail/calendar access fail the function instead of going unlogged.

## Module map

| File | Role |
| --- | --- |
| `main.py` | CLI (puts `src/` on `sys.path`) |
| `app.py` | Chat UI (`127.0.0.1:8765`, `--host 0.0.0.0` for LAN) |
| `src/tenant.py` | LAN MAC / cookie device key |
| `src/memory.py` | Chroma index + host retrieval pack |
| `src/static_prompts.py` | Chat / web / job / profile / review system prompts |
| `src/mcp/` | Capability packs + stdio server (`src/mcp_server.py` is the entry) |
| `src/sandbox/` | Jail create / read / write / exec |
| `src/coding/` | Sequential coding committee, roster, prompts, `rules.md` |
| `ui/index.html` | Chat page served by `app.py` |
| `src/router.py` | Router prompt, parse, `mapRoute`, heuristic fallback |
| `src/executor.py` | Factory: agents, worker threads, sandbox, session, OAuth connect, run lifecycle |
| `src/committee.py` | Shim → `coding/board.py` |
| `src/git_tools.py` | Keep-folder git login/commit/push; `GH_TOKEN` stays in-process |
| `src/blackboard.py` | Live committee board + durable notebooks (`runtime/state/ui-session/<device>/threads/` in the UI; `runtime/state/threads/` on the CLI) |
| `src/runtime.py` | Session details + blackboard wrappers (sandbox re-exported from `sandbox/`) |
| `src/file_tools.py` | Public file API |
| `src/web_scrape.py` | HTTP GET/POST + `search_web` |
| `src/search.py` | Private CSE / SerpAPI / ScraperAPI backend for `search_web` and the operator Web control |
| `src/web_research.py` | Factory live-search pipeline (query → search → fetch → digest). Agents never import this. |
| `src/mailAndCalendar.py` | Agent-facing mail/calendar door |
| `src/google_backend.py` / `src/microsoft.py` | Private OAuth backends (the Google file **cannot** be named `google.py`: it would shadow Google's own `google` package) |
| `src/models.py` | Resolve / RAM check / load / generate / pin refresh |
| `src/gpu-check.py` | Factory-only GPU decision per role (driver, device, wheel, dedicated VRAM) |
| `models.json` | Role → repo/file/revision |
| `src/logger.py` | Spawn + event audit log |
| `src/config.py` | Paths, env, allowed/blocked lists |
| `src/store.py` | Private run registry |
| `src/profile.py` | Durable operator profile board (`runtime/state/profile.json`). Agents never import this. |
| `src/formatter.py` | Chat-answer Markdown HTML + sandboxed HTML pages. Agents never import this. |
| `src/coding/rules.md` | Injected on every coding committee run |
| `documentation/Hardware Requirements.md` | Ubuntu/Windows, headless vs desktop, named NVIDIA and Ryzen SKUs |
| `documentation/Server Hardware.md` | Headless box cart (CPU, GPU, disks) |
| `documentation/CHANGELOG.md` | Hand-written release history, newest first (never updated automatically). Current version **1.3.3**. |
| `documentation/Multi-Phase Testing (Testing Plan).md` | Multi-phase eval plan |
| `documentation/Multi-Phase Testing (Results).md` | Multi-phase eval results |
| `documentation/Memory Board Continuity (Results).md` | Memory-board continuity results |
| `documentation/Quality Test Results.md` | Quality-test results |
| `scripts/install.ps1` / `scripts/install.sh` | Setup only: venv, both requirement files, `.env`. No models, no secrets |
| `src/downloader-scripts/` | HF GGUF fetchers (not imported by the runtime) |
| `usb-chat/` | Standalone USB GGUF chat (not the committee). Copy onto the stick; see [`usb-chat/README.md`](usb-chat/README.md) |

## Mail and calendar (optional)

1. Create a Google Cloud OAuth **desktop** client and/or a Microsoft public client.
2. Put client ids/secrets in `.env` (no mailbox password).
3. Run with `--provider google` or `--provider microsoft` on a prompt that needs inbox/calendar.
4. The factory opens a browser consent screen before worker threads start.
5. Tokens land in `runtime/state/tokens/` (`token_google_*.json`, `token_ms_*.json`), which is blocked.

If `mail_cal` is `off`, connect is skipped.

## Tests

```powershell
python -m pytest
```

Pytest uses a temp tree (no real GGUF load, no browser OAuth, and a throwaway copy of `models.json` so pin writes never touch the tracked manifest). It covers routing defaults, vote selection, tool gating, page windows, the createdIndex write gate, per-type appends, path escapes, the binary log format and its hard-fail policy, SSRF including redirect hops, mail policy, sandbox bind/lock/execute/fetch, the large-run keep folder and ship lock, model pins, the GPU decision per role, CLI error text, and small/medium/large teardown.

Those 136 tests are **not** a live chat log. Session tests inject `stub_generate` (they echo `intent`). Other tests print the tool call and JSON result. For a real model answer, use `python main.py "..."` or the `.bat` scripts above.

Live bats live under `tests/` (gitignored with the rest of that folder). They call `main.py` with unbuffered output.

### Live scenario suite

`pytest` proves the parts work alone. `tests/live/` proves the factory does a real job: real prompts, real GGUFs, real files, real refusals. It is not collected by pytest, because a large scenario can run over an hour.

```powershell
python tests\live\runner.py --list        # 22 scenarios and a time budget
python tests\live\runner.py --matrix      # feature -> scenario coverage map
python tests\live\runner.py --dry-run     # stage fixtures, report blockers, load nothing
python tests\live\runner.py --tier small
python tests\live\runner.py --id large_receipt_pipeline
```

Every check is graded either `contract` (a runtime guarantee — a failure is a bug) or `quality` (what the local model produced — a failure on the 3B set is a limitation, not a bug). The runner exits non-zero only on `contract` failures unless you pass `--strict`, and each run writes `outputs/live/<timestamp>/report.md`.

Scenarios cover the three tiers end to end, including a resume retargeted to a job description, a cover letter written from a live portfolio URL, and a Swedish-receipt-to-CSV pipeline built by the coding committee. `tests/live/README.md` explains the prerequisites, the mail/calendar opt-in, and why the receipts task is shaped around the sandbox's no-network, no-pip limits. Start with `tests\run_live_smoke.bat`, which uses stub replies and finishes in seconds.

## License

MIT. Third-party model licenses still apply (Apache-2.0 Qwen/Mistral, Llama community license, Gemma terms). Accept those on Hugging Face before downloading gated weights.
