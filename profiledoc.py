"""Structured profile stored as JSON. The model may propose it; the host checks every value."""

from __future__ import annotations

import json
import re
from pathlib import Path

import doccompat as usbchat

_WORD = re.compile(r"[^a-z0-9]+")


def profile_json_path(root: Path) -> Path:
    return root / "profile.json"


def empty_profile() -> dict:
    return {
        "contact": {"name": "", "email": "", "phone": "", "location": "", "links": []},
        "summary": "",
        "experience": [],
        "projects": [],
        "skills": [],
        "education": [],
    }


def empty_role() -> dict:
    return {"position": "", "company": "", "location": "", "start": "", "end": "", "description": ""}


def empty_school() -> dict:
    return {
        "school": "",
        "location": "",
        "start": "",
        "end": "",
        "degree": "",
        "specialization": "",
        "description": "",
    }


def empty_project() -> dict:
    return {"title": "", "description": ""}


def _text(value) -> str:
    if isinstance(value, (dict, list)):
        return ""
    return str(value or "").strip()


def _description(value) -> str:
    """A description is text. A nested object is left empty so it can be requested again."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list) and all(not isinstance(item, (dict, list)) for item in value):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return ""


def empty_link() -> dict:
    return {"title": "", "url": ""}


def _link_url(item) -> str:
    if isinstance(item, dict):
        item = item.get("url") or item.get("link") or item.get("href") or ""
    return _text(item)


def _link_title(url: str, given: str) -> str:
    title = _text(given)
    if title:
        return title
    bare = _bare_url(url).lower()
    if "linkedin." in bare:
        return "LinkedIn"
    if "github." in bare:
        return "GitHub"
    host = bare.split("/")[0]
    return host or "Link"


def _link(item) -> dict | None:
    if isinstance(item, str):
        url = _bare_url(item) or _text(item)
        title = _link_title(url, "")
    elif isinstance(item, dict):
        given = _text(item.get("title") or item.get("type") or item.get("name") or item.get("label") or "")
        url = _bare_url(_link_url(item)) or _link_url(item)
        if not url and not given:
            return None
        title = _link_title(url, given)
    else:
        return None
    if not url and not title:
        return None
    return {"title": title, "url": url}


def _bare_url(url: str) -> str:
    text = re.sub(r"^[a-z][a-z0-9+.-]*://", "", _text(url), flags=re.I)
    text = re.sub(r"^www\.", "", text, flags=re.I)
    return text.rstrip("/")


def _role(item: dict) -> dict:
    description = item.get("description")
    if description is None:
        description = item.get("highlights")
    start = _text(item.get("start"))
    end = _text(item.get("end"))
    if not start and not end:
        end = _text(item.get("year"))
    return {
        "position": _text(item.get("position") or item.get("title")),
        "company": _text(item.get("company") or item.get("employer")),
        "location": _text(item.get("location")),
        "start": start,
        "end": end,
        "description": _description(description),
    }


def _school(item: dict) -> dict:
    start = _text(item.get("start"))
    end = _text(item.get("end"))
    if not start and not end:
        end = _text(item.get("year"))
    return {
        "school": _text(item.get("school") or item.get("university") or item.get("college")),
        "location": _text(item.get("location")),
        "start": start,
        "end": end,
        "degree": _text(item.get("degree") or item.get("course")),
        "specialization": _text(item.get("specialization")),
        "description": _description(item.get("description")),
    }


def _project(item: dict) -> dict:
    return {"title": _text(item.get("title")), "description": _description(item.get("description"))}


def normalize_profile(data: dict | None) -> dict:
    base = empty_profile()
    if not isinstance(data, dict):
        return base
    contact = data.get("contact") if isinstance(data.get("contact"), dict) else {}
    links = contact.get("links") or []
    if isinstance(links, str):
        links = [links]
    seen = set()
    stored_links = []
    for item in links:
        link = _link(item)
        if link is None:
            continue
        key = _norm(link["url"] or link["title"])
        if not key or key in seen:
            continue
        seen.add(key)
        stored_links.append(link)
    base["contact"] = {
        "name": _text(contact.get("name")),
        "email": _text(contact.get("email")),
        "phone": _text(contact.get("phone")),
        "location": _text(contact.get("location")),
        "links": stored_links,
    }
    base["summary"] = _text(data.get("summary"))
    skills = data.get("skills") or []
    if isinstance(skills, str):
        skills = [part.strip() for part in skills.split(",")]
    base["skills"] = [_text(item) for item in skills if _text(item)]
    base["experience"] = [_role(item) for item in data.get("experience") or [] if isinstance(item, dict)]
    base["education"] = [_school(item) for item in data.get("education") or [] if isinstance(item, dict)]
    base["projects"] = [_project(item) for item in data.get("projects") or [] if isinstance(item, dict)]
    return base


def is_follow_up(data: dict | None) -> bool:
    """A saved name plus contact details means the next resume run updates that profile."""
    profile = normalize_profile(data)
    contact = profile["contact"]
    if not contact["name"]:
        return False
    return bool(contact["email"] or contact["phone"] or contact["location"] or contact["links"])


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
            profile["projects"],
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


def _description_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _location_parts(value: str) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_PRESENT = {"present", "current", "now", "ongoing", "till date", "to date"}


def _is_present(value: str) -> bool:
    return _norm(value) in _PRESENT


def _parse_month_year(value: str) -> tuple[int, int] | None:
    text = _norm(value)
    if not text or _is_present(value):
        return None
    month = 0
    year = 0
    for part in text.split():
        if part in _MONTHS:
            month = _MONTHS[part]
        elif len(part) == 4 and part.isdigit():
            year = int(part)
    if not year:
        return None
    return year, month


def _end_after_start(start: str, end: str) -> bool:
    """True when end is later, current, or too vague to compare."""
    if not _text(end) or _is_present(end) or not _text(start):
        return True
    left = _parse_month_year(start)
    right = _parse_month_year(end)
    if left is None or right is None:
        return True
    if left[1] == 0 or right[1] == 0:
        return right[0] >= left[0]
    return (right[0], right[1]) > (left[0], left[1])


def _keep(value: str, source: str, dropped: list[str]) -> str:
    if not value:
        return ""
    if verbal_contains(source, value):
        return value
    dropped.append(value)
    return ""


_STOP_WORDS = frozenset(
    """
    a an the and or but if then than so such of to for in on with using via from by as at
    into over under that this these those is are was were be been being it its their his her
    them they we our you your not no nor
    """.split()
)


def _content_words(text: str) -> set[str]:
    words = set()
    for token in re.findall(r"[A-Za-z0-9]+", text or ""):
        word = token.lower()
        if len(word) < 2 or word in _STOP_WORDS:
            continue
        words.add(word)
    return words


def _collapsed(text: str) -> tuple[str, list[int]]:
    chars: list[str] = []
    origins: list[int] = []
    pending_space = False
    for index, char in enumerate(text or ""):
        if char.isspace():
            pending_space = bool(chars)
            continue
        if pending_space:
            chars.append(" ")
            origins.append(index)
            pending_space = False
        chars.append(char)
        origins.append(index)
    return "".join(chars), origins


def title_span(source: str, title: str) -> tuple[int, int] | None:
    """Where the title appears as its own phrase. Whitespace may differ; characters may not."""
    phrase = re.sub(r"\s+", " ", (title or "").strip())
    if len(phrase) < 2:
        return None
    collapsed, origins = _collapsed(source)
    start_at = 0
    while start_at <= len(collapsed):
        found = collapsed.find(phrase, start_at)
        if found < 0:
            return None
        before = collapsed[found - 1] if found else ""
        after_at = found + len(phrase)
        after = collapsed[after_at] if after_at < len(collapsed) else ""
        if (not before or not before.isalnum()) and (not after or not after.isalnum()):
            return origins[found], origins[after_at - 1] + 1
        start_at = found + 1
    return None


def _starts_new_block(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if len(stripped) > 12 and stripped.isupper():
        return True
    return bool(re.match(r"^[-*?\u2022]\s+\S", stripped))


def project_passage(source: str, span: tuple[int, int]) -> str:
    """The resume text that belongs to a title: its line and the lines under it."""
    line_start = (source or "").rfind("\n", 0, span[0]) + 1
    kept: list[str] = []
    for index, line in enumerate(source[line_start:].splitlines()):
        if index and _starts_new_block(line):
            break
        kept.append(line)
        if sum(len(item) for item in kept) > 700:
            break
    return "\n".join(kept).strip()


def project_mismatches(project: dict, source: str) -> list[str]:
    """Title must match the resume exactly. Remaining description words must appear under that title."""
    title = _text(project.get("title") if isinstance(project, dict) else "")
    description = _description(project.get("description") if isinstance(project, dict) else "")
    reasons: list[str] = []
    span = title_span(source, title)
    if span is None:
        reasons.append(
            "title failed because it is not an exact match in the resume. "
            "Copy the project title exactly as it is written."
        )
        return reasons
    if not description:
        reasons.append(
            "description failed because it is empty. "
            "Use the resume text that belongs to this title."
        )
        return reasons
    wanted = _content_words(description)
    have = _content_words(project_passage(source, span))
    missing = sorted(wanted - have)
    if not wanted or missing:
        shown = ", ".join(missing[:8]) if missing else "none"
        reasons.append(
            "description failed because these words are not in the resume text under that title: "
            f"{shown}. Use the words that belong to this project."
        )
    return reasons


def filter_profile(data: dict, source: str) -> tuple[dict, list[str]]:
    """Drop any value that is not verbally present in the source text."""
    profile = normalize_profile(data)
    dropped: list[str] = []
    contact = profile["contact"]
    for key in ("name", "email", "phone", "location"):
        contact[key] = _keep(contact[key], source, dropped)
    kept_links = []
    for item in contact["links"]:
        url = item.get("url") if isinstance(item, dict) else _text(item)
        if url and _keep(_bare_url(url) or url, source, dropped):
            kept_links.append(item)
    contact["links"] = kept_links
    summary_lines = []
    for sentence in re.split(r"(?<=[.!?])\s+", profile["summary"]):
        kept = _keep(sentence.strip(), source, dropped)
        if kept:
            summary_lines.append(kept)
    profile["summary"] = " ".join(summary_lines)
    roles = []
    for role in profile["experience"]:
        for key in ("position", "company", "start", "end"):
            role[key] = _keep(role[key], source, dropped)
        role["location"] = ", ".join(
            part for part in _location_parts(role["location"]) if _keep(part, source, dropped)
        )
        role["description"] = "\n".join(
            line for line in _description_lines(role["description"]) if _keep(line, source, dropped)
        )
        if any(role[key] for key in ("position", "company", "description")):
            roles.append(role)
    profile["experience"] = roles
    projects = []
    for project in profile["projects"]:
        reasons = project_mismatches(project, source)
        dropped.extend(reasons)
        if not reasons:
            projects.append(project)
    profile["projects"] = projects
    profile["skills"] = [skill for skill in profile["skills"] if _keep(skill, source, dropped)]
    schools = []
    for school in profile["education"]:
        for key in ("school", "start", "end", "degree", "specialization"):
            school[key] = _keep(school[key], source, dropped)
        school["location"] = ", ".join(
            part for part in _location_parts(school["location"]) if _keep(part, source, dropped)
        )
        school["description"] = "\n".join(
            line for line in _description_lines(school["description"]) if _keep(line, source, dropped)
        )
        if any(school[key] for key in ("school", "degree", "description")):
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
    for link in contact["links"]:
        title = link.get("title") or ""
        url = link.get("url") or ""
        if title and url:
            lines.append(f"{title}: {url}")
        elif url or title:
            lines.append(url or title)
    if profile["summary"]:
        lines.extend(["", "Summary", profile["summary"]])
    if profile["experience"]:
        lines.extend(["", "Experience"])
        for role in profile["experience"]:
            lines.append(_entry_head(role["position"], role["company"], role["location"], role["start"], role["end"], "Role"))
            if role["description"]:
                lines.append(role["description"])
    if profile["projects"]:
        lines.extend(["", "Projects"])
        for project in profile["projects"]:
            if project["title"]:
                lines.append(project["title"])
            if project["description"]:
                lines.append(project["description"])
    if profile["skills"]:
        lines.extend(["", "Skills", ", ".join(profile["skills"])])
    if profile["education"]:
        lines.extend(["", "Education"])
        for school in profile["education"]:
            lines.append(
                _entry_head(school["degree"], school["school"], school["location"], school["start"], school["end"], "Education")
            )
            if school["specialization"]:
                lines.append(school["specialization"])
            if school["description"]:
                lines.append(school["description"])
    return "\n".join(lines).strip()


def _entry_head(primary: str, secondary: str, location: str, start: str, end: str, fallback: str) -> str:
    head = primary or fallback
    if secondary:
        head = f"{head}, {secondary}" if primary else secondary
    if location:
        head = f"{head}, {location}"
    dates = " – ".join(part for part in (start, end) if part)
    if dates:
        head = f"{head} ({dates})"
    return head


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
    have_links = {}
    for item in base["contact"]["links"]:
        have_links[_norm(item.get("url") or item.get("title") or "")] = item
    for link in incoming["contact"]["links"]:
        key = _norm(link.get("url") or link.get("title") or "")
        if not key:
            continue
        match = have_links.get(key)
        if match is None:
            base["contact"]["links"].append(link)
            have_links[key] = link
            continue
        if link.get("title") and not match.get("title"):
            match["title"] = link["title"]
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
                if _same(old["company"], role["company"]) and _same(old["position"], role["position"])
            ),
            None,
        )
        if match is None:
            base["experience"].append(role)
            continue
        for key in ("location", "start", "end"):
            if role[key] and match[key] and not _same(role[key], match[key]):
                conflicts.append(f"{role['position']} at {role['company']}: kept {match[key]} instead of {role[key]}")
            elif role[key] and not match[key]:
                match[key] = role[key]
        match["description"] = _merge_lines(match["description"], role["description"])
    for project in incoming["projects"]:
        match = next((old for old in base["projects"] if _same(old["title"], project["title"])), None)
        if match is None:
            base["projects"].append(project)
            continue
        if project["description"] and match["description"] and not _same(project["description"], match["description"]):
            conflicts.append(f"{project['title']}: kept the saved description")
        elif project["description"] and not match["description"]:
            match["description"] = project["description"]
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
        for key in ("location", "start", "end", "specialization"):
            if school[key] and match[key] and not _same(school[key], match[key]):
                conflicts.append(f"{school['degree']} at {school['school']}: kept {match[key]} instead of {school[key]}")
            elif school[key] and not match[key]:
                match[key] = school[key]
        match["description"] = _merge_lines(match["description"], school["description"])
    return base, conflicts


def _merge_lines(saved: str, incoming: str) -> str:
    lines = _description_lines(saved)
    have = {_norm(line) for line in lines}
    for line in _description_lines(incoming):
        if _norm(line) not in have:
            lines.append(line)
            have.add(_norm(line))
    return "\n".join(lines)


_CONSTRUCTOR_SYSTEM = (
    "You convert resume text into one JSON object. Return JSON only. "
    "Copy names, positions, companies, places, dates, and skill words as they appear. Do not add facts. "
    "Dates are a month and a year. Use an empty string when a value is absent. "
    "A current role may use Present or an empty end. "
    "description is only the bullet lines under a job. Do not mention the position, company, location, or dates in description."
)

_SHAPES = {
    "contact": '{"name":"","email":"","phone":"","location":"","links":[{"title":"","url":""}]}',
    "summary": '{"summary":""}',
    "skills": '{"skills":[]}',
    "education": '{"education":[{"school":"","location":"","start":"","end":"","degree":"","specialization":"","description":""}]}',
    "experience": '{"experience":[{"position":"","company":"","location":"","start":"","end":"","description":""}]}',
    "experience_headers": '{"experience":[{"position":"","company":"","location":"","start":"","end":""}]}',
    "description": '{"description":""}',
    "line": '{"line":""}',
    "role": '{"position":"","company":"","location":"","start":"","end":""}',
    "projects": '{"projects":[{"title":"","description":""}]}',
}


def fits_structure_prompt(text: str, instruction: str, n_ctx: int) -> bool:
    budget = usbchat._blob_char_budget(n_ctx, instruction, _CONSTRUCTOR_SYSTEM, chars_per_token=4)
    return len(text or "") <= budget


GUARD_ROUNDS = 5

_JSON_SHAPE = (
    "Return one JSON object only. contact.links is a list of objects with title and url. "
    "Each job has position, company, location, start, end, and description. "
    "Each school has school, location, start, end, degree, specialization, and description. "
    "Each project has title and description. "
    "Copy each value as it appears in the resume, or use an empty string."
)


def _guard(failures: list[str], field: str, value: str, why: str, how: str) -> None:
    shown = value if len(value) <= 180 else value[:180] + "…"
    failures.append(f'{field}: "{shown}" failed because {why} {how}')


def _check_value(failures: list[str], field: str, value: str, source: str, how: str) -> None:
    if not value:
        return
    if verbal_contains(source, value):
        return
    _guard(failures, field, value, "those words are not in the resume.", how)


def audit_profile(raw: dict, source: str, failures: list[str]) -> dict:
    """Append one message per failed section or value. The list is shared by every check."""
    if not isinstance(raw, dict) or not raw:
        failures.append(
            "reply: the text failed because it is not a JSON object. " + _JSON_SHAPE
        )
        return empty_profile()
    expected = {
        "contact": "an object with name, email, phone, location, and links",
        "summary": "a string copied from the resume",
        "experience": "a list of jobs with position, company, location, start, end, and description",
        "projects": "a list of objects with title and description",
        "skills": "a list of strings copied from the resume",
        "education": "a list of schools with school, location, start, end, degree, specialization, and description",
    }
    for key, how in expected.items():
        if key not in raw:
            failures.append(
                f"{key}: this section is missing. Structure it as {how}. "
                "It was missing from the JSON object."
            )
    profile = normalize_profile(raw)
    contact = profile["contact"]
    for key in ("name", "email", "phone", "location"):
        _check_value(
            failures,
            f"contact.{key}",
            contact[key],
            source,
            "Copy that value as it appears in the resume, or use an empty string.",
        )
    for index, link in enumerate(contact["links"]):
        url = link.get("url") if isinstance(link, dict) else _text(link)
        _check_value(
            failures,
            f"contact.links[{index}]",
            _bare_url(url) or url,
            source,
            "Copy the link address as it appears in the resume, or remove it.",
        )
    for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", profile["summary"])):
        _check_value(
            failures,
            f"summary[{index}]",
            sentence.strip(),
            source,
            "Copy the sentence as it appears in the resume, or remove it.",
        )
    for index, role in enumerate(profile["experience"]):
        _check_entry(failures, f"experience[{index}]", role, ("position", "company", "start", "end"), source)
        _check_order(failures, f"experience[{index}]", role, source)
    for index, project in enumerate(profile["projects"]):
        for reason in project_mismatches(project, source):
            failures.append(f"projects[{index}]: {reason}")
    for index, skill in enumerate(profile["skills"]):
        _check_value(
            failures,
            f"skills[{index}]",
            skill,
            source,
            "Copy the skill as it appears in the resume, or remove it.",
        )
    for index, school in enumerate(profile["education"]):
        _check_entry(
            failures,
            f"education[{index}]",
            school,
            ("school", "start", "end", "degree", "specialization"),
            source,
        )
        _check_order(failures, f"education[{index}]", school, source)
    if not failures and profile_is_empty(profile):
        failures.append(
            "profile: every section is empty. Fill contact, summary, experience, projects, skills, and education from the resume. "
            "It failed because the JSON object had no resume text in it."
        )
    return profile


def _check_entry(failures: list[str], field: str, item: dict, keys: tuple[str, ...], source: str) -> None:
    for key in keys:
        _check_value(
            failures,
            f"{field}.{key}",
            item.get(key) or "",
            source,
            "Copy that value as it appears in the resume, or use an empty string.",
        )
    for part in _location_parts(item.get("location") or ""):
        _check_value(
            failures,
            f"{field}.location",
            part,
            source,
            "Copy that place as it appears in the resume, or use an empty string.",
        )
    for line in _description_lines(item.get("description") or ""):
        _check_value(
            failures,
            f"{field}.description",
            line,
            source,
            "Copy a bullet from the resume. Do not mention the position, company, location, or dates.",
        )


def _check_order(failures: list[str], field: str, item: dict, _source: str) -> None:
    start = item.get("start") or ""
    end = item.get("end") or ""
    if _end_after_start(start, end):
        return
    _guard(
        failures,
        f"{field}.end",
        end,
        f'it is not after the start "{start}".',
        "Use a later month and year, Present, or an empty string.",
    )


def _loads_json_object(text: str) -> dict | None:
    """A JSON object, including one with a trailing comma. Incomplete text is not an object."""
    found = usbchat.extract_json_object(text)
    if found:
        return found
    blob = text or ""
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end <= start:
        return None
    snippet = re.sub(r",\s*([}\]])", r"\1", blob[start : end + 1])
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) and data else None


def _json_max_tokens(messages: list[dict], n_ctx: int) -> int:
    used = usbchat.messages_tokens(messages) + usbchat.CTX_SLACK
    room = int(n_ctx) - used
    return max(128, min(1024, room))


def _constructor_call(complete, source: str, task: str, shape: str, feedback: str, n_ctx: int, stop_event, preamble: str = ""):
    if usbchat._stopped(stop_event):
        return None, "", True
    prompt = f"{task}\n\n"
    if preamble.strip():
        prompt += preamble.strip() + "\n\n"
    prompt += (
        f"Resume text:\n{source}\n\n"
        f"Return one JSON object in this shape and nothing else:\n{shape}"
    )
    if feedback.strip():
        prompt += (
            "\n\nThese checks failed. Fix every one of them and return the JSON object again.\n"
            + feedback.strip()
        )
    messages = [
        {"role": "system", "content": _CONSTRUCTOR_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    try:
        raw = complete(messages, max_tokens=_json_max_tokens(messages, n_ctx))
    except TypeError:
        raw = complete(messages)
    if usbchat._stopped(stop_event):
        return None, raw or "", True
    return _loads_json_object(raw), raw or "", False


def _json_failure(section: str, raw: str) -> str:
    text = raw or ""
    if "{" in text and "}" not in text:
        why = "the JSON was cut off before it finished."
    elif "{" in text:
        why = "the JSON text could not be read."
    else:
        why = "the reply was not a JSON object."
    return f"{section}: the constructor failed because {why} Return one JSON object and nothing else."


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [_text(item) for item in value if _text(item)]


def _contact_from(data: dict | None) -> dict | None:
    if not isinstance(data, dict):
        return None
    contact = data.get("contact") if isinstance(data.get("contact"), dict) else data
    if not isinstance(contact, dict):
        return None
    if not any(key in contact for key in ("name", "email", "phone", "location", "links")):
        return None
    return normalize_profile({"contact": contact})["contact"]


def _description_is_text(value) -> bool:
    if value is None or isinstance(value, str):
        return True
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _roles_from(data: dict | None) -> tuple[list[dict], bool] | None:
    if not isinstance(data, dict) or not isinstance(data.get("experience"), list):
        return None
    roles = []
    trusted = True
    for item in data["experience"]:
        if not isinstance(item, dict):
            continue
        desc = item.get("description", item.get("highlights"))
        if "description" not in item and "highlights" not in item:
            trusted = False
        elif not _description_is_text(desc):
            trusted = False
        roles.append(_role(item))
    if not roles and data["experience"]:
        return None
    return roles, trusted and bool(roles)


_SECTION_ORDER = ["contact", "summary", "experience", "projects", "skills", "education"]
_EXPERIENCE_FIELD = re.compile(r"experience\[(\d+)\]\.(description|position|company|location|start|end)")


def _pending_key(item: str) -> str:
    head = item.split(":", 1)[0].strip()
    match = _EXPERIENCE_FIELD.match(head)
    if match:
        index, field = match.group(1), match.group(2)
        return f"description:{index}" if field == "description" else f"role:{index}"
    for name in _SECTION_ORDER:
        if head == name or head.startswith(name + ".") or head.startswith(name + "["):
            return name
    return "*"


def _queue_from(failures: list[str]) -> list[str]:
    keys: list[str] = []
    for item in failures:
        key = _pending_key(item)
        if key == "*":
            return list(_SECTION_ORDER)
        if key not in keys:
            keys.append(key)
    return keys


def _feedback_for(failures: list[str], key: str) -> str:
    lines = [item for item in failures if _pending_key(item) == key]
    return "\n".join(f"- {item}" for item in lines)


def _report(status, label: str, round_no: int) -> None:
    if status is None:
        return
    if round_no == 1:
        status(f"Update profile: structuring {label}")
    else:
        status(f"Update profile: fixing {label} (round {round_no} of {GUARD_ROUNDS})")


def _job_label(role: dict) -> str:
    return (
        f"This request is for the job with position {role.get('position', '')}, "
        f"company {role.get('company', '')}, start {role.get('start', '')}, end {role.get('end', '')}. "
        "Those are already stored. Do not write the position, company, location, or dates in the description."
    )


def _description_lines_from_model(complete, source, role: dict, feedback, n_ctx, stop_event, preamble: str = ""):
    lines: list[str] = []
    task = _job_label(role) + " Copy the next bullet line under this job and no other job."
    for _ in range(10):
        shown = "\n".join(lines) or "(none yet)"
        data, raw, stopped = _constructor_call(
            complete,
            source,
            task + f"\nLines already copied:\n{shown}\nReturn the next line, or an empty line if there are no more.",
            _SHAPES["line"],
            feedback if not lines else "",
            n_ctx,
            stop_event,
            preamble,
        )
        if stopped:
            return None, raw, True
        if not isinstance(data, dict) or "line" not in data:
            return None, raw, False
        line = _text(data.get("line"))
        if not line or line in lines:
            return "\n".join(lines), raw, False
        lines.append(line)
        feedback = ""
    return "\n".join(lines), "", False


def _load_description(complete, source, role: dict, feedback, n_ctx, stop_event, preamble: str = ""):
    data, raw, stopped = _constructor_call(
        complete,
        source,
        _job_label(role) + " Copy only the bullet lines under this job. Use a line break between bullets.",
        _SHAPES["description"],
        feedback,
        n_ctx,
        stop_event,
        preamble,
    )
    if stopped:
        return None, raw, True
    if isinstance(data, dict) and isinstance(data.get("description"), str):
        return data["description"].strip(), raw, False
    return _description_lines_from_model(complete, source, role, feedback, n_ctx, stop_event, preamble)


def _changed(new: str, old: str) -> bool:
    return bool(_text(new)) and not _same(new, old)


def _link_key(link: dict) -> str:
    return _norm(_bare_url(link.get("url") or "") or link.get("url") or "")


def overlay_profile(existing: dict, generated: dict) -> dict:
    """Write the agent's entries into a copy of the saved profile. Leave every other entry."""
    base = normalize_profile(existing)
    incoming = normalize_profile(generated)
    for key in ("name", "email", "phone", "location"):
        if incoming["contact"][key]:
            base["contact"][key] = incoming["contact"][key]
    have_links = {_link_key(item): item for item in base["contact"]["links"] if _link_key(item)}
    for link in incoming["contact"]["links"]:
        key = _link_key(link)
        if not key:
            continue
        match = have_links.get(key)
        if match is None:
            base["contact"]["links"].append(link)
            have_links[key] = link
            continue
        if link.get("title"):
            match["title"] = link["title"]
        if link.get("url"):
            match["url"] = link["url"]
    if incoming["summary"]:
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
                if _same(old["company"], role["company"]) and _same(old["position"], role["position"])
            ),
            None,
        )
        if match is None:
            if any(role[key] for key in ("position", "company", "description")):
                base["experience"].append(role)
            continue
        for key in ("location", "start", "end", "description"):
            if role[key]:
                match[key] = role[key]
    for project in incoming["projects"]:
        if not project["title"] and not project["description"]:
            continue
        match = next((old for old in base["projects"] if _same(old["title"], project["title"])), None)
        if match is None:
            base["projects"].append(project)
            continue
        if project["title"]:
            match["title"] = project["title"]
        if project["description"]:
            match["description"] = project["description"]
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
            if any(school[key] for key in ("school", "degree", "description")):
                base["education"].append(school)
            continue
        for key in ("location", "start", "end", "specialization", "description"):
            if school[key]:
                match[key] = school[key]
    return base


def audit_updates(existing: dict, generated: dict, source: str, failures: list[str]) -> None:
    """Check values the agent added or changed. Leave saved values that this reply did not touch."""
    current = normalize_profile(existing)
    incoming = normalize_profile(generated)
    contact = incoming["contact"]
    saved_contact = current["contact"]
    for key in ("name", "email", "phone", "location"):
        if _changed(contact[key], saved_contact[key]):
            _check_value(
                failures,
                f"contact.{key}",
                contact[key],
                source,
                "Copy that value as it appears in the resume, or leave the saved value.",
            )
    saved_links = {_link_key(item) for item in saved_contact["links"]}
    for index, link in enumerate(contact["links"]):
        url = _bare_url(link.get("url") or "") or link.get("url") or ""
        if _link_key(link) in saved_links:
            continue
        _check_value(
            failures,
            f"contact.links[{index}]",
            url,
            source,
            "Copy the link address as it appears in the resume, or leave the saved links.",
        )
    if _changed(incoming["summary"], current["summary"]):
        for index, sentence in enumerate(re.split(r"(?<=[.!?])\s+", incoming["summary"])):
            _check_value(
                failures,
                f"summary[{index}]",
                sentence.strip(),
                source,
                "Copy the sentence as it appears in the resume, or leave the saved summary.",
            )
    saved_skills = {_norm(item) for item in current["skills"]}
    for index, skill in enumerate(incoming["skills"]):
        if _norm(skill) in saved_skills:
            continue
        _check_value(
            failures,
            f"skills[{index}]",
            skill,
            source,
            "Copy the skill as it appears in the resume, or leave the saved skills.",
        )
    for index, role in enumerate(incoming["experience"]):
        match = next(
            (
                old
                for old in current["experience"]
                if _same(old["company"], role["company"]) and _same(old["position"], role["position"])
            ),
            None,
        )
        field = f"experience[{index}]"
        if match is None:
            _check_entry(failures, field, role, ("position", "company", "start", "end"), source)
            _check_order(failures, field, role, source)
            continue
        for key in ("position", "company", "start", "end"):
            if _changed(role[key], match.get(key) or ""):
                _check_value(
                    failures,
                    f"{field}.{key}",
                    role[key],
                    source,
                    "Copy that value as it appears in the resume, or leave the saved value.",
                )
        if _changed(role["location"], match.get("location") or ""):
            for part in _location_parts(role["location"]):
                _check_value(
                    failures,
                    f"{field}.location",
                    part,
                    source,
                    "Copy that place as it appears in the resume, or leave the saved value.",
                )
        if _changed(role["description"], match.get("description") or ""):
            for line in _description_lines(role["description"]):
                _check_value(
                    failures,
                    f"{field}.description",
                    line,
                    source,
                    "Copy a bullet from the resume. Do not mention the position, company, location, or dates.",
                )
        if _changed(role["start"], match.get("start") or "") or _changed(role["end"], match.get("end") or ""):
            _check_order(failures, field, role, source)
    for index, project in enumerate(incoming["projects"]):
        if not project["title"] and not project["description"]:
            continue
        match = next((old for old in current["projects"] if _same(old["title"], project["title"])), None)
        if match is not None and not _changed(project["description"], match.get("description") or ""):
            if not _changed(project["title"], match.get("title") or ""):
                continue
        for reason in project_mismatches(project, source):
            failures.append(f"projects[{index}]: {reason}")
    for index, school in enumerate(incoming["education"]):
        match = next(
            (
                old
                for old in current["education"]
                if _same(old["degree"], school["degree"]) and _same(old["school"], school["school"])
            ),
            None,
        )
        field = f"education[{index}]"
        if match is None:
            _check_entry(failures, field, school, ("school", "start", "end", "degree", "specialization"), source)
            _check_order(failures, field, school, source)
            continue
        for key in ("school", "start", "end", "degree", "specialization"):
            if _changed(school[key], match.get(key) or ""):
                _check_value(
                    failures,
                    f"{field}.{key}",
                    school[key],
                    source,
                    "Copy that value as it appears in the resume, or leave the saved value.",
                )
        if _changed(school["location"], match.get("location") or ""):
            for part in _location_parts(school["location"]):
                _check_value(
                    failures,
                    f"{field}.location",
                    part,
                    source,
                    "Copy that place as it appears in the resume, or leave the saved value.",
                )
        if _changed(school["description"], match.get("description") or ""):
            for line in _description_lines(school["description"]):
                _check_value(
                    failures,
                    f"{field}.description",
                    line,
                    source,
                    "Copy a bullet from the resume, or leave the saved description.",
                )
        if _changed(school["start"], match.get("start") or "") or _changed(school["end"], match.get("end") or ""):
            _check_order(failures, field, school, source)


def build_update(
    complete,
    model_text: str,
    instruction: str,
    source_text: str,
    status=None,
    stop_event=None,
    n_ctx: int | None = None,
    existing: dict | None = None,
) -> dict:
    """Build the profile as JSON objects, then retry only the sections that fail."""
    ctx = int(n_ctx or usbchat.N_CTX_DEFAULT)
    stored = normalize_profile(existing)
    follow_up = is_follow_up(stored)
    source = model_text.strip()
    if instruction.strip():
        source = instruction.strip() + "\n\n" + source
    preamble = ""
    if follow_up:
        preamble = (
            "Current profile:\n"
            + render_profile(stored).strip()
            + "\n\nThis is a follow-up update. Return the entries for this section after the update. "
            "Keep an entry the resume does not change. Take a new or corrected value from the resume.\n"
        )
        source = source_text.strip()
        if instruction.strip():
            source = instruction.strip() + "\n\n" + source
    pieces = {
        "contact": None,
        "summary": None,
        "skills": None,
        "education": None,
        "experience": None,
        "projects": None,
    }
    loaded = {key: False for key in pieces}
    description_ok: set[int] = set()
    queue = list(_SECTION_ORDER)
    previous: list[str] = []
    failures: list[str] = []

    def stopped_result() -> dict:
        return {"reply": "", "profile_record": None, "dropped": list(failures), "stopped": True}

    def assemble() -> dict:
        raw = empty_profile()
        if loaded["contact"]:
            raw["contact"] = pieces["contact"]
        if loaded["summary"]:
            raw["summary"] = pieces["summary"]
        if loaded["skills"]:
            raw["skills"] = pieces["skills"]
        if loaded["education"]:
            raw["education"] = pieces["education"]
        if loaded["experience"]:
            roles = []
            for index, role in enumerate(pieces["experience"] or []):
                item = dict(role)
                if index not in description_ok:
                    item["description"] = ""
                roles.append(item)
            raw["experience"] = roles
        if loaded["projects"]:
            raw["projects"] = pieces["projects"]
        return raw

    for round_no in range(1, GUARD_ROUNDS + 1):
        if usbchat._stopped(stop_event):
            return stopped_result()
        constructor_failures: list[str] = []
        pending = list(queue)
        queue = []
        while pending:
            key = pending.pop(0)
            if usbchat._stopped(stop_event):
                return stopped_result()
            feedback = _feedback_for(previous, key)
            if key == "contact":
                _report(status, "contact", round_no)
                data, raw, stopped = _constructor_call(
                    complete,
                    source,
                    "Copy the contact details. Each link has a short title and the address. "
                    "Copy the address as it appears. The title is only a name for that address, such as LinkedIn.",
                    _SHAPES["contact"],
                    feedback,
                    ctx,
                    stop_event,
                    preamble,
                )
                if stopped:
                    return stopped_result()
                contact = _contact_from(data)
                if contact is None:
                    constructor_failures.append(_json_failure("contact", raw))
                else:
                    pieces["contact"] = contact
                    loaded["contact"] = True
            elif key == "summary":
                _report(status, "summary", round_no)
                data, raw, stopped = _constructor_call(
                    complete, source, "Copy the professional summary.", _SHAPES["summary"], feedback, ctx, stop_event, preamble
                )
                if stopped:
                    return stopped_result()
                if not isinstance(data, dict) or "summary" not in data:
                    constructor_failures.append(_json_failure("summary", raw))
                else:
                    pieces["summary"] = _text(data.get("summary"))
                    loaded["summary"] = True
            elif key == "skills":
                _report(status, "skills", round_no)
                data, raw, stopped = _constructor_call(
                    complete, source, "Copy the skills.", _SHAPES["skills"], feedback, ctx, stop_event, preamble
                )
                if stopped:
                    return stopped_result()
                if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
                    constructor_failures.append(_json_failure("skills", raw))
                else:
                    pieces["skills"] = _string_list(data.get("skills"))
                    loaded["skills"] = True
            elif key == "education":
                _report(status, "education", round_no)
                data, raw, stopped = _constructor_call(
                    complete, source, "Copy the education.", _SHAPES["education"], feedback, ctx, stop_event, preamble
                )
                if stopped:
                    return stopped_result()
                if not isinstance(data, dict) or not isinstance(data.get("education"), list):
                    constructor_failures.append(_json_failure("education", raw))
                elif any(
                    isinstance(item, dict) and not _description_is_text(item.get("description"))
                    for item in data["education"]
                ):
                    constructor_failures.append(
                        "education: description failed because it was an object. Return description as a string of resume lines."
                    )
                else:
                    pieces["education"] = [_school(item) for item in data["education"] if isinstance(item, dict)]
                    loaded["education"] = True
            elif key == "projects":
                _report(status, "projects", round_no)
                data, raw, stopped = _constructor_call(
                    complete,
                    source,
                    "Copy the projects. Each item has a title string and a description string. "
                    "Copy each title exactly as it is written. "
                    "The description is the resume text that belongs to that title.",
                    _SHAPES["projects"],
                    feedback,
                    ctx,
                    stop_event,
                    preamble,
                )
                if stopped:
                    return stopped_result()
                if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
                    constructor_failures.append(_json_failure("projects", raw))
                elif any(
                    isinstance(item, dict) and not _description_is_text(item.get("description"))
                    for item in data["projects"]
                ):
                    constructor_failures.append(
                        "projects: description failed because it was an object. Return description as a string of resume lines."
                    )
                else:
                    pieces["projects"] = [_project(item) for item in data["projects"] if isinstance(item, dict)]
                    loaded["projects"] = True
            elif key == "experience":
                _report(status, "experience", round_no)
                data, raw, stopped = _constructor_call(
                    complete,
                    source,
                    "Copy every job. description is only the bullet lines, with a line break between bullets. "
                    "Do not mention the position, company, location, or dates in description.",
                    _SHAPES["experience"],
                    feedback,
                    ctx,
                    stop_event,
                    preamble,
                )
                if stopped:
                    return stopped_result()
                parsed = _roles_from(data)
                if parsed is None:
                    data, raw, stopped = _constructor_call(
                        complete,
                        source,
                        "List every job. Leave description for a later step.",
                        _SHAPES["experience_headers"],
                        feedback,
                        ctx,
                        stop_event,
                        preamble,
                    )
                    if stopped:
                        return stopped_result()
                    parsed = _roles_from(data)
                    trust = False
                else:
                    trust = parsed[1]
                if parsed is None:
                    constructor_failures.append(_json_failure("experience", raw))
                else:
                    roles, _trusted = parsed
                    if not trust:
                        for role in roles:
                            role["description"] = ""
                    pieces["experience"] = roles
                    loaded["experience"] = True
                    description_ok = set(range(len(roles))) if trust else set()
                    if not trust:
                        pending.extend(f"description:{index}" for index in range(len(roles)))
            elif key.startswith("description:"):
                index = int(key.split(":", 1)[1])
                roles = pieces["experience"] or []
                if index >= len(roles):
                    continue
                _report(status, f"description {index + 1} of {len(roles)}", round_no)
                text, raw, stopped = _load_description(
                    complete, source, roles[index], feedback, ctx, stop_event, preamble
                )
                if stopped:
                    return stopped_result()
                if text is None:
                    constructor_failures.append(_json_failure(f"experience[{index}].description", raw))
                else:
                    roles[index]["description"] = text
                    description_ok.add(index)
            elif key.startswith("role:"):
                index = int(key.split(":", 1)[1])
                roles = pieces["experience"] or []
                if index >= len(roles):
                    continue
                _report(status, f"experience {index + 1} of {len(roles)}", round_no)
                data, raw, stopped = _constructor_call(
                    complete,
                    source,
                    "Copy this job's position, company, location, and dates. "
                    f"Current position: {roles[index].get('position', '')}. Current company: {roles[index].get('company', '')}.",
                    _SHAPES["role"],
                    feedback,
                    ctx,
                    stop_event,
                    preamble,
                )
                if stopped:
                    return stopped_result()
                if not isinstance(data, dict) or not any(
                    data.get(field) for field in ("position", "company", "title", "employer", "start", "end", "location")
                ):
                    constructor_failures.append(_json_failure(f"experience[{index}].position", raw))
                else:
                    roles[index]["position"] = _text(data.get("position") or data.get("title"))
                    roles[index]["company"] = _text(data.get("company") or data.get("employer"))
                    for field in ("location", "start", "end"):
                        if field in data:
                            roles[index][field] = _text(data.get(field))
            else:
                continue

        failures = list(constructor_failures)
        complete_parts = all(loaded.values()) and (
            not loaded["experience"] or description_ok >= set(range(len(pieces["experience"] or [])))
        )
        generated = assemble()
        if follow_up:
            audit_updates(stored, generated, source_text, failures)
            if complete_parts and not failures:
                profile = overlay_profile(stored, generated)
                return {
                    "reply": render_profile(profile),
                    "profile_record": profile,
                    "dropped": [],
                    "stopped": False,
                }
        elif complete_parts:
            profile = audit_profile(generated, source_text, failures)
            if not failures:
                return {
                    "reply": render_profile(profile),
                    "profile_record": profile,
                    "dropped": [],
                    "stopped": False,
                }
        elif any(loaded.values()):
            audit_profile(generated, source_text, failures)
            failures = [item for item in failures if not item.startswith("profile:")]
        previous = list(failures)
        queue = _queue_from(failures)
        if not queue:
            queue = list(_SECTION_ORDER)

    feedback = "\n".join(f"- {item}" for item in previous)
    reply = (
        f"The profile was not saved. These checks were still failing after {GUARD_ROUNDS} rounds:\n"
        + feedback
    )
    return {"reply": reply, "profile_record": None, "dropped": list(previous), "stopped": False}


def job_profile_text(root: Path, cap: int = 24_000) -> str:
    """Text the job committee reads. JSON wins when it has saved details."""
    rendered = render_profile(load_profile(profile_json_path(root)))
    if rendered.strip():
        return rendered[:cap]
    return usbchat.read_profile(usbchat.profile_path(root), cap=cap)
