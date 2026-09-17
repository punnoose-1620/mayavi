"""Router model prompt + script mapping. Models do not pick the tier."""

from __future__ import annotations

import json
import re
from typing import Any

import logger

ROUTER_SYSTEM = """You are the routing model. You do not answer the user. You only inspect the prompt and emit a structured plan so the script can pick a tier.

You are the smallest model in the system. Stay cheap and strict. If unsure about stakes, mark them low. If unsure about effort, round counts down. Greetings, chat, summaries, and casual how-to are low stakes.

Output only these fields. Do not output small, medium, or large. Do not invent tools that are not listed.

- file_ops: 0 | 1 | 2 | 3+
- web_ops: 0 | 1 | 2+
- needs_code_exec: yes | no
- mail_cal: off | read | write
- stakes: low | high
- intent: one short sentence of what the user wants

file_ops is how many file tool calls the job needs (read or discovery). A folder discovery sweep that stays under the safety cap counts as one file op, not one op per file inside it.

web_ops is how many web scrape tool calls the job needs. v1 calls are get_url / post_url (agent-built URLs). Dedicated search APIs are v2.

needs_code_exec is yes only if the job cannot finish without writing and running custom code in the closed sandbox. Using the provided PDF/doc writer is not code execution. If unsure, mark no.

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
    if any(mark in text for mark in ("file", "folder", "pdf", "document", "docx", "csv", "xlsx")):
        file_ops = "3+" if any(mark in text for mark in ("folder", "all files", "documents in")) else "1"
    web_ops = "0"
    if any(mark in text for mark in ("http://", "https://", "website", "scrape", "url")):
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
