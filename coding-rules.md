# Coding rules (v1)

You are specifying hard limits on **what the committee may write and run** in the sandbox. v1 huge programming work is **web apps** only: Python API + HTML/CSS/JS UI. You (the human) inspect the UI later. The committee does **not** drive a browser or check GUI.

These rules apply on **every large (committee) run**, including high-stakes work that is not “a coding task.” The committee may always build code in the sandbox to process data. The factory must inject this document into **session details** and pin it on the **blackboard** before `startThread`. Agents read it via `viewSessionDetails` (full text) and the pinned blackboard `rules` message. They cannot edit it.

v2 (Flutter, Dart, Java, C#, mobile) is out of scope.

## Allowed files in the sandbox

Only these extensions: `.py`, `.html`, `.css`, `.js`. Anything else: `sandbox_write` fails.

## What “execute” means

- **Python** — `python <file.py>` under the sandbox root. This is the API / tests / one-shot processors.
- **HTML / CSS** — write only. Not executed.
- **JavaScript** — write as browser-side UI (or small `.js` helpers). v1 does **not** require `node` unless you later add it; default execute is Python.
- **No shell**, no `.exe`, no PowerShell, no bash, no other languages.

One `executeScriptInSandbox` at a time (exclusive mutex in `runtime.md`). Timeout. Cwd = sandbox. Host env stripped. **No network** except the process listening on **sandbox-bind localhost** for the app under test. No `pip` / `npm` install; only what the jail already has.

## Web app shape

- Python hosts **API endpoints**.
- HTML/CSS/JS call those endpoints (theory + fetch URLs in the JS). Layout is “good enough”; the human rebuilds UI later.
- Prove wiring **without a GUI**: tests in Python and/or `sandbox_fetch` to `http://127.0.0.1:<port>/...` (JSON/status). **Not** public `get_url` (that blocks localhost).

## `sandbox_fetch` (runtime, large only)

GET (optional POST) only to the sandbox loopback address and the port the executed app bound. Same paging/caps as other reads. Event-log host+port+status, not body. This is how the committee checks that UI-facing functions can hit the API.

## Keep vs wipe

The factory creates `outputs/<run_id>/` at the start of every large run. That folder is the keep tree.

The sandbox is a separate jail (`sandboxes/<run_id>/`) and is destroyed at teardown. On large runs, `write_doc` / `write_json` / `write_pdf` / `append_file` / `mkdir` stay locked until the executor has a successful `executeScriptInSandbox` **and** a majority of builders plus the executor have voted `ship` (not `reject`) on the blackboard. Then the factory copies allowed sandbox files (`.py`, `.html`, `.css`, `.js`) and stdout (`result.txt`) into the keep folder. After unlock, durable writes are forced into that same folder. Nothing in the jail enters createdIndex until that copy.

## Logging

`executeScriptInSandbox` and `sandbox_fetch` event-log like every exported function. No full program text in the log.

If this file conflicts with `runtime.md` on **what may run**, **this file wins**.
