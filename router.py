"""Router model prompt + script mapping. Models do not pick the tier."""

from __future__ import annotations

import json
import re
from typing import Any

import logger

ROUTER_SYSTEM = """You are the routing model. You do not answer the user. You only inspect the prompt and emit a structured plan so the script can pick a tier.

You are the smallest model in the system. Stay cheap and strict. If unsure about stakes, mark them low. If unsure about effort, round counts down. Greetings, chat, summaries, and casual how-to are low stakes.

Prefer a direct spoken answer. Count a tool family only when the user clearly needs it. Do not count file or web tools just because they exist. "hi", chat, and questions that can be answered from the model's own knowledge are file_ops 0, web_ops 0.

Output only these fields. Do not output small, medium, or large. Do not invent tools that are not listed. Do not output needs_code_exec. The operator chooses whether this is a coding task and whether live web search is allowed.

- file_ops: 0 | 1 | 2 | 3+
- web_ops: 0
- mail_cal: off | read | write
- stakes: low | high
- intent: one short sentence of what the user wants

file_ops is how many file tool calls the job needs (read, discovery, or write). Count a write only if the user asked to create, save, edit, or build a file (doc, pdf, csv, json, and similar). A folder discovery sweep that stays under the safety cap counts as one file op, not one op per file inside it. Do not count write_doc for a greeting or a spoken answer.

web_ops is always 0. Live search (search_web, get_url, post_url) is an operator control, not yours. A URL in the prompt is not permission to fetch it. Do not count web because they said search, google, look up, or pasted a link.

mail_cal is off unless the user clearly needs inbox or calendar. Use read for list/open/search/free-busy only. Use write only for send, reply, create, update, or cancel events.

High stakes: legal, official, contractual, policy, government, financial, medical, or something they will sign, file, send as official, or rely on as a record. Only mark high when that is clearly true. If unsure, mark low.

Low stakes: greetings, chat, personal, hobby, how-to, search, summaries, or casual troubleshooting. Default low.

Output a JSON object with exactly those fields.
"""

FILE_OPS = {"0", "1", "2", "3+"}
WEB_OPS = {"0", "1", "2+"}
YES_NO = {"yes", "no"}
MAIL = {"off", "read", "write"}
STAKES = {"low", "high"}
HIGH_STAKES_MARKS = (
    "legal",
    "contract",
    "clause",
    "official",
    "policy",
    "government",
    "medical",
    "financial",
    "sign this",
    "review this document",
    "compliance",
)
CODE_AGENT_MARKS = (
    "html",
    ".css",
    "stylesheet",
    ".js",
    "javascript",
    "typescript",
    "web page",
    "webpage",
    "landing page",
    "python script",
    "write a function",
    "write a class",
    "write a program",
    "code snippet",
    " python",
    "python ",
    "matrix",
    "todo",
    " cli",
    "```html",
    "```css",
    "```js",
    "```python",
)


def apply_user_controls(
    fields: dict[str, Any],
    *,
    coding: Any = None,
    git_remote: str | None = None,
    web: Any = None,
    gmail: Any = None,
    calendar: Any = None,
) -> dict[str, Any]:
    """Operator coding, web, Gmail, and Calendar flags win over the router."""
    import git_tools

    out = dict(fields)
    flag = coding if coding is not None else out.get("coding")
    is_coding = _flag(flag)
    out["coding"] = is_coding
    out["web"] = _flag(web if web is not None else out.get("web"))
    out["gmail"] = _flag(gmail if gmail is not None else out.get("gmail"))
    out["calendar"] = _flag(calendar if calendar is not None else out.get("calendar"))
    if not out["web"]:
        out["web_ops"] = "0"
    if is_coding:
        out["needs_code_exec"] = "yes"
        out["git_remote"] = git_tools.public_github_remote(git_remote if git_remote is not None else out.get("git_remote"))
    else:
        out["needs_code_exec"] = "no"
        out["git_remote"] = None
    out["mail_cal"] = "write" if out["gmail"] or out["calendar"] else "off"
    return out


def _flag(value: Any) -> bool:
    if value is True:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def looks_high_stakes(prompt: str) -> bool:
    text = str(prompt or "").lower()
    return any(mark in text for mark in HIGH_STAKES_MARKS)


EXECUTE_MARKS = (
    "sandbox",
    "run python",
    "run the code",
    "run this",
    "execute",
    "unit test",
    "test this",
    "in the jail",
)


def wants_code_agent(prompt: str) -> bool:
    """Hobby HTML/JS/snippet work. Does not select the coding committee."""
    text = str(prompt or "").lower()
    return any(mark in text for mark in CODE_AGENT_MARKS)


def wants_execute(prompt: str) -> bool:
    """They asked to run or test code. Still does not select the coding committee."""
    text = str(prompt or "").lower()
    return any(mark in text for mark in EXECUTE_MARKS)


def mapRoute(fields: dict[str, Any], run_id: str, agent_name: str) -> dict[str, Any]:
    controlled = apply_user_controls(fields)
    cleaned = normalize_fields(controlled)
    coding = bool(controlled.get("coding"))
    web = bool(controlled.get("web"))
    gmail = bool(controlled.get("gmail"))
    calendar = bool(controlled.get("calendar"))
    git_remote = controlled.get("git_remote") if coding else None
    if not web:
        cleaned["web_ops"] = "0"
    cleaned["mail_cal"] = "write" if gmail or calendar else "off"
    if coding:
        cleaned["needs_code_exec"] = "yes"
        level = "large"
        shape = "coding"
    elif cleaned["stakes"] == "high":
        cleaned["needs_code_exec"] = "no"
        level = "large"
        shape = "review"
    elif cleaned["file_ops"] == "3+":
        cleaned["needs_code_exec"] = "no"
        level = "medium"
        shape = "medium"
    else:
        cleaned["needs_code_exec"] = "no"
        level = "small"
        shape = "small"
    result = {
        **cleaned,
        "ok": True,
        "level": level,
        "shape": shape,
        "coding": coding,
        "git_remote": git_remote,
        "web": web,
        "gmail": gmail,
        "calendar": calendar,
    }
    return logger.finish(
        event="route",
        tool="mapRoute",
        run_id=run_id,
        agent_name=agent_name,
        result=result,
        level=level,
        stakes=cleaned["stakes"],
        mail_cal=cleaned["mail_cal"],
        summary=f"level={level} shape={shape} file_ops={cleaned['file_ops']} web_ops={cleaned['web_ops']}",
    )


def parse_router_output(text: str) -> dict[str, Any]:
    blob = None
    try:
        blob = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                blob = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                blob = None
    if not isinstance(blob, dict):
        blob = {}
        for key in ("file_ops", "web_ops", "needs_code_exec", "mail_cal", "stakes", "intent"):
            match = re.search(rf"{key}\s*[:=]\s*([^\n,}}]+)", text, re.I)
            if match:
                blob[key] = match.group(1).strip().strip("\"'")
    return normalize_fields(blob)


def normalize_fields(fields: dict[str, Any]) -> dict[str, Any]:
    file_ops = str(fields.get("file_ops", "0")).strip()
    web_ops = str(fields.get("web_ops", "0")).strip()
    needs = str(fields.get("needs_code_exec", "no")).strip().lower()
    mail = str(fields.get("mail_cal", "off")).strip().lower()
    stakes = str(fields.get("stakes", "low")).strip().lower()
    intent = str(fields.get("intent") or "").strip()
    if file_ops.isdigit() and int(file_ops) >= 3:
        file_ops = "3+"
    if web_ops.isdigit() and int(web_ops) >= 2:
        web_ops = "2+"
    if file_ops not in FILE_OPS:
        file_ops = "0"
    if web_ops not in WEB_OPS:
        web_ops = "0"
    if needs not in YES_NO:
        needs = "no"
    if mail not in MAIL:
        mail = "off"
    if stakes not in STAKES:
        stakes = "low"
    if needs == "yes":
        mail = "off"
    return {
        "file_ops": file_ops,
        "web_ops": web_ops,
        "needs_code_exec": needs,
        "mail_cal": mail,
        "stakes": stakes,
        "intent": intent or "unspecified",
    }


def lift_ops_from_prompt(prompt: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Keep live 1.5B routing from dropping file tools or inflating code-exec."""
    text = prompt.lower()
    out = dict(fields)
    if _read_existing_work(text):
        out["needs_code_exec"] = "no"
        if str(out.get("file_ops", "0")).strip() in {"", "0", "no", "off"}:
            out["file_ops"] = "1"
    write_marks = (
        "write_doc",
        "write_pdf",
        "write_json",
        "append_file",
        "save that",
        "save this",
        "create a new text",
        "create that file",
        "create that pdf",
        "create that json",
        ".txt",
        ".pdf",
        ".csv",
        ".docx",
        ".json",
    )
    if any(mark in text for mark in write_marks) and str(out.get("file_ops", "0")) == "0":
        out["file_ops"] = "1"
    if "three" in text and ("resume" in text or "files" in text):
        out["file_ops"] = "3+"
    if _flag(out.get("web")):
        if "https://example.com" in text and "https://example.org" in text:
            out["web_ops"] = "2+"
        if "https://" in text or "http://" in text or "get_url" in text:
            if str(out.get("web_ops", "0")) == "0":
                out["web_ops"] = "1"
        if any(mark in text for mark in ("search the web", "google ", "look up")):
            if str(out.get("web_ops", "0")) == "0":
                out["web_ops"] = "1"
    else:
        out["web_ops"] = "0"
    if str(out.get("needs_code_exec", "no")).lower() == "yes":
        if "sandbox" not in text and "run python" not in text and "execute" not in text and "matrix" not in text:
            if any(mark in text for mark in ("write_json", "write_doc", "write_pdf", "append_file")):
                out["needs_code_exec"] = "no"
    if "not legal" in text or "low stakes" in text or "casual personal" in text:
        out["stakes"] = "low"
    if not _flag(out.get("coding")) and not looks_high_stakes(text):
        out["stakes"] = "low"
    return out


def _read_existing_work(text: str) -> bool:
    """True when they want a summary/read of code already on disk, not a new sandbox build."""
    saved = any(
        mark in text
        for mark in (
            "outputs",
            "saved",
            "keep folder",
            "code that was built",
            "code that was saved",
            "code created",
            "created code",
            "the code",
            "files you",
            "what you saved",
            "already saved",
        )
    )
    wants_read = any(
        mark in text
        for mark in (
            "summar",
            "read it",
            "read the",
            "explain",
            "how it works",
            "how they work",
            "what did you",
            "tell me about",
            "review the code",
        )
    )
    wants_build = any(
        mark in text
        for mark in (
            "write a program",
            "write and run",
            "build a",
            "create a program",
            "in the sandbox",
            "run python",
            "implement",
        )
    )
    return saved and wants_read and not wants_build


def heuristic_route(prompt: str) -> dict[str, Any]:
    text = prompt.lower()
    stakes = "high" if looks_high_stakes(text) else "low"
    needs = "no"
    if any(mark in text for mark in ("write a program", "python app", "web app", "run code", "sandbox", "build an api")):
        needs = "yes"
    mail = "off"
    if needs != "yes" and any(mark in text for mark in ("email", "gmail", "outlook", "calendar", "inbox", "meeting")):
        mail = "write" if any(mark in text for mark in ("send", "reply", "create event", "cancel")) else "read"
    file_ops = "0"
    write_marks = (
        "write a doc",
        "write a document",
        "save as",
        "save this",
        "create a pdf",
        "write a pdf",
        "write a csv",
    )
    if any(mark in text for mark in ("file", "folder", "pdf", "document", "docx", "csv", "xlsx") + write_marks):
        file_ops = "3+" if any(mark in text for mark in ("folder", "all files", "documents in")) else "1"
    if _read_existing_work(text):
        needs = "no"
        if file_ops == "0":
            file_ops = "1"
    web_ops = "0"
    return normalize_fields(
        {
            "file_ops": file_ops,
            "web_ops": web_ops,
            "needs_code_exec": needs,
            "mail_cal": mail,
            "stakes": stakes,
            "intent": prompt.strip()[:200],
        }
    )
