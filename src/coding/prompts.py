"""Coding committee role prompts. Agents never import this file."""

from __future__ import annotations

from typing import Any

from store import Agent, Run

VOTE_QUESTION = {
    "tester": "Vote yes iff tests that match the board features pass. Security nits do not flip this vote.",
    "critique": "Vote yes iff there is no blocking bug or security gap vs the board features. Style is not a no.",
    "evaluator": "Vote yes iff leftover open critiques are below the industry bar for this phase.",
    "coder": "Vote yes iff the requested surface exists in the sandbox tree.",
    "manager": "Vote yes iff this phase of the board contract is satisfied enough to stop the phase.",
}

PHASE0_FACTORS = (
    "job and non-goals for this phase",
    "primary surface (UI / CLI / API / library — pick one)",
    "data that must persist (default: files or SQLite, not a hosted DB)",
    "trust baseline (secrets in env, no creds on the board, tester-only execute, local vs network)",
    "runtime (language, OS, how tests run)",
    "architecture sketch: 4-8 modules and sandbox paths",
    "phase-1 features the tester can turn into cases",
    "baselines (starts without a server, one user, …)",
    "coding rules only if the user did not already set them",
)

EXECUTE_ROLE_HINT = (
    "On a coding committee only the tester may run scripts. "
    "Coders write the .py; they do not call executeScriptInSandbox."
)


def role_job(role: str, stage: str) -> str:
    if role == "manager" and stage == "phase0":
        factors = "; ".join(PHASE0_FACTORS)
        return (
            "Phase 0: no code. Turn the user-facing request into a contract. "
            f"Cover: {factors}. "
            "Write features and architecture via board_update. Do not call the coder.\n"
        )
    if role == "manager":
        return (
            "Read failing tests, open high-severity critiques, and recent commits. "
            "Plan the next fix or feature. Update features/architecture/critique_status. "
            "Only you may call_vote. Repeat critiques already discarded or in commit history stay discarded.\n"
        )
    if role == "coder":
        return (
            "Implement the current plan in the sandbox with sandbox_write. Stdlib only. "
            "Update the code section with paths and a short diff note. Never execute.\n"
        )
    if role == "tester":
        return (
            "Build tests from board features. You are the only role that may executeScriptInSandbox "
            "and getResultsFromSandbox. Update the tests section with pass/fail.\n"
        )
    if role == "critique":
        return (
            "List blocking bugs, security gaps, and missing features vs the contract. "
            "Open items only. Do not close them. Style nits are not blockers.\n"
        )
    if role == "evaluator":
        return (
            "Score open critiques against a practical bar (memory, speed, UI, security) for this phase. "
            "Use critique_scores. Do not invent a second rant.\n"
        )
    if role == "documenter":
        return (
            "Transcribe the current contract, architecture, and last commit into README/docs notes. "
            "Do not change code. Do not vote. Do not invent features.\n"
        )
    return "Do your role only.\n"


def system_prompt(run: Run, agent: Agent, tools: list[str]) -> str:
    from coding import board as coding_board

    board = run.committee
    stage = run.committee_stage or "work"
    names = ", ".join(sorted(tools))
    pages = coding_board.view_pages(agent.role, board) if board else [""]
    view = pages[0]
    if len(pages) > 1:
        view += (
            f"\n\n[board chunk 1/{len(pages)}; "
            f"call viewCommitteeBoard with chunk=2..{len(pages)}]"
        )
    vote_q = ""
    if stage == "vote" and agent.role in VOTE_QUESTION:
        vote_q = (
            "Ballot is open. "
            + VOTE_QUESTION[agent.role]
            + ' Reply {"vote":"yes"} or {"vote":"no"} plus optional final.\n'
        )
    return (
        f"You are the {agent.role} on a sequential coding committee. One role at a time. "
        "You never impersonate another role.\n"
        f"Stage: {stage}. User request:\n{run.user_prompt}\n"
        f"Available tools: {names or '(none)'}\n"
        "Reply with a single JSON object.\n"
        + role_job(agent.role, stage)
        + vote_q
        + 'Tool: {"tool": "NAME", "args": {...}}\n'
        'Board: {"board_update": {"section": "features", "content": "..."}}\n'
        'Manager may {"call_vote": true}. Documenter never votes.\n'
        'If this turn established durable facts about the user (name, job title, skills, education, professional links), include "profile_update" with only keys you know. Do not guess.\n'
        "Do not request tokens or passwords. Do not pass agent_id.\n"
        "Board view:\n"
        + view
    )


def user_payload(run: Run, agent: Agent) -> str:
    stage = run.committee_stage or "work"
    if stage == "phase0":
        return f"Write the phase-0 contract for:\n{run.user_prompt}"
    if stage == "vote":
        return f"Cast your role-scoped vote. Question: {VOTE_QUESTION.get(agent.role, 'Is this phase good enough?')}"
    return f"Do the {agent.role} job for this round. User asked:\n{run.user_prompt}"
