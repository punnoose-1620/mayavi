"""Factory-directed coding committee loop. Agents never import this file."""

from __future__ import annotations

import json
from typing import Any

import blackboard
import config
import git_tools
import logger
import sandbox
from coding import board as coding_board
from coding.roster import spawn
from store import Run


def rules_text() -> str:
    path = config.CODING_RULES_PATH
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def run_coding(run: Run) -> str:
    import executor

    executor.createKeepDir(run.run_id)
    sandbox.create(run.run_id)
    executor.createBlackBoard(run.run_id)
    executor.setBlackBoardRules(run.run_id, pin_coding_rules=True)
    from store import CommitteeBoard

    run.committee = CommitteeBoard(coding_rules=rules_text(), phase="0")
    if not executor._ops_needed(run.file_ops):  # noqa: SLF001
        run.file_ops = "1"
    blackboard.pin_context_card(run)
    executor._pin_web_digest(run)  # noqa: SLF001
    if run.mail_cal != "off":
        executor._connect_mail(run)  # noqa: SLF001
    names = spawn(run)
    executor.setSessionDetails(run.run_id)
    turn(run, names["manager"], "phase0")
    if run.committee and not str(run.committee.features or "").strip():
        run.committee.features = (run.user_prompt or run.intent or "phase 1").strip()
    if run.committee and not str(run.committee.architecture or "").strip():
        run.committee.architecture = "sandbox scripts (.py / .html / .css / .js)"
    run.committee.phase = "1"
    max_rounds = int(config.COMMITTEE_MAX_ROUNDS)
    for rnd in range(1, max_rounds + 1):
        run.committee.round = rnd
        if run.committee.stop or run.committee.phase_complete:
            break
        turn(run, names["coder"], "code")
        turn(run, names["tester"], "test")
        turn(run, names["critique"], "critique")
        turn(run, names["evaluator"], "evaluate")
        turn(run, names["manager"], "plan")
        if not run.committee.stop:
            run.committee.vote_open = True
        if run.committee.vote_open:
            ballot(run, names)
            run.committee.vote_open = False
            votes = run.committee.last_vote
            if coding_board.should_commit(votes):
                run.ship_unlocked = True
                sandbox.copy_out(run, summary=executor._keep_summary(run), agent_id=run.router_agent)  # noqa: SLF001
                who = names["manager"]
                if run.git_remote:
                    git_tools.git_login(agent_id=who)
                git_tools.git_commit(commit_message(run), agent_id=who)
                if run.git_remote and coding_board.should_push(run.committee.commits_since_push):
                    git_tools.git_push(agent_id=who)
                turn(run, names["documenter"], "document")
            if coding_board.yes_count(votes) == len(coding_board.VOTING_ROLES):
                run.committee.phase_complete = True
                break
        if run.committee.stop:
            break
    if run.git_remote and run.committee.commits_since_push and run.committee.stop:
        git_tools.git_push(agent_id=names["manager"])
    return user_answer(run)


def turn(run: Run, agent_name: str, stage: str) -> None:
    import executor

    if agent_name not in run.agents:
        return
    run.committee_stage = stage
    role = run.agents[agent_name].role
    rnd = run.committee.round if run.committee else 0
    logger.finish(
        event="factory",
        tool="committeeTurn",
        run_id=run.run_id,
        agent_name=agent_name,
        result={"ok": True, "role": role, "stage": stage, "round": rnd},
        level=run.level,
        stakes=run.stakes,
        mail_cal=run.mail_cal,
        summary=f"role={role} stage={stage} round={rnd}",
    )
    if stage in {"code", "test"}:
        sandbox.openSandbox(agent_id=agent_name)
    executor.createThread(agent_name)
    executor.startThread(agent_name)
    executor.endThread(agent_name)
    executor.deleteThread(agent_name)
    run.committee_stage = ""


def ballot(run: Run, names: dict[str, str]) -> None:
    if run.committee is None:
        return
    run.committee.last_vote = {}
    for role in coding_board.VOTING_ROLES:
        turn(run, names[role], "vote")


def commit_message(run: Run) -> str:
    board = run.committee
    feat = (board.features if board else "")[:80] or (run.intent or "phase")
    return f"committee r{board.round if board else 0}: {feat}"


def user_answer(run: Run) -> str:
    import executor

    if run.ship_unlocked:
        summary = executor._keep_summary(run)  # noqa: SLF001
        if summary:
            return summary
    board = run.committee
    if board and board.features:
        vote = json.dumps(board.last_vote, ensure_ascii=False) if board.last_vote else "{}"
        body = board.features.strip()
        if len(body) > 800:
            body = body[:799] + "…"
        return f"Committee phase {board.phase} round {board.round}.\nVote: {vote}\n{body}"
    latest = executor._latest_final(run)  # noqa: SLF001
    if latest and not protocol_blob(latest) and not executor._pointer_answer(latest):  # noqa: SLF001
        return latest
    return executor._unshipped_summary(run)  # noqa: SLF001


def protocol_blob(text: str | None) -> bool:
    body = str(text or "").strip()
    if not body.startswith("{"):
        return False
    parsed = coding_board.parse_committee_json(body)
    if parsed.get("board_update") or parsed.get("call_vote") or parsed.get("vote") is not None:
        return True
    if parsed.get("tool"):
        return True
    return False
