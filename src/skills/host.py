"""Shared runtime for local skills. A new skill imports these instead of copying them.

Every generation goes through the local GGUF. Profile text is the signed-in person's
Mayavi profile. Claim checks use jobapp.claim_ratio. Node lookups are plain subprocesses.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import career
import config
import jobapp

PROFILE_CAP = 8_000


def find_checkout(env_keys: tuple[str, ...], sibling_name: str, markers: tuple[tuple[str, str], ...]) -> Path | None:
    """A sibling repo, or an env path. An explicit path that fails the markers is refused."""
    for key in env_keys:
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = config.REPO_ROOT / path
        resolved = path.resolve()
        return resolved if _has_markers(resolved, markers) else None
    sibling = (config.REPO_ROOT.parent / sibling_name).resolve()
    return sibling if _has_markers(sibling, markers) else None


def _has_markers(path: Path, markers: tuple[tuple[str, str], ...]) -> bool:
    for relative, kind in markers:
        target = path / relative
        if kind == "dir" and not target.is_dir():
            return False
        if kind == "file" and not target.is_file():
            return False
    return True


def capped_text(text: str, cap: int = PROFILE_CAP, minimum: int = 40) -> str:
    body = (text or "").strip()
    return body[:cap] if len(body) >= minimum else ""


def profile_text(device_id: str) -> str:
    """Professional profile for the person using this chat. Empty when they have not saved one."""
    if not device_id:
        return ""
    try:
        local = career.profile_text(device_id).strip()
    except ValueError:
        local = ""
    return capped_text(local)


def read_capped(path: Path | None, cap: int = PROFILE_CAP, minimum: int = 40) -> str:
    if path is None or not path.is_file():
        return ""
    return capped_text(path.read_text(encoding="utf-8", errors="replace"), cap, minimum)


def run_node(root: Path, script: str, args: list[str], timeout: int) -> tuple[int, str, str]:
    if shutil.which("node") is None:
        raise FileNotFoundError("node")
    proc = subprocess.run(
        ["node", str(root / script), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def result(
    skill_id: str,
    answer: str,
    *,
    notices: list[str] | None = None,
    documents: list[dict[str, str]] | None = None,
    ok: bool = True,
) -> dict:
    return {
        "ok": ok,
        "answer": (answer or "").strip(),
        "level": skill_id,
        "shape": skill_id,
        "documents": documents or [],
        "notices": notices or [],
        "stopped": False,
    }


def write_text(device_id: str, skill_id: str, filename: str, body: str) -> list[dict[str, str]]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"{skill_id}-{stamp}"
    if device_id:
        folder = config.OUTPUTS / device_id / name
        rel = f"{device_id}/{name}"
    else:
        folder = config.OUTPUTS / name
        rel = name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text((body or "").strip() + "\n", encoding="utf-8")
    return career.documents_for(rel)


def annotate_claims(
    complete,
    profile: str,
    draft: str,
    status,
    *,
    status_label: str = "Checking claims",
    unverified_notice: str = "claims_unverified",
) -> tuple[str, list[str]]:
    """Flag employers, dates, and metrics the draft added. Does not turn them into facts."""
    status(status_label)
    verdict = complete(
        [
            {
                "role": "system",
                "content": (
                    "Check the draft against the candidate file. "
                    "A claim is unsupported when an employer, title, date, skill, metric, or degree is not in the candidate file. "
                    "Rephrasing a true fact is supported. "
                    "Reply with one line per claim: 'supported: <sentence>' or 'unsupported: <sentence>'."
                ),
            },
            {"role": "user", "content": "Candidate file:\n" + profile[:PROFILE_CAP] + "\n\nDraft:\n" + draft},
        ],
        max_tokens=512,
    )
    ratio, unsupported = jobapp.claim_ratio(verdict)
    parsed = "supported:" in (verdict or "").lower() or bool(unsupported)
    if not parsed:
        note = draft + "\n\nClaims were not verified. Treat every number in the draft as unchecked."
        return note, [unverified_notice]
    if unsupported and ratio > jobapp.HALLUCINATION_LIMIT:
        quoted = "\n".join(f"- {quote}" for quote in unsupported)
        return draft + "\n\nThese lines are not in the candidate file:\n" + quoted, ["claim_check"]
    return draft, []


class ModelSession:
    """One local GGUF for a skill turn. A test can pass `complete` and nothing is loaded."""

    def __init__(self, complete=None, no_model: bool = False):
        self.no_model = no_model
        self._fn = complete
        self._loaded = False

    def can_generate(self) -> bool:
        return self._fn is not None or not self.no_model

    def optional(self):
        try:
            return self._open()
        except RuntimeError:
            return None

    def require(self):
        fn = self._open()
        if fn is None:
            raise RuntimeError("model_unavailable")
        return fn

    def close(self) -> None:
        if not self._loaded:
            return
        import models

        models.unloadModel()
        self._loaded = False

    def _open(self):
        if self._fn is not None:
            return self._fn
        if self.no_model:
            return None
        import career as career_mod

        role = career_mod._pick_role()
        self._fn = career_mod._complete(role)
        self._loaded = True
        return self._fn
