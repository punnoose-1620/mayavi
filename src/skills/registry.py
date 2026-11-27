"""Skill registry. Add a skill by calling register() from its module, then import that module in load()."""

from __future__ import annotations

from typing import Any, Callable

_SKILLS: dict[str, "Skill"] = {}
_LOADED = False


class Skill:
    def __init__(self, *, id: str, label: str, title: str, run: Callable[..., dict], flag: str = ""):
        self.id = id
        self.label = label
        self.title = title
        self.run = run
        self.flag = flag

    def public(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "title": self.title}


def register(skill: Skill) -> Skill:
    if skill.id in _SKILLS:
        raise ValueError(f"skill already registered: {skill.id}")
    _SKILLS[skill.id] = skill
    return skill


def get(skill_id: str) -> Skill | None:
    return _SKILLS.get(str(skill_id or "").strip())


def listed() -> list[dict[str, str]]:
    return [skill.public() for skill in _SKILLS.values()]


def selected(body: dict | None) -> tuple[str, str | None]:
    """The one skill this request asked for. A second choice is an error."""
    payload: dict[str, Any] = body if isinstance(body, dict) else {}
    ids: list[str] = []
    explicit = str(payload.get("skill") or "").strip()
    if explicit:
        ids.append(explicit)
    for skill in _SKILLS.values():
        if skill.flag and payload.get(skill.flag) and skill.id not in ids:
            ids.append(skill.id)
    if len(ids) > 1:
        return "", "many_skills"
    if not ids:
        return "", None
    if get(ids[0]) is None:
        return "", "unknown_skill"
    return ids[0], None


def load() -> None:
    """Import skill modules once. Each module registers itself."""
    global _LOADED
    if _LOADED:
        return
    import skills.career_ops  # noqa: F401
    import skills.humanizer  # noqa: F401

    _LOADED = True
