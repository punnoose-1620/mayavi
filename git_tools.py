"""Git login/commit/push. Credentials stay in-process. Agents never import this file."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import logger
import store
from store import CommitItem, Run

# In-process only. Never copy into tool results.
_SESSION: dict[str, Any] = {"logged_in": False, "remote": None}


def _need(agent_id: str | None) -> tuple[Run | None, str]:
    aid = str(agent_id or "")
    return store.run_for_agent(aid), aid


def _public(ok: bool, **extra: Any) -> dict[str, Any]:
    out = {"ok": ok, **extra}
    out.pop("token", None)
    out.pop("password", None)
    out.pop("handle", None)
    return out


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in {"GH_TOKEN", "GITHUB_TOKEN", "GIT_ASKPASS"}}
    env["GIT_TERMINAL_PROMPT"] = "0"
    token = config.GH_TOKEN
    if token:
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Bearer {token}"
    return env


def public_github_remote(url: str | None) -> str | None:
    """Accept only https://github.com/owner/repo. Strip userinfo. Else None."""
    raw = public_remote(url).rstrip("/")
    if raw.lower().endswith(".git"):
        raw = raw[:-4]
    if not raw:
        return None
    match = re.fullmatch(
        r"https://github\.com/([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)/([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?:\.git)?",
        raw,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    if repo.lower() in {".git", "gist"}:
        return None
    return f"https://github.com/{owner}/{repo}"


def public_remote(url: str | None) -> str:
    raw = str(url or "").strip()
    if "://" in raw:
        scheme, rest = raw.split("://", 1)
        if "@" in rest:
            rest = rest.rsplit("@", 1)[-1]
        return f"{scheme}://{rest}"
    return raw


def git_login(repo_url: str | None = None, agent_id: str | None = None) -> dict[str, Any]:
    """Mark the process logged in if a token or git credential exists. Never returns the secret."""
    run, aid = _need(agent_id)
    if run is not None:
        remote = run.git_remote
    else:
        remote = public_github_remote(repo_url)
    if not remote:
        return logger.finish(
            event="tool",
            tool="git_login",
            run_id=None if run is None else run.run_id,
            agent_name=aid,
            result=_public(False, error="no_remote"),
        )
    if config.GH_TOKEN:
        _SESSION["logged_in"] = True
        _SESSION["remote"] = remote
        return logger.finish(
            event="tool",
            tool="git_login",
            run_id=None if run is None else run.run_id,
            agent_name=aid,
            result=_public(True, login_ok=True, method="env"),
        )
    probe = subprocess.run(
        ["git", "config", "--get", "user.email"],
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if probe.returncode == 0 and probe.stdout.strip():
        _SESSION["logged_in"] = True
        _SESSION["remote"] = remote
        return logger.finish(
            event="tool",
            tool="git_login",
            run_id=None if run is None else run.run_id,
            agent_name=aid,
            result=_public(True, login_ok=True, method="git_config"),
        )
    return logger.finish(
        event="tool",
        tool="git_login",
        run_id=None if run is None else run.run_id,
        agent_name=aid,
        result=_public(
            False,
            error="login_required",
            hint="Set GH_TOKEN in .env or configure git credentials. The factory will not open a browser.",
        ),
    )


def git_commit(message: str, agent_id: str | None = None) -> dict[str, Any]:
    run, aid = _need(agent_id)
    if run is None or run.keep_path is None:
        return logger.finish(
            event="tool",
            tool="git_commit",
            run_id=None if run is None else run.run_id,
            agent_name=aid,
            result=_public(False, error="no_keep"),
        )
    if run.git_remote and not _SESSION.get("logged_in"):
        git_login(agent_id=aid)
    text = str(message or "").strip() or "committee phase"
    text = text.replace("\x00", "")[:200]
    root = Path(run.keep_path)
    result = _commit_tree(root, text)
    if run.committee is not None:
        run.committee.commits.append(
            CommitItem(
                message=text,
                when=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                sha=str(result.get("sha") or ""),
                skipped=str(result.get("error") or ""),
            )
        )
        if result.get("ok"):
            run.committee.commits_since_push += 1
    return logger.finish(
        event="tool",
        tool="git_commit",
        run_id=run.run_id,
        agent_name=aid,
        result=_public(bool(result.get("ok")), error=result.get("error"), sha=result.get("sha")),
    )


def git_push(agent_id: str | None = None) -> dict[str, Any]:
    run, aid = _need(agent_id)
    if run is None or run.keep_path is None:
        return logger.finish(
            event="tool",
            tool="git_push",
            run_id=None if run is None else run.run_id,
            agent_name=aid,
            result=_public(False, error="no_keep"),
        )
    if not _SESSION.get("logged_in"):
        login = git_login(agent_id=aid)
        if not login.get("ok"):
            return logger.finish(
                event="tool",
                tool="git_push",
                run_id=run.run_id,
                agent_name=aid,
                result=_public(False, error="login_required"),
            )
    root = Path(run.keep_path)
    remote = public_github_remote(run.git_remote) or public_github_remote(_SESSION.get("remote"))
    if not remote:
        return logger.finish(
            event="tool",
            tool="git_push",
            run_id=run.run_id,
            agent_name=aid,
            result=_public(False, error="no_remote"),
        )
    _ensure_remote(root, remote)
    pushed = subprocess.run(
        ["git", "-C", str(root), "push", "-u", "origin", "HEAD"],
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    ok = pushed.returncode == 0
    if ok and run.committee is not None:
        run.committee.last_push = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        run.committee.commits_since_push = 0
    err = None if ok else (pushed.stderr or pushed.stdout or "push_failed")[:200]
    if err and config.GH_TOKEN and config.GH_TOKEN in err:
        err = "push_failed"
    return logger.finish(
        event="tool",
        tool="git_push",
        run_id=run.run_id,
        agent_name=aid,
        result=_public(ok, error=err),
    )


def _commit_tree(root: Path, message: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    if not (root / ".git").exists():
        init = subprocess.run(["git", "-C", str(root), "init"], capture_output=True, text=True, env=_git_env())
        if init.returncode != 0:
            return {"ok": False, "error": "git_init_failed"}
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True, text=True, env=_git_env())
    commit = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "-c",
            "user.email=id10t@local",
            "-c",
            "user.name=id10t",
            "commit",
            "-m",
            message,
            "--allow-empty",
        ],
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if commit.returncode != 0:
        return {"ok": False, "error": "git_commit_failed"}
    sha = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    return {"ok": True, "sha": (sha.stdout or "").strip()}


def _ensure_remote(root: Path, url: str) -> None:
    url = public_remote(url)
    if not url:
        return
    probe = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        env=_git_env(),
    )
    if probe.returncode == 0:
        return
    subprocess.run(
        ["git", "-C", str(root), "remote", "add", "origin", url],
        capture_output=True,
        text=True,
        env=_git_env(),
    )


def reset_session() -> None:
    _SESSION["logged_in"] = False
    _SESSION["remote"] = None
