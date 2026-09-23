"""Router model prompt + script mapping. Models do not pick the tier."""

from __future__ import annotations

import json
import re
from typing import Any

import logger

ROUTER_SYSTEM = """You are the routing model. You do not answer the user. You only inspect the prompt and emit a structured plan so the script can pick a tier.

You are the smallest model in the system. Stay cheap and strict. If unsure about stakes, mark them low. If unsure about effort, round counts down. Greetings, chat, summaries, and casual how-to are low stakes.

Prefer a direct spoken answer. Count a tool family only when the user clearly needs it. Do not count file, web, or code tools just because they exist. "hi", chat, and questions that can be answered from the model's own knowledge are file_ops 0, web_ops 0, needs_code_exec no.

Output only these fields. Do not output small, medium, or large. Do not invent tools that are not listed.

- file_ops: 0 | 1 | 2 | 3+
- web_ops: 0 | 1 | 2+
- needs_code_exec: yes | no
- mail_cal: off | read | write
- stakes: low | high
- intent: one short sentence of what the user wants

file_ops is how many file tool calls the job needs (read, discovery, or write). Count a write only if the user asked to create, save, edit, or build a file (doc, pdf, csv, json, and similar). A folder discovery sweep that stays under the safety cap counts as one file op, not one op per file inside it. Do not count write_doc for a greeting or a spoken answer.

web_ops is how many web tool calls the job needs. v1 calls are search_web, get_url, and post_url. Count web if they asked to search the web, google something, look up a live fact, or fetch/scrape a URL. Search then one page fetch is 1. Several pages is 2+. Casual "how do I" questions that the model can answer from training are 0. Do not count web because the word search appears in a file-search or code-search request.

needs_code_exec is yes only if the job cannot finish without writing and running new custom code in the closed sandbox. Using the provided PDF/doc writer is not code execution. Reading, summarizing, or explaining code that was already saved under outputs/ is a file read: file_ops at least 1, needs_code_exec no. Do not mark yes because they mentioned tests, matrices, or an earlier build. If unsure, mark no.

mail_cal is off unless the user clearly needs inbox or calendar. Default off when needs_code_exec is yes. Use read for list/open/search/free-busy only. Use write only for send, reply, create, update, or cancel events. Coding tasks must not get schedule access.

High stakes: legal, official, contractual, policy, government, financial, medical, or something they will sign, file, send as official, or rely on as a record. Only mark high when that is clearly true. If unsure, mark low.

Low stakes: greetings, chat, personal, hobby, how-to, search, summaries, or casual troubleshooting. Default low.

Output a JSON object with exactly those fields.
"""

FILE_OPS = {"0", "1", "2", "3+"}
WEB_OPS = {"0", "1", "2+"}
YES_NO = {"yes", "no"}
MAIL = {"off", "read", "write"}
STAKES = {"low", "high"}


def mapRoute(fields: dict[str, Any], run_id: str, agent_name: str) -> dict[str, Any]:
    cleaned = normalize_fields(fields)
    if cleaned["stakes"] == "high":
        level = "large"
    elif cleaned["needs_code_exec"] == "yes":
        level = "large"
    elif cleaned["file_ops"] == "3+" or cleaned["web_ops"] == "2+":
        level = "medium"
    else:
        level = "small"
    result = {**cleaned, "ok": True, "level": level}
    return logger.finish(
        event="route",
        tool="mapRoute",
        run_id=run_id,
        agent_name=agent_name,
        result=result,
        level=level,
        stakes=cleaned["stakes"],
        mail_cal=cleaned["mail_cal"],
        summary=f"level={level} file_ops={cleaned['file_ops']} web_ops={cleaned['web_ops']}",
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
    if "https://example.com" in text and "https://example.org" in text:
        out["web_ops"] = "2+"
    if "https://" in text or "http://" in text or "get_url" in text:
        if str(out.get("web_ops", "0")) == "0":
            out["web_ops"] = "1"
    if any(mark in text for mark in ("search the web", "google ", "look up")):
        if str(out.get("web_ops", "0")) == "0":
            out["web_ops"] = "1"
    if str(out.get("needs_code_exec", "no")).lower() == "yes":
        if "sandbox" not in text and "run python" not in text and "execute" not in text and "matrix" not in text:
            if any(mark in text for mark in ("write_json", "write_doc", "write_pdf", "append_file")):
                out["needs_code_exec"] = "no"
    if "not legal" in text or "low stakes" in text or "casual personal" in text:
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
    stakes = "low"
    high_marks = (
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
    if any(mark in text for mark in high_marks):
        stakes = "high"
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
    if any(mark in text for mark in ("http://", "https://", "website", "scrape", "url", "google", "look up", "search the web")):
        web_ops = "2+" if "several" in text or "multiple" in text else "1"
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
