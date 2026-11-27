"""Local UI/UX search for the coding committee. Agents never import this file.

The host runs the sibling ui-ux-pro-max-skill search. No cloud model. The text
that comes back is a recommendation for plain CSS. It does not override coding rules.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import skills.host as host

GUIDE_CAP = 1800
QUERY_CAP = 240
DOMAINS = frozenset({"style", "color", "chart", "landing", "product", "ux", "typography", "icons", "web"})
_MARKER = (("src/ui-ux-pro-max/scripts/search.py", "file"),)
_MOTION = re.compile(r"\n### Motion\n.*?(?=\n### |\Z)", re.S)
_FENCE = re.compile(r"```[a-z]*\n.*?```", re.S | re.I)
_DROP = re.compile(r"fonts\.googleapis|@import\s+url|\bgsap\b|tailwind|cursor-pointer|heroicons|lucide", re.I)
_PREFIX = (
    "Recommendation only. Coding rules win. Write plain CSS variables from the hex values. "
    "No Tailwind classes, no GSAP, no font download, no npm. "
    "A style mismatch is not a blocking critique.\n\n"
)


def find_root() -> Path | None:
    return host.find_checkout(("MAYAVI_UI_UX_ROOT",), "ui-ux-pro-max-skill", _MARKER)


def lookup(query: str, mode: str = "system", domain: str = "") -> dict[str, str | bool]:
    """One search. mode is system or domain. domain is ignored for system."""
    text = " ".join(str(query or "").split())[:QUERY_CAP]
    if len(text) < 2:
        return {"ok": False, "error": "empty_query"}
    asked = str(mode or "").strip().lower()
    if asked not in {"", "system", "design-system", "domain"}:
        return {"ok": False, "error": "mode_denied"}
    kind = "domain" if asked == "domain" else "system"
    chosen = str(domain or "").strip().lower()
    if kind == "domain" and chosen not in DOMAINS:
        return {"ok": False, "error": "domain_denied"}
    root = find_root()
    if root is None:
        return {"ok": False, "error": "ui_skill_missing"}
    script = root / "src" / "ui-ux-pro-max" / "scripts" / "search.py"
    try:
        proc = subprocess.run(
            build_argv(script, text, kind, chosen),
            cwd=str(script.parent),
            capture_output=True,
            text=True,
            timeout=20,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    guide = trim_guide(proc.stdout or "")
    if proc.returncode != 0 or len(guide) < 40:
        return {"ok": False, "error": "search_failed"}
    return {"ok": True, "mode": kind, "guide": guide}


def build_argv(script: Path, query: str, mode: str, domain: str) -> list[str]:
    """Argv for the search. Never persists, previews, or selects a framework stack."""
    if mode == "domain":
        return [sys.executable, str(script), query, "--domain", domain, "--max-results", "2"]
    return [sys.executable, str(script), query, "--design-system", "--format", "markdown"]


def trim_guide(text: str) -> str:
    """Drop font fetches, GSAP, and Tailwind so the sandbox can follow the rest."""
    body = _MOTION.sub("\n", str(text or "").replace("\r\n", "\n"))
    body = _FENCE.sub("", body)
    kept = [line for line in body.splitlines() if line.strip() and not _DROP.search(line)]
    guide = _PREFIX + "\n".join(kept).strip()
    if len(guide) <= GUIDE_CAP:
        return guide
    return guide[: GUIDE_CAP - 1] + "…"
