"""Factory/router runtime. Agents never import this file."""

from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

import blackboard
import committee
import config
import git_tools
import google_backend
import logger
import mailAndCalendar
import models
import profile
import router
import runtime
import store
import web_scrape
from store import Agent, Run

import file_tools

BUILDER_ROLES = ("builder_llama", "builder_qwen", "builder_mistral", "builder_gemma")
BACKUP_BUILDERS = ("builder_llama", "builder_qwen")
WRITE_TOOL_NAMES = {"write_doc", "write_file", "write_pdf", "write_json", "append_file", "mkdir"}
_LANGUAGE_MARKS = (
    "translate",
    "rephrase",
    "rewrite",
    "resume",
    "cover letter",
    "proofread",
    "grammar",
    "paraphrase",
    "into swedish",
    "into english",
)


def mint_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:16]}"


def createAgent(
    run_id: str,
    role: str,
    model_role: str,
    parent_agent: str | None = None,
) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        return _factory("createAgent", None, "script", {"ok": False, "error": "no_run"})
    name = f"agt_{role}_{uuid.uuid4().hex[:8]}"
    resolved = models.resolveModel(model_role)
    filename = resolved.get("filename") or models.expected_filename(model_role)
    if resolved.get("ok") and resolved.get("root"):
        run.used_model_root = resolved["root"]
    agent = Agent(
        agent_name=name,
        role=role,
        model_role=model_role,
        model=filename,
        run_id=run_id,
        parent_agent=parent_agent,
    )
    store.register_agent(run, agent)
    logger.writeSpawnLog(
        run_id=run_id,
        agent_name=name,
        model=filename,
        role=role,
        parent_agent=parent_agent,
        level=run.level,
        stakes=run.stakes,
        mail_cal=run.mail_cal,
    )
    return _factory(
        "createAgent",
        run,
        name,
        {"ok": True, "agent_name": name, "role": role, "model": filename},
    )


def deleteAgent(agent_name: str) -> dict[str, Any]:
    run = store.run_for_agent(agent_name)
    if run is None:
        return _factory("deleteAgent", None, agent_name, {"ok": False, "error": "no_agent"})
    store.drop_agent(agent_name)
    return _factory("deleteAgent", run, agent_name, {"ok": True, "agent_name": agent_name})


def createThread(agent_name: str) -> dict[str, Any]:
    run, agent, err = _agent(agent_name)
    if err:
        return _factory("createThread", run, agent_name, err)
    agent.thread_state = "created"
    return _factory("createThread", run, agent_name, {"ok": True, "agent_name": agent_name})


def startThread(agent_name: str) -> dict[str, Any]:
    run, agent, err = _agent(agent_name)
    if err:
        return _factory("startThread", run, agent_name, err)
    if run.level in {"medium", "large"} and not (run.rules_frozen and run.session_frozen):
        return _factory("startThread", run, agent_name, {"ok": False, "error": "not_frozen"})
    if run.level == "large" and run.sandbox_path is not None:
        runtime.openSandbox(agent_id=agent_name)
    agent.thread_state = "started"
    result = _run_agent_loop(run, agent)
    return _factory("startThread", run, agent_name, result)


def endThread(agent_name: str) -> dict[str, Any]:
    run, agent, err = _agent(agent_name)
    if err:
        return _factory("endThread", run, agent_name, err)
    agent.thread_state = "ended"
    return _factory("endThread", run, agent_name, {"ok": True, "agent_name": agent_name})


def deleteThread(agent_name: str) -> dict[str, Any]:
    run, agent, err = _agent(agent_name)
    if err:
        return _factory("deleteThread", run, agent_name, err)
    agent.thread_state = "deleted"
    return _factory("deleteThread", run, agent_name, {"ok": True, "agent_name": agent_name})


def createSandbox(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        return _factory("createSandbox", None, "script", {"ok": False, "error": "no_run"})
    path = (config.SANDBOX_ROOT / run_id).resolve()
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    run.sandbox_path = path
    return _factory("createSandbox", run, run.router_agent or "script", {"ok": True, "path": str(path)})


def createKeepDir(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        return _factory("createKeepDir", None, "script", {"ok": False, "error": "no_run"})
    path = _keep_dir(run)
    path.mkdir(parents=True, exist_ok=True)
    run.keep_path = path
    return _factory("createKeepDir", run, run.router_agent or "script", {"ok": True, "path": str(path)})


def deleteSandbox(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        return _factory("deleteSandbox", None, "script", {"ok": False, "error": "no_run"})
    runtime._kill_sandbox_proc(run)  # noqa: SLF001
    path = run.sandbox_path
    try:
        if path is not None and path.exists():
            shutil.rmtree(path)
        run.sandbox_path = None
        return _factory("deleteSandbox", run, run.router_agent or "script", {"ok": True})
    except Exception as exc:
        return _factory("deleteSandbox", run, run.router_agent or "script", {"ok": False, "error": type(exc).__name__})


def createBlackBoard(run_id: str) -> dict[str, Any]:
    return blackboard.create_board(run_id)


def setBlackBoardRules(run_id: str, *, pin_coding_rules: bool = False) -> dict[str, Any]:
    return blackboard.set_rules(run_id, pin_coding_rules=pin_coding_rules)


def setSessionDetails(run_id: str) -> dict[str, Any]:
    run = store.get_run(run_id)
    if run is None:
        return _factory("setSessionDetails", None, "script", {"ok": False, "error": "no_run"})
    coding = _coding_rules_text() if run.coding else ""
    details = {
        "run_id": run.run_id,
        "blackboard_id": run.run_id if run.blackboard else None,
        "frozen_rules": True,
        "coding_rules": coding,
        "agents": [
            {"agent_name": a.agent_name, "role": a.role, "model_role": a.model_role}
            for a in run.agents.values()
        ],
        "sandbox_id": run.run_id if run.sandbox_path else None,
        "keep_path": str(run.keep_path) if run.keep_path else None,
        "may_execute": [
            a.agent_name for a in run.agents.values() if run.coding and a.role == "tester"
        ],
        "may_write": [
            a.agent_name
            for a in run.agents.values()
            if a.role in ({"coder"} if run.coding else {"builder", "executor"})
        ],
        "mail_cal": run.mail_cal,
        "provider": run.provider,
        "account_email": run.account_email,
        "timezone": run.timezone,
        "level": run.level,
        "stakes": run.stakes,
        "intent": run.intent,
        "user_prompt": run.user_prompt,
        "thread_id": run.thread_id,
        "thread_card": blackboard.context_card(run.thread) if run.thread else "",
    }
    dest = config.SESSION_DIR / f"{run.run_id}.json"
    dest.write_text(json.dumps(details, indent=2), encoding="utf-8")
    run.session_path = dest
    run.session_frozen = True
    return _factory("setSessionDetails", run, run.router_agent or "script", {"ok": True, "path": str(dest)})


def connectToGoogle() -> dict[str, Any]:
    run = _any_run()
    if run is None:
        return _factory("connectToGoogle", None, "script", {"ok": False, "error": "no_run"})
    if run.mail_cal == "off":
        return _factory("connectToGoogle", run, run.router_agent or "script", {"ok": True, "skipped": True})
    result = google_backend.connectToGoogle()
    if result.get("ok") and result.get("handle"):
        run.oauth["google"] = result["handle"]
        run.provider = run.provider or "google"
        run.account_email = result.get("email") or run.account_email
    return _factory("connectToGoogle", run, run.router_agent or "script", {"ok": bool(result.get("ok")), "error": result.get("error"), "email": result.get("email")})


def connectToMicrosoft() -> dict[str, Any]:
    import microsoft as microsoft_backend

    run = _any_run()
    if run is None:
        return _factory("connectToMicrosoft", None, "script", {"ok": False, "error": "no_run"})
    if run.mail_cal == "off":
        return _factory("connectToMicrosoft", run, run.router_agent or "script", {"ok": True, "skipped": True})
    result = microsoft_backend.connectToMicrosoft()
    if result.get("ok") and result.get("handle"):
        run.oauth["microsoft"] = result["handle"]
        run.provider = run.provider or "microsoft"
        run.account_email = result.get("email") or run.account_email
    return _factory("connectToMicrosoft", run, run.router_agent or "script", {"ok": bool(result.get("ok")), "error": result.get("error"), "email": result.get("email")})


def viewBlackBoard(run_id: str) -> dict[str, Any]:
    return blackboard.view_board(run_id)


def run_session(
    prompt: str,
    fields: dict[str, Any],
    *,
    generate_fn: Callable[..., str] | None = None,
    provider: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Map router fields to a tier, spawn the factory, return one user-facing answer."""
    from router import lift_ops_from_prompt, mapRoute

    run_id = mint_run_id()
    run = Run(
        run_id=run_id,
        user_prompt=prompt,
        intent=str(fields.get("intent") or ""),
        generate_fn=generate_fn,
        provider=provider,
        timezone="UTC",
    )
    store.put_run(run)
    router = createAgent(run_id, "router", "router", parent_agent=None)
    if not router.get("ok"):
        return {"ok": False, "error": "router_spawn_failed", "run_id": run_id}
    run.router_agent = router["agent_name"]
    mapped = mapRoute(lift_ops_from_prompt(prompt, fields), run_id=run_id, agent_name=run.router_agent)
    run.level = mapped["level"]
    run.stakes = mapped["stakes"]
    run.mail_cal = mapped["mail_cal"]
    run.file_ops = mapped["file_ops"]
    run.web_ops = mapped["web_ops"]
    run.needs_code_exec = mapped["needs_code_exec"]
    run.intent = mapped["intent"]
    run.shape = str(mapped.get("shape") or run.level)
    run.coding = bool(mapped.get("coding"))
    run.git_remote = mapped.get("git_remote") or None
    run.web = bool(mapped.get("web"))
    blackboard.bind_thread(run, thread_id)
    if blackboard.shipped_keep_paths(run.thread):
        if not _ops_needed(run.file_ops):
            run.file_ops = "1"
    if run.web:
        import web_research

        web_research.gather(run)
    answer = None
    try:
        if run.level == "small":
            answer = ""
            if run.web and str(getattr(run, "web_digest", "") or "").strip():
                import web_research

                answer = web_research.synthesize(run)
            if not answer:
                answer = _run_small(run)
        elif run.level == "medium":
            answer = _run_medium(run)
        else:
            answer = _run_large(run)
        answer = _user_answer(run, answer)
        blackboard.distill(run, answer)
    finally:
        _teardown(run)
        if run.level == "large":
            models.checkAndUpdateModels(run.used_model_root)
    return {
        "ok": True,
        "run_id": run_id,
        "level": run.level,
        "stakes": run.stakes,
        "mail_cal": run.mail_cal,
        "intent": run.intent,
        "answer": answer,
        "thread_id": run.thread_id,
        "summary_url": keep_summary_url(run),
        "notices": list(run.notices),
        "committee": _committee_meta(run),
        "shape": run.shape,
        "coding": run.coding,
        "git_remote": run.git_remote,
        "web": run.web,
        "pdfs": _pdf_artifacts(run),
        "profile_update": profile.merge(run.profile_updates),
    }


ANSWER_KINDS = {"vote", "draft"}


def select_vote(run: Run) -> str:
    """Pick the user-facing answer. Never return factory rules, sandbox debug, or pointer words."""
    if run.level == "large" and run.ship_unlocked:
        latest = _latest_final(run)
        if latest and not _pointer_answer(latest):
            return latest
        summary = _keep_summary(run)
        if summary:
            return summary
    if run.blackboard is not None:
        votes = [
            body
            for body in blackboard.protocol_bodies(run, "vote")
            if _usable_answer(body) and blackboard.vote_side(body) is None and not _pointer_answer(body)
        ]
        if votes:
            counts: dict[str, int] = {}
            for body in votes:
                counts[body] = counts.get(body, 0) + 1
            return max(counts.items(), key=lambda kv: kv[1])[0]
        drafts = [
            body
            for body in blackboard.protocol_bodies(run, "draft")
            if _usable_answer(body) and blackboard.vote_side(body) is None and not _pointer_answer(body)
        ]
        if drafts:
            return drafts[-1]
    latest = _latest_final(run)
    if latest and not _pointer_answer(latest):
        return latest
    if run.level == "large":
        return _large_fallback_answer(run)
    return latest if latest and not _pointer_answer(latest) else ""


def _latest_final(run: Run) -> str:
    preferred: list[str] = []
    others: list[str] = []
    for agent in run.agents.values():
        if agent.role == "router":
            continue
        finals = [m["content"] for m in agent.history if m.get("role") == "final" and _usable_answer(m.get("content"))]
        if not finals:
            continue
        if agent.role in {"executor", "drafter"}:
            preferred.append(finals[-1])
        else:
            others.append(finals[-1])
    if preferred:
        return preferred[-1]
    if others:
        return others[-1]
    return ""


def _agent_posted_answer(run: Run, agent_name: str) -> bool:
    if run.blackboard is None:
        return False
    return any(
        m.get("agent_id") == agent_name and m.get("kind") in ANSWER_KINDS
        for m in run.blackboard.messages
    )


def _promote_final_to_board(run: Run, agent: Agent, text: str) -> None:
    body = (text or "").strip()
    if run.level not in {"medium", "large"} or run.blackboard is None or not _usable_answer(body):
        return
    if _agent_posted_answer(run, agent.agent_name):
        return
    kind = "draft" if agent.role in {"drafter", "builder"} else "vote"
    runtime.sendMessageToBlackboard(body, kind, agent_id=agent.agent_name)


def _work_kind(run: Run) -> str:
    if str(run.needs_code_exec or "").lower() == "yes":
        return "code"
    text = f"{run.user_prompt or ''} {run.intent or ''}"
    if router.wants_code_agent(text):
        return "code"
    if any(mark in text.lower() for mark in _LANGUAGE_MARKS):
        return "language"
    return "plan"


def _committee_roles(run: Run) -> tuple[str, list[str]]:
    kind = _work_kind(run)
    extra = 0
    if run.level == "medium":
        extra = 2
    elif run.level == "large":
        extra = 3 if kind == "code" else 2
    return _lead_and_support(kind, extra)


def _lead_and_support(kind: str, extra: int) -> tuple[str, list[str]]:
    roles = models.roles_for_use(kind)
    if not roles:
        return "executor", list(BACKUP_BUILDERS)[: max(0, extra)]
    lead = roles[0]
    support: list[str] = []
    for name in roles[1:]:
        if name != lead and name not in support:
            support.append(name)
        if len(support) >= extra:
            return lead, support
    for other in ("plan", "language", "code"):
        if other == kind:
            continue
        for name in models.roles_for_use(other):
            if name != lead and name not in support:
                support.append(name)
            if len(support) >= extra:
                return lead, support
    if extra and len(support) < extra:
        for name in BACKUP_BUILDERS:
            if name != lead and name not in support:
                support.append(name)
            if len(support) >= extra:
                break
    return lead, support[: max(0, extra)]


def _run_small(run: Run) -> str:
    lead, _support = _committee_roles(run)
    created = createAgent(run.run_id, "drafter", lead, parent_agent=run.router_agent)
    drafter = created["agent_name"]
    if run.mail_cal != "off":
        _connect_mail(run)
        setSessionDetails(run.run_id)
    createThread(drafter)
    startThread(drafter)
    endThread(drafter)
    deleteThread(drafter)
    finals = [m["content"] for m in run.agents[drafter].history if m.get("role") == "final" and _usable_answer(m.get("content"))]
    return finals[-1] if finals else _fallback_final(run.agents[drafter])


def _run_medium(run: Run) -> str:
    lead, support = _committee_roles(run)
    if len(support) < 2:
        support = list(BACKUP_BUILDERS)
    drafter = createAgent(run.run_id, "drafter", lead, parent_agent=run.router_agent)["agent_name"]
    c1 = createAgent(run.run_id, "checker", support[0], parent_agent=run.router_agent)["agent_name"]
    c2 = createAgent(run.run_id, "checker", support[1], parent_agent=run.router_agent)["agent_name"]
    createBlackBoard(run.run_id)
    setBlackBoardRules(run.run_id)
    blackboard.pin_context_card(run)
    _pin_web_digest(run)
    if run.mail_cal != "off":
        _connect_mail(run)
    setSessionDetails(run.run_id)
    for name in (drafter, c1, c2, drafter, drafter, c1, c2):
        createThread(name)
        startThread(name)
        endThread(name)
        deleteThread(name)
    return select_vote(run)


def _run_large(run: Run) -> str:
    if run.coding:
        return _run_coding(run)
    return _run_review(run)


def _run_coding(run: Run) -> str:
    createKeepDir(run.run_id)
    createSandbox(run.run_id)
    createBlackBoard(run.run_id)
    setBlackBoardRules(run.run_id, pin_coding_rules=True)
    run.committee = store.CommitteeBoard(coding_rules=_coding_rules_text(), phase="0")
    if not _ops_needed(run.file_ops):
        run.file_ops = "1"
    blackboard.pin_context_card(run)
    _pin_web_digest(run)
    if run.mail_cal != "off":
        _connect_mail(run)
    names = _spawn_committee(run)
    setSessionDetails(run.run_id)
    _committee_turn(run, names["manager"], "phase0")
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
        _committee_turn(run, names["coder"], "code")
        _committee_turn(run, names["tester"], "test")
        _committee_turn(run, names["critique"], "critique")
        _committee_turn(run, names["evaluator"], "evaluate")
        _committee_turn(run, names["manager"], "plan")
        if not run.committee.stop:
            run.committee.vote_open = True
        if run.committee.vote_open:
            _committee_ballot(run, names)
            run.committee.vote_open = False
            votes = run.committee.last_vote
            if committee.should_commit(votes):
                run.ship_unlocked = True
                _copy_sandbox_out(run)
                who = names["manager"]
                if run.git_remote:
                    git_tools.git_login(agent_id=who)
                git_tools.git_commit(_committee_commit_message(run), agent_id=who)
                if run.git_remote and committee.should_push(run.committee.commits_since_push):
                    git_tools.git_push(agent_id=who)
                _committee_turn(run, names["documenter"], "document")
            if committee.yes_count(votes) == len(committee.VOTING_ROLES):
                run.committee.phase_complete = True
                break
        if run.committee.stop:
            break
    if run.git_remote and run.committee.commits_since_push and run.committee.stop:
        git_tools.git_push(agent_id=names["manager"])
    return _committee_user_answer(run)


def _run_review(run: Run) -> str:
    """High-stakes, not coding: builders + executor, keep-folder writers, no sandbox."""
    createKeepDir(run.run_id)
    createBlackBoard(run.run_id)
    setBlackBoardRules(run.run_id, pin_coding_rules=False)
    if not _ops_needed(run.file_ops):
        run.file_ops = "1"
    blackboard.pin_context_card(run)
    _pin_web_digest(run)
    if run.mail_cal != "off":
        _connect_mail(run)
    _lead, support = _lead_and_support("plan", 3)
    exec_model = committee.pick_model("code", ("executor", "builder_coder", "builder_qwen"))
    exec_name = createAgent(run.run_id, "executor", exec_model, parent_agent=run.router_agent)["agent_name"]
    builders: list[str] = []
    models_cycle = list(support) or list(BACKUP_BUILDERS)
    while len(builders) < 3:
        model = models_cycle[len(builders) % len(models_cycle)]
        builders.append(
            createAgent(run.run_id, "builder", model, parent_agent=run.router_agent)["agent_name"]
        )
    setSessionDetails(run.run_id)
    order = builders + [exec_name] + builders[:2] + [exec_name] + [builders[0], exec_name]
    for name in order:
        createThread(name)
        startThread(name)
        endThread(name)
        deleteThread(name)
    if run.ship_unlocked:
        _run_ship_summary(run, exec_name)
    return select_vote(run)


def _spawn_committee(run: Run) -> dict[str, str]:
    picks = {
        "manager": committee.pick_model("manage", ("builder_qwen", "builder_llama", "executor")),
        "coder": committee.pick_model("code", ("executor", "builder_coder", "builder_qwen")),
        "tester": committee.pick_model("test", ("router", "builder_llama", "executor")),
        "critique": committee.pick_model("critique", ("builder_gemma", "builder_llama", "builder_qwen")),
        "evaluator": committee.pick_model("evaluate", ("router", "builder_llama")),
        "documenter": committee.pick_model("document", ("builder_llama", "builder_qwen", "router")),
    }
    names: dict[str, str] = {}
    for role, model_role in picks.items():
        created = createAgent(run.run_id, role, model_role, parent_agent=run.router_agent)
        names[role] = created["agent_name"]
    return names


def _committee_turn(run: Run, agent_name: str, stage: str) -> None:
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
        runtime.openSandbox(agent_id=agent_name)
    createThread(agent_name)
    startThread(agent_name)
    endThread(agent_name)
    deleteThread(agent_name)
    run.committee_stage = ""


def _committee_ballot(run: Run, names: dict[str, str]) -> None:
    if run.committee is None:
        return
    run.committee.last_vote = {}
    for role in committee.VOTING_ROLES:
        _committee_turn(run, names[role], "vote")


def _committee_commit_message(run: Run) -> str:
    board = run.committee
    feat = (board.features if board else "")[:80] or (run.intent or "phase")
    return f"committee r{board.round if board else 0}: {feat}"


def _protocol_blob(text: str | None) -> bool:
    body = str(text or "").strip()
    if not body.startswith("{"):
        return False
    parsed = committee.parse_committee_json(body)
    if parsed.get("board_update") or parsed.get("call_vote") or parsed.get("vote") is not None:
        return True
    if parsed.get("tool"):
        return True
    return False


def _committee_user_answer(run: Run) -> str:
    if run.ship_unlocked:
        summary = _keep_summary(run)
        if summary:
            return summary
    board = run.committee
    if board and board.features:
        vote = json.dumps(board.last_vote, ensure_ascii=False) if board.last_vote else "{}"
        body = board.features.strip()
        if len(body) > 800:
            body = body[:799] + "…"
        return f"Committee phase {board.phase} round {board.round}.\nVote: {vote}\n{body}"
    latest = _latest_final(run)
    if latest and not _protocol_blob(latest) and not _pointer_answer(latest):
        return latest
    return _unshipped_summary(run)


def _teardown(run: Run) -> None:
    # A leftover jail is a leak, so agent cleanup must never be able to skip deleteSandbox.
    try:
        names = [n for n, a in list(run.agents.items()) if a.role != "router"]
        for name in names:
            agent = run.agents.get(name)
            if agent and agent.thread_state not in {"ended", "deleted", "none"}:
                endThread(name)
                deleteThread(name)
            if name in run.agents:
                deleteAgent(name)
        if run.level == "large":
            _refresh_ship_lock(run)
    finally:
        leaked = False
        if run.sandbox_path is not None:
            leaked = not deleteSandbox(run.run_id).get("ok")
        if run.router_agent and run.router_agent in run.agents:
            deleteAgent(run.router_agent)
        if run.session_path and run.session_path.exists():
            run.session_path.unlink()
        if leaked:
            raise RuntimeError("sandbox_leak")


def _connect_mail(run: Run) -> None:
    out = connectToMicrosoft() if run.provider == "microsoft" else connectToGoogle()
    if not out.get("ok"):
        run.notices.append(f"mail_connect_failed:{out.get('error') or 'unknown'}")


def _pin_web_digest(run: Run) -> None:
    if not getattr(run, "web", False) or not str(getattr(run, "web_digest", "") or "").strip():
        return
    import web_research

    web_research.pin(run)


def _run_agent_loop(run: Run, agent: Agent) -> dict[str, Any]:
    tools = _tools_for(run, agent)
    system = _system_prompt(run, agent, tools)
    user = run.user_prompt
    if run.committee is not None:
        user = committee.user_payload(run, agent)
    digest = str(getattr(run, "web_digest", "") or "").strip()
    if digest:
        user = "Live-search notes (cite these URLs):\n" + digest[:1800] + "\n\nUser request:\n" + user
    if run.summarize_keep and run.keep_path is not None:
        user = (
            f"The build shipped to {run.keep_path}. "
            "Use search_dir and read_file on that folder, then emit a final summary: "
            "what was completed, architecture, a short description of each file, and the save path. "
            "Do not vote. Do not execute. Do not write files."
        )
    agent.history.append({"role": "system", "content": system})
    agent.history.append({"role": "user", "content": user})
    max_steps = 5 if run.committee is not None else 8
    final = ""
    for _ in range(max_steps):
        raw = _generate(run, agent, agent.history)
        for blob in _extract_json_objects(raw):
            if isinstance(blob, dict):
                profile.collect(run, blob)
        if run.committee is not None:
            blobs = [b for b in _extract_json_objects(raw) if isinstance(b, dict)]
            if blobs:
                for blob in blobs:
                    committee.ingest_output(run, agent, blob)
            else:
                committee.ingest_output(run, agent, committee.parse_committee_json(raw))
        items = _parse_all_model_output(raw)
        tools_this = [p for p in items if p.get("tool")]
        for parsed in tools_this:
            result = _dispatch_tool(run, agent, parsed["tool"], parsed.get("args") or {})
            agent.history.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {"tool": parsed["tool"], "args": parsed.get("args") or {}},
                        ensure_ascii=False,
                    ),
                }
            )
            agent.history.append({"role": "tool", "content": json.dumps(_public_result(result), ensure_ascii=False)})
            _refresh_ship_lock(run)
        if tools_this:
            continue
        text = ""
        for parsed in items:
            cand = str(parsed.get("final") or "").strip()
            if cand and _usable_answer(cand):
                text = cand
                break
        if not text:
            leftover = (raw or "").strip()
            if leftover and not items and _usable_answer(leftover):
                text = leftover
            elif leftover and run.committee is not None:
                parsed_c = committee.parse_committee_json(leftover)
                cand = str(parsed_c.get("final") or "").strip()
                if cand and _usable_answer(cand):
                    text = cand
        if text:
            final = text
            agent.history.append({"role": "final", "content": final})
            _promote_final_to_board(run, agent, final)
            _refresh_ship_lock(run)
            break
    if not final:
        final = _fallback_final(agent)
        if final:
            agent.history.append({"role": "final", "content": final})
            _promote_final_to_board(run, agent, final)
            _refresh_ship_lock(run)
    return {"ok": True, "agent_name": agent.agent_name, "final": bool(final)}


def _model_unavailable_text(error: str) -> str:
    if error == "ram":
        return "Not enough free RAM to load the worker GGUF. Close other apps and try again."
    if error == "llama_cpp_missing":
        return "llama-cpp-python is not installed in this Python environment. Re-run install.ps1."
    if error == "not_found":
        return "Local model is not available. Download GGUF files and set MODELS_DIR or BACKUP_MODELS_DIR."
    return f"Local model could not be loaded ({error})."


def _fallback_final(agent: Agent) -> str:
    last_error = ""
    for msg in reversed(agent.history):
        if msg.get("role") != "tool":
            continue
        try:
            blob = json.loads(msg.get("content") or "")
        except json.JSONDecodeError:
            continue
        if not isinstance(blob, dict):
            continue
        if blob.get("ok"):
            text = blob.get("text")
            if text and _usable_answer(str(text)):
                return str(text).strip()
            continue
        err = str(blob.get("error") or "").strip()
        if err and not last_error:
            last_error = err
    if last_error:
        return _tool_error_text(last_error)
    return ""


def _tool_error_text(err: str) -> str:
    if err in {"http_401", "http_403", "forbidden", "accessNotConfigured", "ipRefererBlocked", "ipBlocked"}:
        return "Web search was denied. Check SERPAPI_API_KEY or SCRAPERAPI_API_KEY, then try again."
    if err == "not_configured":
        return "Web search is not configured. Set SERPAPI_API_KEY or SCRAPERAPI_API_KEY."
    if err == "quota":
        return "Web search quota was exceeded. Try again later."
    if err == "empty_query":
        return "Search needed a query."
    return f"The last tool failed ({err})."


def _generate(run: Run, agent: Agent, history: list[dict[str, str]]) -> str:
    if run.generate_fn is not None:
        return run.generate_fn(run, agent, history)
    loaded = models.loadModel(agent.model_role)
    if not loaded.get("ok"):
        err = str(loaded.get("error") or "unavailable")
        run.notices.append(f"model_unavailable:{err}")
        return json.dumps({"final": _model_unavailable_text(err)})
    try:
        messages = _prepare_messages(history)
        out = models.generate(agent.model_role, messages=messages, agent_name=agent.agent_name)
        return out.get("text") or json.dumps({"final": "empty model output"})
    finally:
        models.unloadModel()


def _prepare_messages(history: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep llama.cpp under n_ctx after long PDF/tool dumps."""
    msgs: list[dict[str, str]] = []
    for m in history:
        role = m.get("role") if m.get("role") in {"system", "user", "assistant"} else "user"
        content = str(m.get("content") or "")
        if len(content) > 3000:
            content = content[:3000] + "…"
        msgs.append({"role": role, "content": content})
    if len(msgs) <= 12:
        return msgs
    return msgs[:2] + msgs[-10:]


_POINTER_WORDS = {"saved", "shipped", "ship", "reject", "final", "draft", "vote", "ok", "done"}


def _pointer_answer(text: str | None) -> bool:
    body = re.sub(r"[.!?,;:]+$", "", str(text or "").strip().lower()).strip()
    return body in _POINTER_WORDS


def _user_answer(run: Run, answer: str | None) -> str:
    """Last gate before the UI/CLI see a reply. Pointer words never leave a large run."""
    text = str(answer or "").strip()
    if run.level == "large" and (not text or _pointer_answer(text) or _protocol_blob(text)):
        return _large_fallback_answer(run)
    if not text:
        text = "The run finished without a usable answer."
    if not run.coding:
        text = _finish_off_coding(run, text)
    return text


_UNTESTED = "This code is not tested; it was not executed because Coding is not selected."
_CANNOT_TEST = (
    "I cannot test or run this without Coding selected. "
    "Turn on Coding (or pass --code) to use the sandbox."
)


def off_coding_draft(run: Run) -> str:
    """Viable snippet when Coding is off. Stubs and thin live answers use this."""
    prompt = f"{run.user_prompt or ''} {run.intent or ''}"
    if router.wants_execute(prompt):
        return (
            f"{_CANNOT_TEST}\n\n"
            "Example (not executed):\n\n"
            "```python\nprint('hello')\n```\n"
        )
    text = (run.user_prompt or "").lower()
    if "html" in text or "flashy" in text or "landing" in text or "javascript" in text or "webpage" in text or "web page" in text:
        lang = "html"
        body = _FLASHY_HTML if ("flashy" in text or "html" in text) and "landing" not in text else _LANDING_HTML
        if "landing" in text or "javascript" in text:
            body = _LANDING_HTML
        return f"```{lang}\n{body.rstrip()}\n```\n\n{_UNTESTED}\n"
    if "class" in text or "todo" in text:
        return f"```python\n{_TODO_CLASS.rstrip()}\n```\n\n{_UNTESTED}\n"
    if "matrix" in text:
        return f"```python\n{_MATRIX.rstrip()}\n```\n\n{_UNTESTED}\n"
    if "cli" in text:
        return f"```python\n{_HELLO_CLI.rstrip()}\n```\n\n{_UNTESTED}\n"
    return f"```python\n{_HELLO_FN.rstrip()}\n```\n\n{_UNTESTED}\n"


def _finish_off_coding(run: Run, text: str) -> str:
    prompt = f"{run.user_prompt or ''} {run.intent or ''}"
    if router.wants_execute(prompt):
        if _thin_code_answer(text):
            return off_coding_draft(run).strip()
        if "cannot test" not in text.lower() and "coding" not in text.lower():
            return text.rstrip() + "\n\n" + _CANNOT_TEST
        return text
    if router.wants_code_agent(prompt) or _work_kind(run) == "code":
        if _thin_code_answer(text):
            return off_coding_draft(run).strip()
        if "not tested" not in text.lower() and "not executed" not in text.lower():
            return text.rstrip() + "\n\n" + _UNTESTED
        return text
    return text


def _thin_code_answer(text: str) -> bool:
    body = str(text or "").strip()
    if len(body) < 40:
        return True
    lowered = body.lower()
    if "(no local model)" in lowered:
        return True
    if "```" in body or "<html" in lowered or "def " in body or "class " in body:
        return False
    return True


_FLASHY_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Flashy</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: conic-gradient(from 0.15turn, #ff2d95, #5b8def, #00e5a8, #ff2d95);
      animation: hue 8s linear infinite; color: #fff; font-family: system-ui, sans-serif; }
    @keyframes hue { to { filter: hue-rotate(360deg); } }
    h1 { text-shadow: 0 0 28px #fff; }
  </style>
</head>
<body>
  <h1>Flashy</h1>
</body>
</html>
"""

_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Landing</title>
  <style>
    body { margin: 0; font-family: system-ui, sans-serif; background: #0f172a; color: #e2e8f0; }
    main { max-width: 40rem; margin: 12vh auto; padding: 0 1.5rem; }
    button { background: #38bdf8; color: #0f172a; border: 0; padding: 0.6rem 1rem; font-weight: 700; cursor: pointer; }
  </style>
</head>
<body>
  <main>
    <h1>Hello</h1>
    <p>A small landing page.</p>
    <button id="go" type="button">Click</button>
  </main>
  <script>
    document.getElementById("go").addEventListener("click", () => { alert("hi"); });
  </script>
</body>
</html>
"""

_HELLO_FN = '''def hello(name: str = "world") -> str:
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(hello())
'''

_HELLO_CLI = '''import argparse

parser = argparse.ArgumentParser(description="hello CLI")
parser.add_argument("name", nargs="?", default="world")
args = parser.parse_args()
print(f"hello {args.name}")
'''

_TODO_CLASS = '''class TodoList:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, text: str) -> None:
        self.items.append(text)

    def done(self, index: int) -> str:
        return self.items.pop(index)


if __name__ == "__main__":
    box = TodoList()
    box.add("write tests")
    print(box.items)
'''

_MATRIX = '''def matmul(a: list[list[int]], b: list[list[int]]) -> list[list[int]]:
    n, m, p = len(a), len(a[0]), len(b[0])
    out = [[0] * p for _ in range(n)]
    for i in range(n):
        for k in range(m):
            for j in range(p):
                out[i][j] += a[i][k] * b[k][j]
    return out


if __name__ == "__main__":
    print(matmul([[1, 2], [3, 4]], [[5, 6], [7, 8]]))
'''


def _usable_answer(text: str | None) -> bool:
    body = str(text or "").strip()
    if not body:
        return False
    if _protocol_blob(body):
        return False
    lowered = body.lower()
    if lowered in {
        "unknown_tool",
        "empty_content",
        "path_denied",
        "type_error",
        "not_in_index",
        "bad_name",
        "failed",
        "json_shape",
        "role_denied",
        "level_denied",
        "ship_locked",
        "not_run",
        "...",
        "…",
    }:
        return False
    return not _is_tool_dump(body) and not _is_sandbox_dump(body)


def _is_sandbox_dump(text: str | None) -> bool:
    body = str(text or "")
    lowered = body.lower()
    if body.lstrip().startswith("exit_code=") or "\n-- stdout --\n" in body or "\n-- stderr --\n" in body:
        return True
    if "can't open file" in lowered and "sandboxes" in lowered:
        return True
    return False


def _is_tool_dump(text: str) -> bool:
    body = str(text or "").lstrip()
    if body.startswith('{"tool"') or body.startswith('{ "tool"'):
        return True
    if body.startswith('{"final"') or body.startswith('{ "final"'):
        return True
    blobs = _extract_json_objects(text)
    if not blobs:
        return False
    first = blobs[0]
    if not isinstance(first, dict):
        return False
    if first.get("tool") and not first.get("final"):
        return True
    return "final" in first and not str(first.get("final") or "").strip()


def _parse_all_model_output(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    blobs = _extract_json_objects(text)
    if not blobs:
        return [{"final": text}] if text else []
    items: list[dict[str, Any]] = []
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        if blob.get("tool"):
            items.append({"tool": blob["tool"], "args": blob.get("args") or {}})
        elif blob.get("final"):
            items.append({"final": str(blob["final"])})
    return items


def _parse_model_output(raw: str) -> dict[str, Any]:
    items = _parse_all_model_output(raw)
    return items[0] if items else {}


def _extract_json(text: str) -> Any:
    objs = _extract_json_objects(text)
    return objs[0] if objs else None


def _extract_json_objects(text: str) -> list[Any]:
    decoder = json.JSONDecoder()
    objs: list[Any] = []
    i = 0
    n = len(text or "")
    while i < n:
        while i < n and text[i].isspace():
            i += 1
        if i >= n:
            break
        if text[i] != "{":
            nxt = text.find("{", i)
            if nxt < 0:
                break
            i = nxt
        try:
            obj, end = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            break
        objs.append(obj)
        i = end
    return objs


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _exec_timeout(value: Any) -> int:
    """A model may ask for a shorter run, never a longer one than the configured cap."""
    limit = int(config.EXECUTE_TIMEOUT)
    if value is None:
        return limit
    return max(1, min(_as_int(value, limit), limit))


def _ops_needed(value: str | None) -> bool:
    return str(value or "0").strip() not in {"", "0", "no", "off"}


def _tools_for(run: Run, agent: Agent) -> dict[str, Callable[..., Any]]:
    aid = agent.agent_name
    tools: dict[str, Callable[..., Any]] = {}
    if _ops_needed(run.file_ops):
        tools.update(
            {
                "search_dir": lambda **kw: file_tools.search_dir(agent_id=aid, **kw),
                "read_file": lambda **kw: file_tools.read_file(agent_id=aid, **kw),
            }
        )
        if _writers_open(run) and not run.summarize_keep:
            tools.update(
                {
                    "write_doc": lambda **kw: file_tools.write_doc(agent_id=aid, **kw),
                    "write_pdf": lambda **kw: file_tools.write_pdf(agent_id=aid, **kw),
                    "write_json": lambda **kw: file_tools.write_json(agent_id=aid, **kw),
                    "append_file": lambda **kw: file_tools.append_file(agent_id=aid, **kw),
                    "mkdir": lambda **kw: file_tools.mkdir(agent_id=aid, **kw),
                }
            )
            tools["write_file"] = tools["write_doc"]
    if run.web:
        tools.update(
            {
                "search_web": lambda **kw: web_scrape.search_web(agent_id=aid, **kw),
                "get_url": lambda **kw: web_scrape.get_url(agent_id=aid, **kw),
                "post_url": lambda **kw: web_scrape.post_url(agent_id=aid, **kw),
                "resetSession": lambda **kw: web_scrape.resetSession(agent_id=aid, **kw),
            }
        )
    if run.level in {"medium", "large"}:
        tools.update(
            {
                "viewSessionDetails": lambda **kw: runtime.viewSessionDetails(agent_id=aid),
                "sendMessageToBlackboard": lambda **kw: runtime.sendMessageToBlackboard(
                    str(kw.get("body") or kw.get("message") or kw.get("text") or kw.get("content") or ""),
                    str(kw.get("kind") or "critique"),
                    agent_id=aid,
                ),
                "viewBlackboardMessages": lambda **kw: runtime.viewBlackboardMessages(
                    n=_as_int(kw.get("n", kw.get("count", 20)), 20),
                    agent_id=aid,
                ),
            }
        )
    if run.coding and not run.summarize_keep:
        tools["openSandbox"] = lambda **kw: runtime.openSandbox(agent_id=aid)
        tools["sandbox_read"] = lambda **kw: runtime.sandbox_read(
            path=str(kw.get("path") or kw.get("file") or ""),
            start=_as_int(kw.get("start", 1), 1),
            end=_as_int(kw.get("end", 1), 1),
            agent_id=aid,
        )
        tools["getResultsFromSandbox"] = lambda **kw: runtime.getResultsFromSandbox(
            start=_as_int(kw.get("start", 1), 1),
            end=_as_int(kw.get("end", 1), 1),
            agent_id=aid,
        )
        if agent.role in {"builder", "coder"}:
            tools["sandbox_write"] = lambda **kw: runtime.sandbox_write(
                path=str(kw.get("path") or kw.get("file") or kw.get("filename") or ""),
                content=str(kw.get("content") or kw.get("text") or kw.get("code") or ""),
                agent_id=aid,
            )
        if agent.role in {"executor", "tester"}:
            tools["executeScriptInSandbox"] = lambda **kw: runtime.executeScriptInSandbox(
                path=str(kw.get("path") or kw.get("file") or ""),
                timeout=_exec_timeout(kw.get("timeout")),
                agent_id=aid,
            )
            tools["sandbox_fetch"] = lambda **kw: runtime.sandbox_fetch(
                url=str(kw.get("url") or ""),
                method=str(kw.get("method") or "GET"),
                body=kw.get("body"),
                start=_as_int(kw.get("start", 1), 1),
                end=_as_int(kw.get("end", 1), 1),
                agent_id=aid,
            )
    if run.committee is not None:
        tools["updateBoard"] = lambda **kw: _tool_update_board(run, agent, kw)
        tools["viewCommitteeBoard"] = lambda **kw: _tool_view_board(run, agent, kw)
        if agent.role == "manager":
            tools["callVote"] = lambda **kw: _tool_call_vote(run, agent)
            if run.git_remote:
                tools["git_login"] = lambda **kw: git_tools.git_login(agent_id=aid)
    if run.mail_cal != "off" and _mail_manager(run, agent):
        for name in (
            "listMails",
            "searchMails",
            "openMail",
            "sendMail",
            "replyMail",
            "listCalendars",
            "listCalendarEvents",
            "openCalendarEvent",
            "createCalendarEvent",
            "updateCalendarEvent",
            "cancelCalendarEvent",
            "findFreeBusy",
        ):
            tools[name] = lambda name=name, **kw: getattr(mailAndCalendar, name)(agent_id=aid, **kw)
    return tools


def _mail_manager(run: Run, agent: Agent) -> bool:
    if run.committee is not None:
        return agent.role == "manager"
    if run.level == "large":
        return agent.role == "executor"
    return agent.role == "drafter"


def _dispatch_tool(run: Run, agent: Agent, name: str, args: dict[str, Any]) -> dict[str, Any]:
    tools = _tools_for(run, agent)
    fn = tools.get(name)
    if fn is None:
        error = _unknown_tool_error(run, agent, name)
        if error == "role_denied" and name == "executeScriptInSandbox":
            _pin_execute_role_hint(run)
        return logger.finish(
            event="tool",
            tool=str(name or "unknown"),
            run_id=run.run_id,
            agent_name=agent.agent_name,
            result={"ok": False, "error": error},
            level=run.level,
            stakes=run.stakes,
            mail_cal=run.mail_cal,
            summary=f"{error} name={name}",
        )
    cleaned = _tool_args(name, args)
    try:
        return fn(**cleaned)
    except TypeError as exc:
        return logger.finish(
            event="tool",
            tool=str(name),
            run_id=run.run_id,
            agent_name=agent.agent_name,
            result={"ok": False, "error": str(exc)},
            level=run.level,
            stakes=run.stakes,
            mail_cal=run.mail_cal,
            summary="type_error",
        )


def _tool_update_board(run: Run, agent: Agent, kw: dict[str, Any]) -> dict[str, Any]:
    if run.committee is None:
        return logger.finish(
            event="tool",
            tool="updateBoard",
            run_id=run.run_id,
            agent_name=agent.agent_name,
            result={"ok": False, "error": "no_board"},
        )
    section = str(kw.get("section") or kw.get("kind") or "")
    content = kw.get("content") if "content" in kw else kw.get("body") or kw.get("text")
    result = committee.apply_update(run.committee, agent.role, section, content)
    return logger.finish(
        event="tool",
        tool="updateBoard",
        run_id=run.run_id,
        agent_name=agent.agent_name,
        result=result,
    )


def _tool_view_board(run: Run, agent: Agent, kw: dict[str, Any]) -> dict[str, Any]:
    if run.committee is None:
        return logger.finish(
            event="tool",
            tool="viewCommitteeBoard",
            run_id=run.run_id,
            agent_name=agent.agent_name,
            result={"ok": False, "error": "no_board"},
        )
    pages = committee.view_pages(agent.role, run.committee)
    total = len(pages) or 1
    chunk = max(1, min(_as_int(kw.get("chunk", kw.get("n", 1)), 1), total))
    return logger.finish(
        event="tool",
        tool="viewCommitteeBoard",
        run_id=run.run_id,
        agent_name=agent.agent_name,
        result={"ok": True, "chunk": chunk, "total": len(pages), "view": pages[chunk - 1] if pages else ""},
    )


def _tool_call_vote(run: Run, agent: Agent) -> dict[str, Any]:
    if run.committee is None or agent.role != "manager":
        return logger.finish(
            event="tool",
            tool="callVote",
            run_id=run.run_id,
            agent_name=agent.agent_name,
            result={"ok": False, "error": "role_denied"},
        )
    run.committee.vote_open = True
    return logger.finish(
        event="tool",
        tool="callVote",
        run_id=run.run_id,
        agent_name=agent.agent_name,
        result={"ok": True, "vote_open": True},
    )


def _unknown_tool_error(run: Run, agent: Agent, name: str) -> str:
    if name in WRITE_TOOL_NAMES and run.coding and not run.ship_unlocked:
        return "ship_locked"
    if name == "executeScriptInSandbox" and agent.role not in {"executor", "tester"}:
        return "role_denied"
    if name == "sandbox_write" and agent.role not in {"builder", "coder"}:
        return "role_denied"
    if name == "callVote" and agent.role != "manager":
        return "role_denied"
    if name == "git_login" and (agent.role != "manager" or not run.git_remote):
        return "unknown_tool"
    if name in {"sendMessageToBlackboard", "viewBlackboardMessages", "viewSessionDetails"} and run.level == "small":
        return "level_denied"
    return "unknown_tool"


_ARG_ALIASES = {
    "directory": ("directory", "dir", "folder"),
    "name": ("name", "filename"),
    "content": ("content", "text", "body", "code", "json"),
    "path": ("path", "file"),
    "file_path": ("file_path",),
    "url": ("url",),
    "query": ("query", "q", "search"),
    "max_n": ("max_n", "num"),
    "n": ("n", "count"),
    "kind": ("kind",),
    "section": ("section",),
    "chunk": ("chunk", "page"),
    "repo_url": ("repo_url", "url"),
    "start": ("start",),
    "end": ("end",),
    "type": ("type",),
    "structure": ("structure",),
}


_TOOL_PARAMS = {
    "search_dir": {"directory", "name", "type", "recursive"},
    "read_file": {"directory", "name", "file_path", "start", "end"},
    "write_doc": {"directory", "name", "type", "content", "structure"},
    "write_file": {"directory", "name", "type", "content", "structure"},
    "write_pdf": {"directory", "name", "content", "structure"},
    "write_json": {"directory", "name", "content"},
    "append_file": {"directory", "name", "type", "content"},
    "mkdir": {"directory", "name"},
    "get_url": {"url", "start", "end"},
    "search_web": {"query", "max_n", "start", "end"},
    "post_url": {"url", "body", "content_type", "start", "end"},
    "resetSession": set(),
    "viewSessionDetails": set(),
    "sendMessageToBlackboard": {"body", "kind"},
    "viewBlackboardMessages": {"n"},
    "openSandbox": set(),
    "sandbox_read": {"path", "start", "end"},
    "sandbox_write": {"path", "content"},
    "executeScriptInSandbox": {"path", "timeout"},
    "getResultsFromSandbox": {"start", "end"},
    "sandbox_fetch": {"url", "method", "body", "start", "end"},
    "updateBoard": {"section", "content"},
    "viewCommitteeBoard": {"chunk", "n"},
    "callVote": set(),
    "git_login": set(),
}


def _tool_args(name: str, args: dict[str, Any]) -> dict[str, Any]:
    raw = {k: v for k, v in (args or {}).items() if k != "agent_id"}
    canon: dict[str, Any] = dict(raw)
    for dest, keys in _ARG_ALIASES.items():
        if dest in canon and canon[dest] not in (None, ""):
            continue
        for key in keys:
            if key in raw and raw[key] not in (None, ""):
                canon[dest] = raw[key]
                break
    allowed = _TOOL_PARAMS.get(name)
    if allowed is None:
        return {k: v for k, v in canon.items() if v is not None}
    out = {k: v for k, v in canon.items() if k in allowed}
    if name in {
        "read_file",
        "sandbox_read",
        "getResultsFromSandbox",
        "sandbox_fetch",
        "viewBlackboardMessages",
        "search_web",
        "get_url",
        "post_url",
        "viewCommitteeBoard",
    }:
        if "start" in out:
            out["start"] = _as_int(out["start"], 1)
        if "end" in out:
            out["end"] = _as_int(out["end"], 1)
        if "n" in out:
            out["n"] = _as_int(out["n"], 20)
        if "max_n" in out:
            out["max_n"] = _as_int(out["max_n"], 10)
        if "chunk" in out:
            out["chunk"] = _as_int(out["chunk"], 1)
    return out


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    out.pop("handle", None)
    return out


def _system_prompt(run: Run, agent: Agent, tools: dict[str, Callable[..., Any]]) -> str:
    if run.committee is not None:
        return committee.system_prompt(run, agent, list(tools))
    names = ", ".join(sorted(tools))
    need_tools = _ops_needed(run.file_ops) or run.web or run.mail_cal != "off" or run.level == "large"
    if need_tools:
        if run.summarize_keep:
            prefer = (
                "The build already shipped. Do not execute and do not write. "
                "Call search_dir / read_file on the keep folder, then emit "
                '{"final": "summary of what shipped, architecture, each file, and the save path"}.\n'
            )
        elif run.coding and not run.ship_unlocked:
            prefer = _large_tool_prefer(agent)
        elif run.level == "large" and not run.coding:
            prefer = _review_tool_prefer()
        else:
            prefer = (
                "The user needs tools. Do not answer with final until you have called the needed tool and seen its result.\n"
                "Emit exactly one JSON object per reply. If you need several tools, call one, wait for the tool result, then call the next.\n"
                'Tool call: {"tool": "read_file", "args": {"directory": "inputs", "name": "file.pdf"}}\n'
                'or {"tool": "write_doc", "args": {"directory": "t01_txt", "name": "hello", "type": "txt", "content": "hello"}}\n'
                'or {"tool": "search_web", "args": {"query": "python 3.13 release"}}\n'
                'or {"tool": "get_url", "args": {"url": "https://example.com/"}}\n'
                "After a search, copy a result URL into get_url. Do not fetch google.com/search.\n"
                "After reads or fetches succeed, copy facts from the tool result into write content. "
                "Do not write empty content, '...', or placeholders. Then emit "
                '{"final": "a short user-facing summary"}. Do not use a tool named name.\n'
            )
    else:
        prefer = 'Prefer a direct reply: {"final": "answer for the user"}. Do not call tools.\n'
        blob = f"{run.user_prompt or ''} {run.intent or ''}"
        if not run.coding and router.wants_execute(blob):
            prefer += (
                "They asked to run or test code. There is no sandbox on this run. "
                "Do not claim you executed anything. You may show a short example in final. "
                "Say clearly you cannot test it until they select Coding / --code.\n"
            )
        elif not run.coding and (
            router.wants_code_agent(blob) or _work_kind(run) == "code"
        ):
            prefer += (
                "Put the complete code in final (fenced ```html / ```python / ```js as fits). "
                "Say it is not tested and was not executed, because Coding is not selected. "
                "Do not describe opening a sandbox.\n"
            )
        elif router.wants_code_agent(blob):
            prefer += (
                "If they asked for a page or snippet, put the complete HTML/CSS/JS in final "
                "(fenced ```html is fine). Do not describe a sandbox.\n"
            )
    shipped = blackboard.shipped_keep_paths(run.thread)
    if shipped and not run.summarize_keep:
        prefer += (
            f"This notebook's last shipped build is in {shipped[-1]}. "
            "If they ask about that work, search_dir and read_file that folder before answering. "
            "Do not invent the file contents.\n"
        )
    return (
        f"You are agent {agent.agent_name} with role {agent.role} on a {run.level} run.\n"
        f"User intent: {run.intent}\n"
        f"Available tools: {names}\n"
        "Reply with a single JSON object and nothing else.\n"
        + prefer
        + "Call a tool only if it is in the list above. Do not write, save, or build a document unless they asked.\n"
        "If they asked to create or save a file and write_doc, write_pdf, or write_json is listed, you can create files. "
        "Call that tool with directory, name, and type. Do not say you cannot create files.\n"
        "If they asked to read a document and read_file is listed, call read_file before you answer. Do not invent the contents.\n"
        "If the tool list is empty, answer with final. Do not invent tools.\n"
        "On medium/large, post drafts/critiques/votes with sendMessageToBlackboard. "
        "Allowed kinds: draft, critique, debug, vote. "
        "The script also records your final as a draft (builders/drafter) or vote (executor/checkers). "
        "Blackboard rules and debug messages are not the user answer.\n"
        'If this turn established durable facts about the user (name, job title, skills, education, professional links), include "profile_update": {"name":"...","role":"...","skills":["..."],"education":["..."],"links":["..."]} with only keys you know. Do not guess.\n'
        "Do not pass agent_id. Do not request tokens or passwords.\n"
    )


EXECUTE_ROLE_HINT = (
    "On a coding committee only the tester may run scripts. "
    "Coders write the .py; they do not call executeScriptInSandbox."
)


def _review_tool_prefer() -> str:
    return (
        "High-stakes review. There is no sandbox. Write the document with write_doc / write_pdf / write_json "
        "into the keep folder.\n"
        "Emit exactly one JSON object per reply. Call one tool, wait, then the next.\n"
        '{"tool": "write_doc", "args": {"directory": "outputs", "name": "review", "type": "md", "content": "..."}}\n'
        'Post {"tool": "sendMessageToBlackboard", "args": {"kind": "draft", "body": "..."}} then vote ship or reject.\n'
        "Do not call sandbox tools. Do not execute scripts.\n"
    )


def _run_ship_summary(run: Run, exec_name: str) -> None:
    """One extra executor pass after copy-out so the user answer is a summary, not 'saved'."""
    if exec_name not in run.agents:
        return
    run.summarize_keep = True
    try:
        createThread(exec_name)
        startThread(exec_name)
        endThread(exec_name)
        deleteThread(exec_name)
    finally:
        run.summarize_keep = False


def _keep_dir(run: Run) -> Path:
    slug = _keep_slug(run.intent or run.user_prompt or run.run_id)
    name = f"{date.today().isoformat()}_{slug}"
    dest = (config.OUTPUTS / name).resolve()
    if dest.exists():
        dest = (config.OUTPUTS / f"{name}_{run.run_id[-8:]}").resolve()
    return dest


def _keep_slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:40]
    return slug or "build"


def _keep_summary(run: Run) -> str:
    keep = run.keep_path
    if keep is None or not keep.is_dir():
        return ""
    files = [
        p.relative_to(keep).as_posix()
        for p in sorted(keep.rglob("*"))
        if p.is_file() and p.name != "SUMMARY.md" and ".git" not in p.relative_to(keep).parts
    ]
    if not files:
        return ""
    lines = [
        f"Shipped to {keep}.",
        "Files:",
        *[f"- {name}" for name in files[:24]],
    ]
    result_txt = keep / "result.txt"
    if result_txt.is_file():
        snippet = result_txt.read_text(encoding="utf-8", errors="replace").strip()[:400]
        if snippet:
            lines.append("Run output:")
            lines.append(snippet)
    return "\n".join(lines)


def keep_summary_url(run: Run) -> str | None:
    keep = run.keep_path
    if keep is None or not (keep / "SUMMARY.md").is_file():
        return None
    return "/keep?" + urlencode({"dir": keep.name, "file": "SUMMARY.md"})


def _pdf_artifacts(run: Run) -> list[dict[str, str]]:
    root = config.OUTPUTS.resolve()
    rows: list[dict[str, str]] = []
    for path in file_tools.pdf_paths_for_run(run.run_id, run.keep_path):
        try:
            rel = path.resolve().relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) < 2:
            continue
        folder = "/".join(parts[:-1])
        name = parts[-1]
        rows.append(
            {
                "name": name,
                "dir": folder,
                "url": "/keep?" + urlencode({"dir": folder, "file": name}),
            }
        )
    return rows


def _large_fallback_answer(run: Run) -> str:
    summary = _keep_summary(run)
    if summary:
        return summary
    if run.ship_unlocked and run.keep_path is not None:
        return f"Shipped to {run.keep_path}."
    return _unshipped_summary(run)


def _unshipped_summary(run: Run) -> str:
    if run.sandbox_executed:
        lines = ["The committee ran the sandbox but did not vote ship. Nothing was copied to the keep folder."]
    else:
        lines = ["The committee did not ship. Nothing was copied to the keep folder."]
    root = run.sandbox_path
    if root is not None and root.is_dir():
        files = [
            p.relative_to(root).as_posix()
            for p in sorted(root.rglob("*"))
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() != ".tmp"
        ]
        if files:
            lines.append("Files in the jail:")
            lines.extend(f"- {name}" for name in files[:24])
    stdout = str((run.sandbox_results or {}).get("stdout") or "").strip()
    if stdout:
        lines.append("Run output:")
        lines.append(stdout[:400])
    return "\n".join(lines)


def _large_tool_prefer(agent: Agent) -> str:
    head = (
        "The user needs tools. Do not answer with final until you have called the needed tool and seen its result.\n"
        "Emit exactly one JSON object per reply. If you need several tools, call one, wait for the tool result, then call the next.\n"
    )
    tail = (
        'After a successful execute, vote {"tool": "sendMessageToBlackboard", "args": {"kind": "vote", "body": "ship"}} '
        "or body reject. Durable write_doc stays locked until a successful execute and a majority ship vote. "
        "The factory then copies sandbox files into the keep folder.\n"
    )
    if agent.role == "builder":
        return (
            head
            + 'Write stdlib-only Python with sandbox_write (no numpy, no pip). Never call executeScriptInSandbox.\n'
            + '{"tool": "sandbox_write", "args": {"path": "mul.py", "content": "print(3*7)"}}\n'
            + 'Then post {"tool": "sendMessageToBlackboard", "args": {"kind": "draft", "body": "wrote mul.py"}}\n'
            + tail
        )
    if agent.role == "executor":
        return (
            head
            + "After openSandbox, run the builder .py. Do not sandbox_write.\n"
            + '{"tool": "executeScriptInSandbox", "args": {"path": "mul.py"}} then getResultsFromSandbox.\n'
            + tail
        )
    return (
        head
        + 'Builders: {"tool": "sandbox_write", "args": {"path": "mul.py", "content": "print(3*7)"}}\n'
        + 'Executor: {"tool": "executeScriptInSandbox", "args": {"path": "mul.py"}} then getResultsFromSandbox.\n'
        + tail
    )


def _pin_execute_role_hint(run: Run) -> None:
    if run.blackboard is None:
        return
    if any(m.get("kind") == "debug" and EXECUTE_ROLE_HINT in str(m.get("body") or "") for m in run.blackboard.messages):
        return
    who = run.router_agent or next(iter(run.agents), None)
    if not who:
        return
    blackboard.send_message(EXECUTE_ROLE_HINT, "debug", agent_id=who, factory=True)


def _coding_rules_text() -> str:
    path = config.CODING_RULES_PATH
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def _writers_open(run: Run) -> bool:
    if run.level != "large":
        return True
    if not run.coding:
        return True
    return run.ship_unlocked


def _committee_agents(run: Run) -> list[Agent]:
    return [a for a in run.agents.values() if a.role in {"builder", "executor"}]


def _ship_ready(run: Run) -> bool:
    if run.level != "large":
        return False
    if run.coding and not run.sandbox_executed:
        return False
    voters = _committee_agents(run)
    if not voters:
        return False
    last = blackboard.last_ship_votes(run)
    ships = sum(1 for agent in voters if last.get(agent.agent_name) == "ship")
    rejects = sum(1 for agent in voters if last.get(agent.agent_name) == "reject")
    need = (len(voters) + 1) // 2
    return ships >= need and ships > rejects


def _refresh_ship_lock(run: Run) -> None:
    if run.level != "large" or run.committee is not None:
        return
    if _ship_ready(run):
        run.ship_unlocked = True
        if run.coding:
            _copy_sandbox_out(run)


def _committee_meta(run: Run) -> dict[str, Any] | None:
    board = run.committee
    if board is None:
        return None
    feat = (board.features or "").strip()
    if len(feat) > 160:
        feat = feat[:159] + "…"
    return {
        "phase": board.phase,
        "round": board.round,
        "vote": dict(board.last_vote),
        "shipped": run.ship_unlocked,
        "phase_complete": board.phase_complete,
        "commits": len(board.commits),
        "features": feat,
        "git_remote": run.git_remote,
    }


def _copy_sandbox_out(run: Run) -> None:
    runtime.collect_sandbox_output(run)
    keep = run.keep_path
    root = run.sandbox_path
    if keep is None or root is None or not root.is_dir():
        return
    keep.mkdir(parents=True, exist_ok=True)
    agent_id = run.router_agent
    for src in root.rglob("*"):
        if not src.is_file():
            continue
        if src.name.startswith(".") or src.suffix.lower() == ".tmp":
            continue
        if src.suffix.lower() not in config.SANDBOX_EXTENSIONS:
            continue
        rel = src.relative_to(root)
        dest = keep / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        file_tools.keep_copy(dest, src.read_bytes(), agent_id=agent_id)
    stdout = str((run.sandbox_results or {}).get("stdout") or "")
    if stdout.strip():
        file_tools.keep_copy(keep / "result.txt", stdout.encode("utf-8"), agent_id=agent_id)
    summary = _keep_summary(run)
    if summary:
        file_tools.keep_copy(keep / "SUMMARY.md", summary.encode("utf-8"), agent_id=agent_id)


def _agent(agent_name: str) -> tuple[Run | None, Agent | None, dict[str, Any] | None]:
    run = store.run_for_agent(agent_name)
    if run is None or agent_name not in run.agents:
        return None, None, {"ok": False, "error": "no_agent"}
    return run, run.agents[agent_name], None


def _any_run() -> Run | None:
    runs = list(store._RUNS.values())  # noqa: SLF001
    return runs[-1] if runs else None


def _factory(tool: str, run: Run | None, agent_name: str, result: dict[str, Any]) -> dict[str, Any]:
    return logger.finish(
        event="factory",
        tool=tool,
        run_id=None if run is None else run.run_id,
        agent_name=agent_name,
        result=result,
        level=None if run is None else run.level,
        stakes=None if run is None else run.stakes,
        mail_cal=None if run is None else run.mail_cal,
    )
