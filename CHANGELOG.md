# Changelog

Hand-written. Nothing lands here automatically; entries are added only when a release is declared.

Newest version first — the top entry is the current feature set, older releases follow below it.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-09-28

Large runs split into two loops. **Coding** is an operator control (CLI `--code`, UI checkbox), not a router guess. High stakes without coding restores the builders + executor **review** committee. Coding plus high stakes stays sequential.

### Routing

- The router no longer emits `needs_code_exec`. It still decides `stakes`, `file_ops`, `web_ops`, `mail_cal`, and `intent`.
- Operator coding → sequential committee (`shape=coding`). Else high stakes → review (`shape=review`). Else `file_ops=3+` or `web_ops=2+` → medium. Else small.
- Coding forces `mail_cal=off`. File/web gating is unchanged.
- The factory clamps router `stakes=high` unless the prompt matches legal/official/medical/financial marks. A flashy HTML page stays **small**.
- Small/medium HTML/JS/snippet prompts pick a **code-tagged** drafter. They do not open a sandbox. The operator coding flag is still the only way into the sequential committee.

### Coding committee

- Roles, one at a time: manager (phase-0 contract, then plans) → coder → tester → critique → evaluator → vote. Documenter transcribes after a commit and does not vote.
- Shared **board** with locked writers: coding rules, features/targets/baselines, architecture, code (paths + last diff), tests, critiques (open/score/status), commits + last push, docs.
- Each agent sees a **view** of the board, not the whole dump. Long views are **chunked** for 4096-token workers (`viewCommitteeBoard` pages).
- Votes are role-scoped. ≥4/5 copies the sandbox to keep and **commits**. 5/5 marks the phase complete. **Push every 5 commits** (or on stop) only when a valid GitHub URL was given. `COMMITTEE_MAX_ROUNDS` caps the loop.
- Tester is the only coding role that executes. Coder is the only coding role that `sandbox_write`s.
- `models.json` `use` tags include `manage`, `test`, `critique`, `evaluate`, `document`. The picker skips a GGUF that fails the RAM check so a 14B miss falls through to 7B/8B or the 3B backup.
- `--no-model` drives the same sequential loop with stubs.
- If phase 0 does not land a contract, the factory seeds features from the user prompt. Empty board updates do not wipe a filled section.
- If a GGUF template rejects `system`, that text is folded into the first user message.

### Review committee

- High stakes, coding off: keep folder, blackboard, three builders plus an executor. **No sandbox.** Writers (`write_doc` / PDF / JSON) go to the keep folder immediately.
- Majority blackboard **ship** vote records that the keep folder shipped. No git tools.

### GitHub remote

- UI GitHub field appears only when coding is selected. CLI `--repo https://github.com/owner/repo`.
- Empty or anything other than that public GitHub shape hides `git_login` from the schema. Keep-folder commits still run locally.
- `git_login` / commit / push keep `GH_TOKEN` in process (HTTP extraHeader, never in the remote URL or tool result). Agents never see credentials. The factory does not open a browser. Keep-folder commits use a one-shot `git -c user.*` identity, not global git config.

### Chat UI artifacts

- Bot replies render as Markdown. Raw HTML in the answer is escaped. Fenced `html` blocks and full HTML documents become **View HTML page** on that reply (`GET /html`, CSP, no scripts). The session tape still stores the raw answer.
- PDFs a run wrote under `outputs/` appear under that bot reply (icon, filename, **Save to PDF**), not next to the prompt. `/keep` may serve those PDFs (and still `SUMMARY.md`).
- A structured `profile_update` on a reply shows **Save to board**. Confirm writes `state/profile.json`. The factory does not guess profile fields from prose.
- Each browser stores a UUID in `localStorage`. Chat history lives in `state/ui-session/<uuid>/` (`session.jsonl`, `html/`, `meta.jsonl`). Starting the server does not rotate those tapes. Peer IP, User-Agent, and language are appended to `meta.jsonl` for later analytics and are not used to look up a session.

Small and medium sessions stay one/three agents. HTML/JS/snippet prompts on those tiers pick a code-tagged drafter without a sandbox.

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
