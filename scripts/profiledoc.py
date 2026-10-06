"""Structured profile stored as JSON. The model may propose it; the host checks every value."""

from __future__ import annotations

import json
import re
from pathlib import Path

import usbchat

_WORD = re.compile(r"[^a-z0-9]+")


def profile_json_path(root: Path) -> Path:
    return root / "profile.json"


def empty_profile() -> dict:
    return {
        "contact": {"name": "", "email": "", "phone": "", "location": "", "links": []},
        "summary": "",
        "experience": [],
        "skills": [],
        "education": [],
    }


def _text(value) -> str:
    return str(value or "").strip()


def normalize_profile(data: dict | None) -> dict:
    base = empty_profile()
    if not isinstance(data, dict):
        return base
    contact = data.get("contact") if isinstance(data.get("contact"), dict) else {}
    links = contact.get("links") or []
    if isinstance(links, str):
        links = [links]
    base["contact"] = {
        "name": _text(contact.get("name")),
        "email": _text(contact.get("email")),
        "phone": _text(contact.get("phone")),
        "location": _text(contact.get("location")),
        "links": [_text(item) for item in links if _text(item)],
    }
    base["summary"] = _text(data.get("summary"))
    skills = data.get("skills") or []
    if isinstance(skills, str):
        skills = [part.strip() for part in skills.split(",")]
    base["skills"] = [_text(item) for item in skills if _text(item)]
    experience = []
    for item in data.get("experience") or []:
        if not isinstance(item, dict):
            continue
        highlights = item.get("highlights") or []
        if isinstance(highlights, str):
            highlights = [line.strip("- ").strip() for line in highlights.splitlines()]
        experience.append(
            {
                "title": _text(item.get("title")),
                "employer": _text(item.get("employer")),
                "start": _text(item.get("start")),
                "end": _text(item.get("end")),
                "highlights": [_text(line) for line in highlights if _text(line)],
            }
        )
    base["experience"] = experience
    education = []
    for item in data.get("education") or []:
        if not isinstance(item, dict):
            continue
        education.append(
            {
                "degree": _text(item.get("degree")),
                "school": _text(item.get("school")),
                "year": _text(item.get("year")),
            }
        )
    base["education"] = education
    return base


def profile_is_empty(data: dict | None) -> bool:
    profile = normalize_profile(data)
    contact = profile["contact"]
    return not any(
        [
            contact["name"],
            contact["email"],
            contact["phone"],
            contact["location"],
            contact["links"],
            profile["summary"],
            profile["experience"],
            profile["skills"],
            profile["education"],
        ]
    )


def load_profile(path: Path) -> dict:
    if not path.is_file():
        return empty_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return empty_profile()
    return normalize_profile(data if isinstance(data, dict) else None)


def save_profile(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize_profile(data), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _norm(text: str) -> str:
    return _WORD.sub(" ", str(text or "").lower()).strip()


def verbal_contains(haystack: str, value: str) -> bool:
    """True when the value appears in the haystack, ignoring case and extra spaces."""
    needle = _norm(value)
    if not needle:
        return True
    hay = _norm(haystack)
    if " " not in needle and len(needle) <= 4:
        return f" {needle} " in f" {hay} "
    return needle in hay


def _keep(value: str, source: str, dropped: list[str]) -> str:
    if not value:
        return ""
    if verbal_contains(source, value):
        return value
    dropped.append(value)
    return ""


def filter_profile(data: dict, source: str) -> tuple[dict, list[str]]:
    """Drop any value that is not verbally present in the source text."""
    profile = normalize_profile(data)
    dropped: list[str] = []
    contact = profile["contact"]
    for key in ("name", "email", "phone", "location"):
        contact[key] = _keep(contact[key], source, dropped)
    contact["links"] = [item for item in contact["links"] if _keep(item, source, dropped)]
    summary_lines = []
    for sentence in re.split(r"(?<=[.!?])\s+", profile["summary"]):
        kept = _keep(sentence.strip(), source, dropped)
        if kept:
            summary_lines.append(kept)
    profile["summary"] = " ".join(summary_lines)
    roles = []
    for role in profile["experience"]:
        role["title"] = _keep(role["title"], source, dropped)
        role["employer"] = _keep(role["employer"], source, dropped)
        role["start"] = _keep(role["start"], source, dropped)
        role["end"] = _keep(role["end"], source, dropped)
        role["highlights"] = [line for line in role["highlights"] if _keep(line, source, dropped)]
        if role["title"] or role["employer"] or role["highlights"]:
            roles.append(role)
    profile["experience"] = roles
    profile["skills"] = [skill for skill in profile["skills"] if _keep(skill, source, dropped)]
    schools = []
    for school in profile["education"]:
        school["degree"] = _keep(school["degree"], source, dropped)
        school["school"] = _keep(school["school"], source, dropped)
        school["year"] = _keep(school["year"], source, dropped)
        if school["degree"] or school["school"] or school["year"]:
            schools.append(school)
    profile["education"] = schools
    return profile, dropped


def render_profile(data: dict) -> str:
    profile = normalize_profile(data)
    lines: list[str] = []
    contact = profile["contact"]
    if contact["name"]:
        lines.append(contact["name"])
    meta = [contact[key] for key in ("email", "phone", "location") if contact[key]]
    if meta:
        lines.append(" · ".join(meta))
    if contact["links"]:
        lines.extend(contact["links"])
    if profile["summary"]:
        lines.extend(["", "Summary", profile["summary"]])
    if profile["experience"]:
        lines.extend(["", "Experience"])
        for role in profile["experience"]:
            head = role["title"] or "Role"
            if role["employer"]:
                head = f"{head}, {role['employer']}" if role["title"] else role["employer"]
            dates = " – ".join(part for part in (role["start"], role["end"]) if part)
            if dates:
                head = f"{head} ({dates})"
            lines.append(head)
            for highlight in role["highlights"]:
                lines.append(f"- {highlight}")
    if profile["skills"]:
        lines.extend(["", "Skills", ", ".join(profile["skills"])])
    if profile["education"]:
        lines.extend(["", "Education"])
        for school in profile["education"]:
            head = school["degree"] or school["school"] or "Education"
            if school["degree"] and school["school"]:
                head = f"{school['degree']}, {school['school']}"
            if school["year"]:
                head = f"{head} ({school['year']})"
            lines.append(head)
    return "\n".join(lines).strip()


def _same(left: str, right: str) -> bool:
    return _norm(left) == _norm(right) and bool(_norm(left))


def merge_profile(existing: dict, update: dict) -> tuple[dict, list[str]]:
    """Fill blanks and add new roles. Keep an existing date or title when the new one differs."""
    base = normalize_profile(existing)
    incoming = normalize_profile(update)
    conflicts: list[str] = []
    for key in ("name", "email", "phone", "location"):
        if incoming["contact"][key] and not base["contact"][key]:
            base["contact"][key] = incoming["contact"][key]
    have_links = {_norm(item) for item in base["contact"]["links"]}
    for link in incoming["contact"]["links"]:
        if _norm(link) not in have_links:
            base["contact"]["links"].append(link)
            have_links.add(_norm(link))
    if incoming["summary"] and not base["summary"]:
        base["summary"] = incoming["summary"]
    have_skills = {_norm(item) for item in base["skills"]}
    for skill in incoming["skills"]:
        if _norm(skill) not in have_skills:
            base["skills"].append(skill)
            have_skills.add(_norm(skill))
    for role in incoming["experience"]:
        match = next(
            (
                old
                for old in base["experience"]
                if _same(old["employer"], role["employer"]) and _same(old["title"], role["title"])
            ),
            None,
        )
        if match is None:
            base["experience"].append(role)
            continue
        for key in ("start", "end"):
            if role[key] and match[key] and not _same(role[key], match[key]):
                conflicts.append(f"{role['title']} at {role['employer']}: kept {match[key]} instead of {role[key]}")
            elif role[key] and not match[key]:
                match[key] = role[key]
        have = {_norm(line) for line in match["highlights"]}
        for line in role["highlights"]:
            if _norm(line) not in have:
                match["highlights"].append(line)
                have.add(_norm(line))
    for school in incoming["education"]:
        match = next(
            (
                old
                for old in base["education"]
                if _same(old["degree"], school["degree"]) and _same(old["school"], school["school"])
            ),
            None,
        )
        if match is None:
            base["education"].append(school)
            continue
        if school["year"] and match["year"] and not _same(school["year"], match["year"]):
            conflicts.append(f"{school['degree']} at {school['school']}: kept {match['year']} instead of {school['year']}")
        elif school["year"] and not match["year"]:
            match["year"] = school["year"]
    return base, conflicts


_STRUCTURE_SYSTEM = (
    "Copy this resume into JSON with the keys contact, summary, experience, skills, and education. "
    "contact has name, email, phone, location, and links. "
    "Each experience item has title, employer, start, end, and highlights. "
    "Each education item has degree, school, and year. "
    "skills is a list of strings. "
    "Copy names, titles, dates, employers, and skill words as they appear. Do not add facts. "
    "Return JSON only."
)


def fits_structure_prompt(text: str, instruction: str, n_ctx: int) -> bool:
    budget = usbchat._blob_char_budget(n_ctx, instruction, _STRUCTURE_SYSTEM, chars_per_token=4)
    return len(text or "") <= budget


def build_update(complete, model_text: str, instruction: str, source_text: str) -> dict:
    """Ask once, and once more if the sections are unreadable. Then drop values the resume does not contain."""
    user = (instruction.strip() + "\n\n" if instruction.strip() else "") + model_text
    raw = complete(
        [
            {"role": "system", "content": _STRUCTURE_SYSTEM},
            {"role": "user", "content": user},
        ]
    )
    parsed = usbchat.extract_json_object(raw)
    if not parsed:
        raw = complete(
            [
                {"role": "system", "content": _STRUCTURE_SYSTEM},
                {"role": "user", "content": "Return the JSON object only.\n\n" + user},
            ]
        )
        parsed = usbchat.extract_json_object(raw)
    if not parsed:
        return {
            "reply": "The profile sections could not be read. profile.json was left unchanged.",
            "profile_record": None,
            "dropped": [],
        }
    cleaned, dropped = filter_profile(normalize_profile(parsed), source_text)
    reply = render_profile(cleaned)
    cleaned, dropped_again = filter_profile(cleaned, source_text + "\n" + reply)
    dropped.extend(dropped_again)
    reply = render_profile(cleaned)
    if profile_is_empty(cleaned):
        reply = "Nothing on the resume could be saved to the profile."
        record = None
    else:
        record = cleaned
    if dropped:
        listed = "\n".join(f"- {item}" for item in dropped)
        reply = (reply + "\n\n" if reply else "") + "Left out, not found in the resume notes:\n" + listed
    return {"reply": reply.strip(), "profile_record": record, "dropped": dropped}


def job_profile_text(root: Path, cap: int = 24_000) -> str:
    """Text the job committee reads. JSON wins when it has saved details."""
    rendered = render_profile(load_profile(profile_json_path(root)))
    if rendered.strip():
        return rendered[:cap]
    return usbchat.read_profile(usbchat.profile_path(root), cap=cap)
