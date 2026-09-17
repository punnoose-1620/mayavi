# Project ID-10-T

![Display Image](assets/displayImage.jpg)


Local multi-agent runtime that routes a user request into a **small**, **medium**, or **large** session, then runs local GGUF models one at a time with a locked-down tool set.

It is designed to run on a single machine (overnight / sequential). It does **not** keep five models in RAM. Weights come from Hugging Face as GGUF files. Inference uses llama.cpp (`llama-cpp-python`).

## What it does

1. A **router** inspects the prompt and emits effort/stakes fields (not a tier name). It does not answer the user and does not call tools.
2. The script maps those fields to `small` | `medium` | `large`.
3. A **factory** (`executor.py`) creates agents, optional blackboard, optional sandbox, and (if requested) mail/calendar OAuth. File and web tools are **gated** from the router counts: `file_ops=0` hides writers/readers; `web_ops=0` hides scrape tools.
4. Workers prefer a direct `{"final": "..."}`. They only get a tool if the router counted that family and the user asked for a file, URL, mail, or sandbox code.
5. The CLI prints **one** user-facing answer (Prompt / Response / Meta). Tokens are not streamed. On medium/large, that answer comes from blackboard `vote` then `draft`. Factory `rules` and sandbox `debug` are never the answer. If the model only emits `final`, the script copies it onto the board.
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

If the router is **unsure**, fields default **cheap**: `stakes=low`, `needs_code_exec=no`, `file_ops=0`, `web_ops=0` → **small**. High stakes only when the prompt is clearly legal/official/medical/financial (or similar). Greetings, chat, how-to, and summaries are low. A write counts toward `file_ops` only if the user asked to create or save a file. Missing or garbage router JSON uses those same cheap defaults (it does **not** round up to large).

| Tier | Agents | Blackboard | Sandbox | Typical use |
| --- | --- | --- | --- | --- |
| Small | 1 drafter | no | no | cheap Q&A, light file/web |
| Medium | drafter + 2 checkers | yes | no | more file/web work, review |
| Large | 1 executor + builders | yes | **always** | high stakes and/or custom code |

Large always creates a sandbox and injects `coding-rules.md`, even when the user task is not “write a program.” If the USB model library is present, large uses four unique builders. If not, it uses the thinner backup pair (Llama 3.2 3B + Qwen 3B).

## Requirements

- Python 3.10+
- Enough disk for GGUFs (~7GB backup set, or ~26GB full USB set)
- Enough RAM to load **one** GGUF at a time (file size × 1.2, plus a 2GB reserve)
- Hugging Face account + **Read** token (needed for gated Llama/Gemma)
- Optional: GPU via `N_GPU_LAYERS`; CPU mmap is the default

Install Python deps:

```powershell
cd "d:\Documents\Github Repositories\id10t"
python -m pip install -r requirements.txt
python -m pip install -r requirements-inference.txt
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

`--no-model` and `pytest` use **stubs**. They will not print a real 3B chat reply. `pytest` also prints each test’s captured call/result (`-s` is on by default); most of those 44 tests are gates (path deny, SSRF, mail policy), not conversations.

Run for real (loads the router GGUF, then workers as needed):

```powershell
python main.py "hi"
python main.py "Summarize the files in the input folder"
```

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
| `MODELS_DIR` | Primary/USB GGUF library (7B–9B set). Optional until the USB set exists. |
| `BACKUP_MODELS_DIR` | Small SSD copies (3B set). Point this at `models` for the local backup download. |
| `ID10T_WORKSPACE` | **Input** root agents may **read** (`input/` by default). |
| `ID10T_OUTPUTS` | **Output** root for **writes** (`outputs/` by default). |
| `ID10T_HF_DOWNLOAD` | `1` to allow resolve/update to download from Hugging Face into `BACKUP_MODELS_DIR`. Default `0`. |
| `N_GPU_LAYERS` | llama.cpp GPU offload. `0` = CPU. |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_LOGIN_HINT` | Gmail + Calendar OAuth (browser Allow). |
| `MS_CLIENT_ID` / `MS_TENANT` / `MS_LOGIN_HINT` | Microsoft Graph mail + calendar OAuth. |
| `ID10T_DATA_DIR` | Private state (logs, tokens, createdIndex). Default `state/`. |
| `ID10T_SANDBOX_ROOT` | Large-run jails. Default `sandboxes/`. |

Relative paths in `.env` are resolved from the **repo root**, not the current working directory.

### Folders

| Folder | Role |
| --- | --- |
| `input/` | Allowed **read** root. Put source documents here. |
| `outputs/` | Allowed **write** root. `write_doc` / `write_pdf` / `write_json` / `append_file` / `mkdir` only write here. |
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

### Full / USB set (~26GB, 32GB stick)

`downloader-scripts/download_models_usb.py`

| Role | Model | Approx |
| --- | --- | --- |
| router | Qwen2.5 1.5B Instruct | 1.1GB |
| executor | Qwen2.5 Coder **7B** Instruct | 4.7GB |
| builder_llama | Llama **3.1 8B** Instruct | 4.9GB |
| builder_qwen | Qwen2.5 **7B** Instruct | 4.7GB |
| builder_mistral | Mistral 7B Instruct v0.3 | 4.4GB |
| builder_gemma | Gemma 2 **9B** Instruct | 5.8GB |

Gated for this set: **Llama 3.1 8B** and **Gemma 2 9B**.

After a **large** teardown only, `checkAndUpdateModels` can refresh pins from Hugging Face. It is skipped unless `ID10T_HF_DOWNLOAD=1`.

## Gated models (Hugging Face)

Use a **Read** token from the same account that accepts the licenses. Log in, then open the original model pages and use **Agree and access repository**:

Backup set:

- [meta-llama/Llama-3.2-3B-Instruct](https://huggingface.co/meta-llama/Llama-3.2-3B-Instruct)
- [bartowski/Llama-3.2-3B-Instruct-GGUF](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF) (accept if it asks)

USB set, additionally:

- [meta-llama/Llama-3.1-8B-Instruct](https://huggingface.co/meta-llama/Llama-3.1-8B-Instruct)
- [google/gemma-2-9b-it](https://huggingface.co/google/gemma-2-9b-it)

Do **not** use Write, Inference, CI/CD, or Full access tokens for this project.

## Tools agents can see

Agents never import `executor.py`, `logger.py`, `models.py`, `google.py`, or `microsoft.py`. The runtime injects `agent_id`; models must not pass their own id.

The worker system prompt tells them to **answer directly** unless the user asked for a file, a live URL, mail/calendar, or sandbox code. The factory also **removes tools they should not have**:

| Router field | Tools exposed |
| --- | --- |
| `file_ops` is `0` | No `search_dir` / `read_file` / `write_doc` / `write_pdf` / `write_json` / `append_file` / `mkdir` |
| `web_ops` is `0` | No `get_url` / `post_url` / `resetSession` |
| `mail_cal` is `off` | No mail/calendar tools |
| not `large` | No sandbox tools |

A model that still calls a hidden tool gets `unknown_tool` and can finish with `{"final": "..."}`. That is why a greeting must not invoke `write_doc`.

**Files** (`file_tools.py`): `search_dir`, `read_file`, `write_doc`, `write_pdf`, `write_json`, `append_file`, `mkdir` (only if `file_ops` ≠ `0`).

- Reads: `input/` and `outputs/` (allowed roots).
- Writes: `outputs/` only.
- Original files that exist on disk but are not in `createdIndex` cannot be overwritten.
- Created files are tracked in `state/createdIndex.json` (agents cannot read that index).
- Reads/writes are paged (max 5 pages per call).

**Web** (`web_scrape.py`): `get_url`, `post_url`, `resetSession` (only if `web_ops` ≠ `0`).

- http/https only. Loopback, private, and link-local IPs are rejected (SSRF).
- No captcha solving, no search APIs (v2).

**Mail / calendar** (`mailAndCalendar.py`): list/search/open mail, send/reply (no delete), calendars, events, free/busy.

- `mail_cal`: `off` | `read` | `write`.
- Only the manager agent: small/medium = drafter; large = executor role.
- Outbound bodies are scanned for tokens/JWTs; matches are denied without echoing the secret.
- OAuth is browser **Allow**, not mailbox password. Tokens stay on blocked paths.

**Committee** (`runtime.py`, medium/large): `viewSessionDetails`, blackboard send/view.

Allowed blackboard kinds: `draft`, `critique`, `debug`, `vote`, `rules`. Only the factory may post `rules` (coding-rules pin on large). `select_vote` uses `vote`, then `draft`, then worker `final` text. It never returns `rules` or `debug`.

**Sandbox** (`runtime.py`, large only): `openSandbox`, `sandbox_read`, `sandbox_write` (builders), `executeScriptInSandbox` / `sandbox_fetch` (executor), `getResultsFromSandbox`.

Sandbox v1: `.py` / `.html` / `.css` / `.js` only. Execute is `python <file.py>` under the sandbox root, timed, host env stripped. One exclusive lock covers write, execute, and fetch. HTML/CSS/JS are written as UI, not run as a GUI. Full rules: `coding-rules.md`.

## Path policy

`ALLOWED_PATHS`: `input/` and `outputs/`.

`BLOCKED_PATHS` always wins: repo source, `.env`, model dirs, logs, createdIndex, `file_tools.py`, `logger.py`, OAuth token files, sandboxes, `state/`. Agents cannot patch this repo through file tools.

## Logging

`logger.py` writes one binary file per local calendar day under `state/logs/` (`YYYY-MM-DD.id10t.log`).

Every exported function logs once on return (`ok` or `fail`): factory, tools, and the route mapping step. Spawn records bind `agent_name` → GGUF filename. Summaries are short; bodies and tokens are never stored.

If a log write fails: warn and continue only on small/medium with `mail_cal=off`. Large, high stakes, or mail/calendar access fail the function instead of going unlogged.

## Module map

| File | Role |
| --- | --- |
| `main.py` | CLI |
| `router.py` | Router prompt, parse, `mapRoute`, heuristic fallback |
| `executor.py` | Factory: agents, threads, sandbox, blackboard, session, OAuth connect, run lifecycle |
| `runtime.py` | Agent committee + sandbox tools |
| `file_tools.py` | Public file API |
| `web_scrape.py` | HTTP GET/POST |
| `mailAndCalendar.py` | Agent-facing mail/calendar door |
| `google.py` / `microsoft.py` | Private OAuth backends |
| `models.py` | Resolve / RAM check / load / generate / pin refresh |
| `models.json` | Role → repo/file/revision |
| `logger.py` | Spawn + event audit log |
| `config.py` | Paths, env, allowed/blocked lists |
| `store.py` | Private run registry |
| `coding-rules.md` | Injected on every large run |
| `downloader-scripts/` | HF GGUF fetchers (not imported by the runtime) |

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

Pytest uses a temp tree (no real GGUF load, no browser OAuth). It covers routing defaults, vote selection, tool gating, logs, file gates, SSRF, mail policy, sandbox execute/fetch, and small/medium/large teardown.

Those 44 tests are **not** a live chat log. Session tests inject `stub_generate` (they echo `intent`). Other tests print the tool call and JSON result. For a real model answer, use `python main.py "..."` or the `.bat` scripts above.

Live bats live under `tests/` (gitignored with the rest of that folder). They call `main.py` with unbuffered output.

## License

MIT. Third-party model licenses still apply (Apache-2.0 Qwen/Mistral, Llama community license, Gemma terms). Accept those on Hugging Face before downloading gated weights.
