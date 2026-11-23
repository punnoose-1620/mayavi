"""Sequential coding committee: board sections, views, votes. Agents never import this.

Role prompts live in coding.prompts. The round loop lives in coding.run.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import config
from store import Agent, CommitteeBoard, CommitItem, CritiqueItem, Run, TestItem

VOTING_ROLES = ("manager", "coder", "tester", "critique", "evaluator")
COMMITTEE_ROLES = VOTING_ROLES + ("documenter",)

SECTION_ALIASES: dict[str, str] = {
    "targets": "features",
    "baselines": "features",
    "contract": "features",
    "job": "features",
    "non_goals": "features",
    "nongoals": "features",
    "goal": "features",
    "modules": "architecture",
    "design": "architecture",
    "sketch": "architecture",
    "layout": "architecture",
    "readme": "docs",
    "notes": "docs",
    "diff": "code",
    "paths": "code",
    "cases": "tests",
}

SECTION_WRITERS: dict[str, frozenset[str]] = {
    "coding_rules": frozenset({"factory", "manager"}),
    "features": frozenset({"manager"}),
    "architecture": frozenset({"manager"}),
    "code": frozenset({"coder"}),
    "tests": frozenset({"tester"}),
    "critiques": frozenset({"critique"}),
    "critique_scores": frozenset({"evaluator"}),
    "critique_status": frozenset({"manager"}),
    "docs": frozenset({"documenter"}),
}

VIEW_SECTIONS: dict[str, tuple[str, ...]] = {
    "manager": ("features", "architecture", "tests", "critiques", "commits", "phase"),
    "coder": ("features", "architecture", "code", "coding_rules"),
    "tester": ("features", "tests", "code"),
    "critique": ("features", "architecture", "code", "tests", "critiques"),
    "evaluator": ("features", "critiques", "tests"),
    "documenter": ("features", "architecture", "commits", "docs", "critiques"),
}

from coding.prompts import PHASE0_FACTORS, VOTE_QUESTION, system_prompt, user_payload

_VOTE_QUESTION = VOTE_QUESTION


def yes_count(votes: dict[str, str]) -> int:
    return sum(1 for role in VOTING_ROLES if str(votes.get(role) or "").lower() in {"yes", "y", "ship"})


def should_commit(votes: dict[str, str]) -> bool:
    return yes_count(votes) >= int(config.COMMITTEE_YES_FOR_COMMIT)


def should_push(commits_since_push: int) -> bool:
    return commits_since_push >= int(config.COMMITTEE_PUSH_EVERY)


def snapshot(board: CommitteeBoard) -> dict[str, Any]:
    return {
        "coding_rules": board.coding_rules,
        "features": board.features,
        "architecture": board.architecture,
        "code": board.code,
        "tests": [item.__dict__ for item in board.tests],
        "critiques": [item.__dict__ for item in board.critiques],
        "commits": [item.__dict__ for item in board.commits],
        "last_push": board.last_push,
        "docs": board.docs,
        "phase": board.phase,
        "round": board.round,
        "last_vote": dict(board.last_vote),
        "vote_open": board.vote_open,
        "phase_complete": board.phase_complete,
        "commits_since_push": board.commits_since_push,
    }


def _clip(text: str, cap: int) -> str:
    body = str(text or "")
    if len(body) <= cap:
        return body
    return body[: cap - 1] + "…"


def view_for(role: str, board: CommitteeBoard, cap: int | None = None) -> str:
    budget = int(cap or config.COMMITTEE_VIEW_CHARS)
    return _clip(_view_body(role, board), budget)


def view_pages(role: str, board: CommitteeBoard, size: int | None = None) -> list[str]:
    pages = chunk_text(_view_body(role, board), size)
    return pages or [""]


def _view_body(role: str, board: CommitteeBoard) -> str:
    keys = VIEW_SECTIONS.get(role) or ("features", "phase")
    chunks: list[str] = [f"phase={board.phase} round={board.round}"]
    if "features" in keys:
        chunks.append("## features, targets, baselines\n" + (board.features or "(empty)"))
    if "architecture" in keys:
        chunks.append("## architecture\n" + (board.architecture or "(empty)"))
    if "coding_rules" in keys:
        chunks.append("## coding rules\n" + (board.coding_rules or "(empty)"))
    if "code" in keys:
        chunks.append("## code (paths + last diff)\n" + (board.code or "(empty)"))
    if "tests" in keys:
        if board.tests:
            lines = [f"- {t.name}: {t.status} [{t.feature}] {t.detail}".rstrip() for t in board.tests]
            chunks.append("## tests\n" + "\n".join(lines))
        else:
            chunks.append("## tests\n(empty)")
    if "critiques" in keys:
        if board.critiques:
            lines = [
                f"- {c.item_id} [{c.status}] score={c.score or '-'}: {c.text}" for c in board.critiques
            ]
            chunks.append("## critiques\n" + "\n".join(lines))
        else:
            chunks.append("## critiques\n(empty)")
    if "commits" in keys:
        if board.commits:
            lines = [f"- {c.sha or 'n/a'} {c.message} {c.skipped}".rstrip() for c in board.commits[-8:]]
            chunks.append("## commits (last push: " + (board.last_push or "never") + ")\n" + "\n".join(lines))
        else:
            chunks.append("## commits\n(empty) last push: " + (board.last_push or "never"))
    if "docs" in keys:
        chunks.append("## docs\n" + (board.docs or "(empty)"))
    if "phase" in keys and board.last_vote:
        chunks.append("## last vote\n" + json.dumps(board.last_vote, ensure_ascii=False))
    return "\n\n".join(chunks)


def chunk_text(text: str, size: int | None = None) -> list[str]:
    body = str(text or "")
    if size is None:
        limit = max(400, int(config.COMMITTEE_CHUNK_CHARS))
    else:
        limit = max(1, int(size))
    if len(body) <= limit:
        return [body] if body else []
    return [body[i : i + limit] for i in range(0, len(body), limit)]


def apply_update(board: CommitteeBoard, role: str, section: str, content: Any) -> dict[str, Any]:
    section = SECTION_ALIASES.get(str(section or "").strip().lower(), str(section or "").strip())
    allowed = SECTION_WRITERS.get(section)
    if allowed is None:
        return {"ok": False, "error": "unknown_section"}
    if role not in allowed:
        return {"ok": False, "error": "role_denied", "section": section, "role": role}
    if section in {"features", "architecture", "coding_rules", "code", "docs"}:
        text = str(content or "")
        if not text.strip():
            return {"ok": True, "section": section, "skipped": "empty"}
        setattr(board, section, text)
        return {"ok": True, "section": section}
    if section == "tests":
        board.tests = _parse_tests(content)
    elif section == "critiques":
        board.critiques.extend(_parse_critiques(content, open_only=True))
    elif section == "critique_scores":
        _apply_scores(board, content)
    elif section == "critique_status":
        _apply_status(board, content)
    else:
        return {"ok": False, "error": "unknown_section"}
    return {"ok": True, "section": section}


def _parse_tests(content: Any) -> list[TestItem]:
    items: list[TestItem] = []
    if isinstance(content, list):
        raw = content
    elif isinstance(content, dict):
        raw = content.get("tests") or content.get("cases") or [content]
    else:
        raw = []
        for line in str(content or "").splitlines():
            line = line.strip().lstrip("-").strip()
            if not line:
                continue
            raw.append(line)
    for row in raw:
        if isinstance(row, dict):
            items.append(
                TestItem(
                    name=str(row.get("name") or row.get("id") or f"t{len(items)+1}"),
                    feature=str(row.get("feature") or ""),
                    status=str(row.get("status") or "pending"),
                    detail=str(row.get("detail") or ""),
                )
            )
        else:
            items.append(TestItem(name=str(row)[:120], status="pending"))
    return items


def _parse_critiques(content: Any, *, open_only: bool) -> list[CritiqueItem]:
    rows: list[Any]
    if isinstance(content, list):
        rows = content
    elif isinstance(content, dict):
        rows = content.get("critiques") or content.get("items") or [content]
    else:
        rows = [ln.strip().lstrip("-").strip() for ln in str(content or "").splitlines() if ln.strip()]
    out: list[CritiqueItem] = []
    for row in rows:
        if isinstance(row, dict):
            text = str(row.get("text") or row.get("body") or "")
            if not text.strip():
                continue
            out.append(
                CritiqueItem(
                    item_id=str(row.get("id") or row.get("item_id") or f"c-{uuid.uuid4().hex[:6]}"),
                    text=text.strip(),
                    score=str(row.get("score") or ""),
                    status="open" if open_only else str(row.get("status") or "open"),
                )
            )
        else:
            text = str(row).strip()
            if text:
                out.append(CritiqueItem(item_id=f"c-{uuid.uuid4().hex[:6]}", text=text, status="open"))
    return out


def _apply_scores(board: CommitteeBoard, content: Any) -> None:
    mapping: dict[str, str] = {}
    if isinstance(content, dict) and not any(k in content for k in ("id", "item_id")):
        mapping = {str(k): str(v) for k, v in content.items()}
    else:
        for item in _parse_critiques(content, open_only=False):
            mapping[item.item_id] = item.score or item.text
    for item in board.critiques:
        if item.item_id in mapping:
            item.score = mapping[item.item_id]


def _apply_status(board: CommitteeBoard, content: Any) -> None:
    mapping: dict[str, str] = {}
    if isinstance(content, dict) and "status" not in content:
        mapping = {str(k): str(v) for k, v in content.items()}
    elif isinstance(content, dict):
        mapping[str(content.get("id") or content.get("item_id") or "")] = str(content.get("status") or "")
    elif isinstance(content, list):
        for row in content:
            if isinstance(row, dict):
                mapping[str(row.get("id") or row.get("item_id") or "")] = str(row.get("status") or "")
    allowed = {"open", "discarded", "avoided", "implemented"}
    for item in board.critiques:
        nxt = mapping.get(item.item_id)
        if nxt and str(nxt).lower() in allowed:
            item.status = str(nxt).lower()


def record_vote(board: CommitteeBoard, role: str, vote: str) -> dict[str, Any]:
    if role not in VOTING_ROLES:
        return {"ok": False, "error": "no_vote"}
    mark = str(vote or "").strip().lower()
    if mark in {"y", "ship", "pass", "true"}:
        mark = "yes"
    if mark in {"n", "reject", "fail", "false"}:
        mark = "no"
    if mark not in {"yes", "no"}:
        return {"ok": False, "error": "bad_vote"}
    board.last_vote[role] = mark
    return {"ok": True, "role": role, "vote": mark}


def parse_committee_json(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    decoder = json.JSONDecoder()
    i = text.find("{")
    while i >= 0:
        try:
            obj, _end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            nxt = text.find("{", i + 1)
            i = nxt
            continue
        if isinstance(obj, dict):
            return obj
        nxt = text.find("{", i + 1)
        i = nxt
    return {}


def pick_model(use: str, fallbacks: tuple[str, ...]) -> str:
    import models

    return models.pick_role(use, fallbacks)


def infer_vote(text: str) -> str | None:
    blob = str(text or "").strip().lower()
    if not blob:
        return None
    first = re.split(r"[\s,.:;]+", blob, maxsplit=1)[0]
    if first in {"yes", "y", "ship", "pass", "true"}:
        return "yes"
    if first in {"no", "n", "reject", "fail", "false"}:
        return "no"
    if re.search(r'"vote"\s*:\s*"(yes|y|ship)"', blob):
        return "yes"
    if re.search(r'"vote"\s*:\s*"(no|n|reject)"', blob):
        return "no"
    return None


def ingest_output(run: Run, agent: Agent, parsed: dict[str, Any]) -> dict[str, Any]:
    import profile

    profile.collect(run, parsed)
    board = run.committee
    if board is None:
        return {"ok": False, "error": "no_board"}
    notes: list[str] = []
    update = parsed.get("board_update")
    if isinstance(update, dict):
        if "section" in update:
            notes.append(str(apply_update(board, agent.role, str(update.get("section")), update.get("content"))))
        else:
            feature_bits: list[str] = []
            for key, value in update.items():
                dest = SECTION_ALIASES.get(str(key).lower(), str(key))
                if dest == "features" and str(key).lower() != "features":
                    feature_bits.append(f"{key}: {value}")
                else:
                    notes.append(str(apply_update(board, agent.role, str(key), value)))
            if feature_bits:
                extra = "\n".join(feature_bits)
                if board.features:
                    board.features = board.features.rstrip() + "\n" + extra
                else:
                    notes.append(str(apply_update(board, agent.role, "features", extra)))
    if parsed.get("call_vote") and agent.role == "manager":
        board.vote_open = True
        notes.append("vote_open")
    if parsed.get("stop") and agent.role == "manager":
        board.stop = True
        notes.append("stop")
    vote = parsed.get("vote")
    if vote is None and (run.committee_stage or "") == "vote":
        vote = infer_vote(str(parsed.get("final") or ""))
    if vote is not None:
        notes.append(str(record_vote(board, agent.role, str(vote))))
    return {"ok": True, "notes": notes}


_COMMIT_DUP = re.compile(r"\s+")


def already_handled(board: CommitteeBoard, text: str) -> bool:
    needle = _COMMIT_DUP.sub(" ", text or "").strip().lower()
    if not needle:
        return False
    for item in board.critiques:
        blob = _COMMIT_DUP.sub(" ", f"{item.text} {item.status}").lower()
        if needle in blob and item.status in {"discarded", "implemented", "avoided"}:
            return True
    for item in board.commits:
        if needle in _COMMIT_DUP.sub(" ", item.message).lower():
            return True
    return False
