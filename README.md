# Project ID-10-T

![Display Image](assets/displayImage.jpg)


Local multi-agent runtime that routes a user request into a **small**, **medium**, or **large** session, then runs local GGUF models one at a time with a locked-down tool set.

It is designed to run on a single machine (overnight / sequential). It does **not** keep five models in RAM. Weights come from Hugging Face as GGUF files. Inference uses llama.cpp (`llama-cpp-python`).

Release history lives in [`CHANGELOG.md`](CHANGELOG.md), newest version **first** (`1.0.2` above `1.0.1`, and so on), so the top entry is always the current feature set. Work that is deliberately not in v1 is parked in [`docs/v2-scope.md`](docs/v2-scope.md).

## What it does

1. A **router** inspects the prompt and emits effort/stakes fields (not a tier name). It does not answer the user and does not call tools.
2. The script maps those fields to `small` | `medium` | `large`.
3. A **factory** (`executor.py`) creates agents, optional blackboard, optional sandbox, and (if requested) mail/calendar OAuth. File and web tools are **gated** from the router counts: `file_ops=0` hides writers/readers; `web_ops=0` hides scrape tools.
4. Workers prefer a direct `{"final": "..."}`. They only get a tool if the router counted that family and the user asked for a file, URL, mail, or sandbox code.
5. The CLI prints **one** user-facing answer (Prompt / Response / Meta). Tokens are not streamed. On medium/large, that answer comes from blackboard `vote` then `draft`. Factory `rules`, sandbox `debug`, and bare `ship` / `reject` / `saved` / `shipped` pointers are never the answer. After a large run ships, the answer is a summary of the keep folder; artifacts land in `outputs/<YYYY-MM-DD>_<intent-slug>/`. If they do not ship, the factory says so (and lists jail files / stdout when it has them) instead of the word `saved`. If the model only emits `final`, the script copies it onto the board.
6. A daily binary **audit log** records who spawned and which exported functions ran. It does not store transcripts, file bodies, mail bodies, or tokens.

## Tiers

The router never outputs `small` / `medium` / `large`. Mapping is:

| Condition | Tier |
| --- | --- |
| `stakes` is `high` | **large** (always) |
| else `needs_code_exec` is `yes` | **large** |
| else `file_ops` is `3+` **or** `web_ops` is `2+` | **medium** |
| else | **small** |

`mail_cal` does not pick the tier. Coding tasks force `mail_cal` to `off`.

If the router is **unsure**, fields default **cheap**: `stakes=low`, `needs_code_exec=no`, `file_ops=0`, `web_ops=0` → **small**. High stakes only when the prompt is clearly legal/official/medical/financial (or similar). Greetings, chat, how-to, and summaries are low. A write counts toward `file_ops` only if the user asked to create or save a file. Summarizing or reading code already under `outputs/` is a file read (`file_ops` at least 1, `needs_code_exec=no`), not a new sandbox build. Missing or garbage router JSON uses those same cheap defaults (it does **not** round up to large).

| Tier | Agents | Blackboard | Sandbox | Typical use |
| --- | --- | --- | --- | --- |
| Small | 1 drafter | no | no | cheap Q&A, light file/web |
| Medium | drafter + 2 checkers | yes + durable thread | no | more file/web work, review |
| Large | 1 executor + builders | yes | **always** | high stakes and/or custom code |

Large always creates a sandbox and a keep folder, and injects `coding-rules.md`, even when the user task is not “write a program.” If the USB library is present, the factory picks builders from `models.json` `use` tags (coding large: 14B coder plus up to three other `code` models). If not, it uses the thinner backup pair (Llama 3.2 3B + Qwen 3B).

## Requirements

Machine-by-machine floors (Ubuntu vs Windows, headless vs desktop, named NVIDIA and Ryzen SKUs) are in [`Hardware Requirements.md`](Hardware%20Requirements.md).

- Python 3.11+
- Enough disk for GGUFs (~7GB backup set, or ~40GB full USB set on a 64GB stick)
- Enough RAM to load **one** GGUF at a time (file size × 1.2, plus a 2GB reserve)
- Hugging Face account + **Read** token (needed for gated Llama/Gemma)
- Optional: GPU via `N_GPU_LAYERS` (`auto` = detect CUDA wheel + dedicated VRAM vs this GGUF, working agents only; `0` = CPU)

Install with the setup script for your platform. It checks the Python version, creates `.venv`, installs both requirement files, copies `.env.example` to `.env` if you have no `.env` yet, and prints what to edit. It does **not** download models.

```powershell
.\install.ps1
```

```bash
./install.sh
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
python downloader-scripts/download_models_local.py --path "d:\Documents\Github Repositories\id10t\models"
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
python main.py "Summarize the files in the input folder"
python main.py --thread thr_abc123def4 "tweak the third bullet"
python app.py
```

`python app.py` serves a loopback chat UI at `http://127.0.0.1:8765/` (`GET /`, `GET /threads`, `GET /history`, `POST /turns`). Double-click `run-id10t.bat` to start it on port **9001** and open the browser. The dropdown lists durable notebooks (`thr_…`) from medium and large runs. The page hydrates from `state/ui-session/session.jsonl`; starting the server renames that file to `previous.jsonl` so a crash copy survives one restart. `python app.py --no-model` uses the same stubs as the CLI.

Double-clickable live checks (open a cmd window, show Prompt / Response / Meta, pause):

- `tests\run_hi.bat`
- `tests\run_resume.bat` — expects resumes under `input/` (or `inputs/` if you pointed `ID10T_WORKSPACE` there)
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

## Configuration

Copy `.env.example` to `.env`. **Never put secrets in `.env.example`.** `.env` is gitignored. The app loads it from the repo root.

| Variable | Purpose |
| --- | --- |
| `HF_TOKEN` | Hugging Face **Read** token. Required for gated Llama/Gemma downloads. Never logged. |
| `MODELS_DIR` | Primary/USB GGUF library (14B coder + planners). Optional until the USB set exists. If that folder has `models.json`, the factory uses it. |
| `BACKUP_MODELS_DIR` | Small SSD copies (3B set). Point this at `models` for the local backup download. |
| `ID10T_WORKSPACE` | **Input** root agents may **read** (`input/` by default). |
| `ID10T_OUTPUTS` | **Output** root for **writes** (`outputs/` by default). |
| `ID10T_HF_DOWNLOAD` | `1` to allow resolve/update to download from Hugging Face into `BACKUP_MODELS_DIR`. Default `0`. |
| `ID10T_VERIFY_MODEL_HASH` | `1` to sha256 every GGUF on load and pin the digest in `models.json`. Default `0`, because re-hashing multi-GB weights on every load is slow; downloads are hashed either way, and loads always check the recorded file size. |
| `N_GPU_LAYERS` | llama.cpp GPU offload. `auto` (default) uses GPU only if driver, device, GPU wheel, and dedicated VRAM beat this GGUF, and only for the working agents — the router always stays on CPU. `0` = CPU everywhere. A positive integer forces that many layers for every role, router included. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_LOGIN_HINT` | Gmail + Calendar OAuth (browser Allow). |
| `SERPAPI_API_KEY` / `SCRAPERAPI_API_KEY` | Web search (`search_web`). SerpAPI first, ScraperAPI if Serp is missing or fails. Keys never logged. |
| `GOOGLE_CLOUD_API_KEY` / `GOOGLE_CSE_ID` | Unused Custom Search JSON leftovers (closed to new projects). |
| `MS_CLIENT_ID` / `MS_TENANT` / `MS_LOGIN_HINT` | Microsoft Graph mail + calendar OAuth. |
| `ID10T_DATA_DIR` | Private state (logs, tokens, createdIndex). Default `state/`. |
| `ID10T_SANDBOX_ROOT` | Large-run jails. Default `sandboxes/`. |

Relative paths in `.env` are resolved from the **repo root**, not the current working directory.

### Folders

| Folder | Role |
| --- | --- |
| `input/` | Allowed **read** root. Put source documents here. |
| `outputs/` | Allowed **write** root. `write_doc` / `write_pdf` / `write_json` / `append_file` / `mkdir` only write here. |
| `outputs/<YYYY-MM-DD>_<intent>/` | Keep folder for one large run. After ship: sandbox files, `result.txt`, and factory `SUMMARY.md`. |
| `models/` | GGUF files. On `BLOCKED_PATHS` (agents cannot `read_file` weights). |
| `state/` | Logs, OAuth token files, session JSON, `createdIndex.json`. Blocked. |
| `sandboxes/` | Per-`run_id` jail. Blocked from file tools; runtime sandbox APIs only. |

Writes aimed at `input/` or anywhere else are denied.

## CLI

```text
python main.py PROMPT
python main.py --no-model PROMPT
python main.py --json PROMPT
python main.py --provider google PROMPT
python main.py --provider microsoft PROMPT
```

| Flag | Meaning |
| --- | --- |
| `--no-model` | Heuristic routing + stub replies. Does not load GGUFs. Use this before weights exist. |
| `--json` | Print the full run record instead of the Prompt/Response block. |
| `--provider` | Prefer Google or Microsoft when `mail_cal` is not `off`. |

Stdout is the labeled Prompt / Response / Meta block (or JSON). Exit code 0 means the **session** finished, not that the answer is non-empty.

If `--no-model` is omitted and the router GGUF cannot load, routing falls back to the heuristic and workers still try to load models when their turn comes.

The download scripts **do not** load `.env`. Export `HF_TOKEN` in the shell, or pass `--login`.

## Models

All planned weights are **Q4_K_M GGUF**. Manifest: `models.json`. Only **one** model is loaded at a time (mmap). Resolve order: USB (`MODELS_DIR`) if the primary file is present and RAM is enough → backup dir → optional HF download into backup (only if `ID10T_HF_DOWNLOAD=1`).

### Backup / laptop set (~7GB)

`downloader-scripts/download_models_local.py`

| Role | Model | File |
| --- | --- | --- |
| router | Qwen2.5 1.5B Instruct | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| executor | Qwen2.5 Coder **3B** Instruct | `qwen2.5-coder-3b-instruct-q4_k_m.gguf` |
| builder_qwen | Qwen2.5 **3B** Instruct | `qwen2.5-3b-instruct-q4_k_m.gguf` |
| builder_llama | Llama 3.2 **3B** Instruct | `Llama-3.2-3B-Instruct-Q4_K_M.gguf` |

Gated for this set: **Llama 3.2 3B** only. Qwen files are public.

### Full / USB set (~40GB, 64GB stick)

`downloader-scripts/download_models_usb.py` writes `models.json` on the stick when it finishes. The factory reads that file when `MODELS_DIR` points at the USB. Roles have a closed `use` list (`route`, `code`, `plan`, `language`). Coding large runs use the 14B coder plus up to three other `code` builders. Medium planning uses the `plan` models. Language prompts (translate / resume / rewrite) use `language`. Leave the leftover space for later image weights.

| Role | Model | Use | Approx |
| --- | --- | --- | --- |
| router | Qwen2.5 1.5B Instruct | route | 1.1GB |
| router (backup) | Llama 3.2 **3B** Instruct | route | 2.0GB |
| executor | Qwen2.5 Coder **14B** Instruct | code | 9.0GB |
| builder_coder | Qwen2.5 Coder **7B** Instruct | code | 4.7GB |
| builder_deepseek | DeepSeek Coder **6.7B** Instruct | code | 4.1GB |
| builder_yi | Yi-Coder **9B** Chat | code | 5.3GB |
| builder_qwen | Qwen3 **14B** Instruct | plan, language | 9.0GB |
| builder_llama | Llama **3.1 8B** Instruct | plan, language | 4.9GB |
| builder_gemma | Gemma 2 **9B** Instruct | plan, language | 5.8GB |

Gated for this set: **Llama 3.2 3B**, **Llama 3.1 8B**, and **Gemma 2 9B**.

After a **large** teardown only, `checkAndUpdateModels` can refresh pins from Hugging Face. It is skipped unless `ID10T_HF_DOWNLOAD=1`.

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
| `web_ops` is `0` | No `search_web` / `get_url` / `post_url` / `resetSession` |
| `mail_cal` is `off` | No mail/calendar tools |
| not `large` | No sandbox tools |
| `large` before the ship vote | No writers; the sandbox is the only place to build |

A model that still calls a hidden tool gets `unknown_tool` and can finish with `{"final": "..."}`. That is why a greeting must not invoke `write_doc`. A writer called too early on a large run gets `ship_locked`.

**Files** (`file_tools.py`): `search_dir`, `read_file`, `write_doc`, `write_pdf`, `write_json`, `append_file`, `mkdir` (only if `file_ops` ≠ `0`).

- Reads: `input/` and `outputs/` (allowed roots).
- Writes: `outputs/` only. On a large run they are locked until the ship vote, then remapped into that run's keep folder.
- Original files that exist on disk but are not in `createdIndex` cannot be overwritten.
- Created files are tracked in `state/createdIndex.json` (agents cannot read that index).
- Reads/writes are paged (max 5 pages per call).

**Web** (`web_scrape.py`, backends in `search.py`): `search_web`, `get_url`, `post_url`, `resetSession` (only if `web_ops` ≠ `0`).

- `search_web` calls `search.webSearch` with `SERPAPI_API_KEY` (first) then `SCRAPERAPI_API_KEY`, and returns `{title, url, snippet}` rows. Then `get_url` fetches a chosen URL. Do not scrape `google.com/search`.
- http/https only on fetches. Loopback, private, and link-local IPs are rejected (SSRF).
- No captcha solving, no contacts, no places lookups — see [`docs/v2-scope.md`](docs/v2-scope.md). The public tool name stays `search_web`.

**Mail / calendar** (`mailAndCalendar.py`): list/search/open mail, send/reply (no delete), calendars, events, free/busy.

- `mail_cal`: `off` | `read` | `write`.
- Only the manager agent: small/medium = drafter; large = executor role.
- Outbound bodies are scanned for tokens/JWTs; matches are denied without echoing the secret.
- OAuth is browser **Allow**, not mailbox password. Tokens stay on blocked paths.

**Committee** (`blackboard.py`, used by `runtime.py` / `executor.py`, medium/large): `viewSessionDetails`, blackboard send/view.

Allowed blackboard kinds: `draft`, `critique`, `debug`, `vote`, `rules`, `memory`. Only the factory may post `rules` (coding-rules pin on large) and `memory` (a context card from a durable thread). `select_vote` uses `vote`, then `draft`, then worker `final` text. It never returns `rules`, `debug`, `memory`, or pointer words (`saved` / `shipped` / `ship` / `reject`).

Medium and large runs also write a **thread** under `state/threads/` (`thr_…`, title from `intent`). Pass `--thread thr_…` on the next command to attach it: a mapped-small prompt is raised to medium; a thread that already shipped artifacts also unlocks `read_file` / `search_dir` so follow-ups can inspect the keep folder. Small without `--thread` never creates or reads a thread. The live committee board is still unique per run and is dropped at teardown.

**Sandbox** (`runtime.py`, large only): `openSandbox`, `sandbox_read`, `sandbox_write` (builders), `executeScriptInSandbox` / `sandbox_fetch` (executor), `getResultsFromSandbox`.

Sandbox v1: `.py` / `.html` / `.css` / `.js` only. Execute is `python <file.py>` under the sandbox root, timed, host env stripped. One exclusive lock covers write, execute, and fetch. HTML/CSS/JS are written as UI, not run as a GUI. `getResultsFromSandbox` returns `not_run` until a script has actually executed, so a committee cannot vote on output that was never produced. Full rules: `coding-rules.md`.

### Keep vs wipe on a large run

The factory makes `outputs/<YYYY-MM-DD>_<intent-slug>/` at the start of the run and keeps every writer (`write_doc`, `write_pdf`, `write_json`, `append_file`, `mkdir`) shut. Builders can only use `sandbox_write`; the executor runs the script and reads the results. Once a script has run and the committee votes **ship** by majority, the factory unlocks the writers, copies the sandbox's `.py` / `.html` / `.css` / `.js` files plus captured stdout (`result.txt`) into the keep folder, writes `SUMMARY.md` there, remaps any later write into that same folder, and answers with a summary of those files. The UI links **view complete summary** to `GET /keep?dir=<keep-folder>&file=SUMMARY.md` (outputs only). `write_doc` may use type `md` the same way as `txt`. Without a ship, the sandbox is wiped at teardown and nothing durable survives — the user answer is a factory note that they did not ship (plus any jail file names and captured stdout), never the pointer word `saved`.

## Path policy

`ALLOWED_PATHS`: `input/` and `outputs/`.

`BLOCKED_PATHS` always wins: repo source, `.env`, model dirs, logs, createdIndex, `file_tools.py`, `logger.py`, OAuth token files, sandboxes, `state/`. Agents cannot patch this repo through file tools.

## Logging

`logger.py` writes one binary file per local calendar day under `state/logs/` (`YYYY-MM-DD.id10t.log`).
The chat UI keeps a separate prompt/answer tape in `state/ui-session/` (not the audit log).

Every exported function logs once on return (`ok` or `fail`): factory, tools, and the route mapping step. Spawn records bind `agent_name` → GGUF filename. Summaries are short; bodies and tokens are never stored.

If a log write fails: warn and continue only on small/medium with `mail_cal=off`. Large, high stakes, or mail/calendar access fail the function instead of going unlogged.

## Module map

| File | Role |
| --- | --- |
| `main.py` | CLI |
| `app.py` | Loopback chat UI (`127.0.0.1:8765`) |
| `ui/index.html` | Chat page served by `app.py` |
| `router.py` | Router prompt, parse, `mapRoute`, heuristic fallback |
| `executor.py` | Factory: agents, worker threads, sandbox, session, OAuth connect, run lifecycle |
| `blackboard.py` | Live committee board + durable `state/threads/` notes |
| `runtime.py` | Agent committee + sandbox tools (blackboard send/view are wrappers)
| `file_tools.py` | Public file API |
| `web_scrape.py` | HTTP GET/POST + `search_web` |
| `search.py` | Private SerpAPI / ScraperAPI backend for `search_web` |
| `mailAndCalendar.py` | Agent-facing mail/calendar door |
| `google_backend.py` / `microsoft.py` | Private OAuth backends (the Google file **cannot** be named `google.py`: it would shadow Google's own `google` package) |
| `models.py` | Resolve / RAM check / load / generate / pin refresh |
| `gpu-check.py` | Factory-only GPU decision per role (driver, device, wheel, dedicated VRAM) |
| `models.json` | Role → repo/file/revision |
| `logger.py` | Spawn + event audit log |
| `config.py` | Paths, env, allowed/blocked lists |
| `store.py` | Private run registry |
| `coding-rules.md` | Injected on every large run |
| `Hardware Requirements.md` | Ubuntu/Windows, headless vs desktop, named NVIDIA and Ryzen SKUs |
| `CHANGELOG.md` | Hand-written release history, newest first (never updated automatically) |
| `install.ps1` / `install.sh` | Setup only: venv, both requirement files, `.env`. No models, no secrets |
| `docs/` | The design specs the runtime was built from, plus `v2-scope.md` for planned work |
| `downloader-scripts/` | HF GGUF fetchers (not imported by the runtime) |
| `usb-chat/` | Standalone USB GGUF chat (not the committee). Copy onto the stick; see [`usb-chat/README.md`](usb-chat/README.md) |

## Mail and calendar (optional)

1. Create a Google Cloud OAuth **desktop** client and/or a Microsoft public client.
2. Put client ids/secrets in `.env` (no mailbox password).
3. Run with `--provider google` or `--provider microsoft` on a prompt that needs inbox/calendar.
4. The factory opens a browser consent screen before worker threads start.
5. Tokens land in `state/tokens/` (`token_google_*.json`, `token_ms_*.json`), which is blocked.

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
