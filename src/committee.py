"""Compatibility shim. Sequential committee lives in coding/."""

from __future__ import annotations

from coding.board import (  # noqa: F401
    COMMITTEE_ROLES,
    SECTION_ALIASES,
    SECTION_WRITERS,
    VIEW_SECTIONS,
    VOTING_ROLES,
    already_handled,
    apply_update,
    chunk_text,
    infer_vote,
    ingest_output,
    parse_committee_json,
    pick_model,
    record_vote,
    should_commit,
    should_push,
    snapshot,
    system_prompt,
    user_payload,
    view_for,
    view_pages,
    yes_count,
)
from coding.prompts import PHASE0_FACTORS, VOTE_QUESTION

_VOTE_QUESTION = VOTE_QUESTION
