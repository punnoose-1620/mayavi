# Changelog

Hand-written. Nothing lands here automatically; entries are added only when a release is declared.

Newest version first — the top entry is the current feature set, older releases follow below it.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-18

First working version: a local multi-agent runtime that routes one prompt into a small, medium, or large session and runs GGUF models one at a time behind a gated tool set.

### Routing

- Router GGUF emits effort/stakes fields (`stakes`, `needs_code_exec`, `file_ops`, `web_ops`, `mail_cal`, `intent`) and never names a tier, answers the user, or calls tools.
- `mapRoute` turns those fields into `small` | `medium` | `large`: high stakes or `needs_code_exec=yes` forces large, `file_ops=3+` or `web_ops=2+` gives medium, everything else is small.
- Unsure, missing, or malformed router JSON defaults cheap (small) instead of rounding up to large.
- Heuristic fallback covers a failed router load, and `--no-model` routes without touching weights.

### Sessions and committee

- Small runs one drafter. Medium adds two checkers plus a blackboard. Large runs an executor with builders, a blackboard, and always a sandbox.
- Large uses four unique builders from the USB library when present, and falls back to the Llama 3.2 3B + Qwen 3B pair otherwise.
- Blackboard kinds are `draft`, `critique`, `debug`, `vote`, and `rules`; only the factory may post `rules`, which pins `coding-rules.md` on every large run.
- `select_vote` prefers `vote`, then `draft`, then a worker's `final` text, and never surfaces factory `rules`, sandbox `debug`, or an empty/placeholder answer as the user-facing reply.
- One answer per run, printed as a Prompt / Response / Meta block (or `--json`). Tokens are not streamed, and an empty answer is labelled as such even on a clean exit.

### Sandbox and the keep folder

- Per-`run_id` jail under `sandboxes/`, restricted to `.py` / `.html` / `.css` / `.js`. Execution is `python <file.py>` inside the jail, timed, with the host environment stripped. One exclusive lock covers write, execute, and fetch.
- `sandbox_write` belongs to builders; `executeScriptInSandbox` and `sandbox_fetch` belong to the executor. `sandbox_fetch` is loopback-only.
- Every large run gets a keep folder at `outputs/<run_id>/`.
- All file writers stay locked on a large run until a script has actually executed and the committee votes **ship** by majority. An early write returns `ship_locked`.
- On unlock the factory copies the sandbox's source files and captured stdout (`result.txt`) into the keep folder, and remaps any later write into that same folder.
- `getResultsFromSandbox` returns `not_run` until something has executed, so the committee cannot vote on output that was never produced.
- Without a ship the sandbox is wiped at teardown, so a failed build leaves nothing durable behind.

### Tools and gating

- Files (`file_tools.py`): `search_dir`, `read_file`, `write_doc`, `write_pdf`, `write_json`, `append_file`, `mkdir`. Reads from `input/` and `outputs/`, writes to `outputs/` only, paged at five pages per call.
- Web (`web_scrape.py`): `get_url`, `post_url`, `resetSession`. http/https only, with loopback, private, and link-local addresses rejected as SSRF.
- Mail and calendar (`mailAndCalendar.py`): list/search/open mail, send and reply (never delete), calendars, events, free/busy. Manager agent only — drafter on small/medium, executor on large.
- The factory removes tools an agent should not have: `file_ops=0` hides readers and writers, `web_ops=0` hides scrape tools, `mail_cal=off` hides mail, and non-large runs see no sandbox. A hidden tool call returns `unknown_tool` and the model can still finish with `final`.
- Agents never import `executor.py`, `logger.py`, `models.py`, `google.py`, or `microsoft.py`; the runtime injects `agent_id` rather than trusting a model-supplied one.

### Files, paths, and safety

- `ALLOWED_PATHS` is `input/` plus `outputs/`; `BLOCKED_PATHS` always wins and covers repo source, `.env`, model directories, logs, `createdIndex`, OAuth token files, `sandboxes/`, and `state/`.
- Files that exist on disk but are absent from `createdIndex` cannot be overwritten, so agents cannot clobber user originals or patch this repo through file tools.
- Created files are tracked in `state/createdIndex.json`, which agents cannot read.
- Writes reject empty content and placeholder bodies.

### Models

- `models.json` pins role → repo/file/revision, all Q4_K_M GGUF.
- One model resident at a time via mmap, with a RAM check of file size × 1.2 plus a 2GB reserve before loading.
- Resolve order is USB (`MODELS_DIR`) when the file is present and RAM allows, then the backup directory, then an optional Hugging Face download gated behind `ID10T_HF_DOWNLOAD=1`.
- Two download sets: a ~7GB backup laptop set and a ~26GB USB set, fetched by scripts under `downloader-scripts/` that the runtime never imports.
- `checkAndUpdateModels` can refresh pins after a large teardown only, and is skipped unless downloads are enabled.

### Mail and calendar OAuth

- Google and Microsoft backends behind one agent-facing door, chosen with `--provider`.
- Browser consent (`Allow`) instead of mailbox passwords; consent happens before worker threads start.
- Tokens are written to `state/tokens/`, which is on the blocked list.
- Outbound bodies are scanned for tokens and JWTs, and a match is denied without echoing the secret.

### Logging

- One binary audit file per local calendar day under `state/logs/`.
- Every exported function logs once on return (`ok` or `fail`), including factory steps, tools, and route mapping. Spawn records bind `agent_name` to a GGUF filename.
- Transcripts, file bodies, mail bodies, and tokens are never stored.
- A failed log write only warns on small/medium runs with `mail_cal=off`; large, high-stakes, or mail/calendar work fails the function rather than proceeding unlogged.

### Configuration

- `.env` at the repo root, with relative paths resolved from the repo root rather than the working directory. `.env.example` carries no secrets.
- Knobs for model directories, workspace and output roots, private state, sandbox root, Hugging Face downloads, GPU layers, and OAuth clients.

### Tests

- Pytest suite over a temp tree with no real GGUF load and no browser OAuth, covering routing defaults, vote selection, tool gating, logging, file gates, SSRF, mail policy, sandbox execute and fetch, the keep folder and ship lock, and teardown for all three tiers.
- Session tests inject a stub generator; tool tests print the call and its JSON result.
