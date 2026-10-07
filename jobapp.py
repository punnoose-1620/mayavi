"""Job application committee. One local model, English resume and cover letter."""

from __future__ import annotations

from pathlib import Path

import doccompat as usbchat

MAX_PASSES = 3
HALLUCINATION_LIMIT = 0.05

_ENGLISH = (
    "Write in English even when the source is Swedish or another language. "
    "Keep proper nouns, company names, and certification names as written."
)
_HONEST = (
    "Use only facts that appear in the profile board. "
    "Do not add an employer, title, date, skill, metric, or degree that is not there. "
    "You may rephrase a true fact. If a job requirement is missing from the profile, leave it out."
)


def claim_ratio(text: str) -> tuple[float, list[str]]:
    """Share of quoted claims the evaluator marked unsupported. Empty output fails closed."""
    unsupported: list[str] = []
    supported = 0
    for line in (text or "").splitlines():
        raw = line.strip().lstrip("-*").strip()
        lower = raw.lower()
        if lower.startswith("unsupported:"):
            quote = raw.split(":", 1)[1].strip()
            if quote:
                unsupported.append(quote)
        elif lower.startswith("supported:"):
            if raw.split(":", 1)[1].strip():
                supported += 1
    total = supported + len(unsupported)
    if total == 0:
        return 1.0, []
    return len(unsupported) / total, unsupported


def _stopped(stop_event) -> bool:
    return stop_event is not None and stop_event.is_set()


def _ask(complete, status, stop_event, label: str, system: str, blob: str, n_ctx: int) -> tuple[str, bool]:
    budget = usbchat._blob_char_budget(n_ctx, label, system, chars_per_token=4)
    parts = usbchat.chunk_text(blob, budget, max_chunks=8) or [blob]
    pieces: list[str] = []
    for index, part in enumerate(parts, start=1):
        if _stopped(stop_event):
            return "\n\n".join(pieces), True
        step = label if len(parts) == 1 else f"{label} ({index}/{len(parts)})"
        status(step)
        prefix = f"Part {index} of {len(parts)}.\n" if len(parts) > 1 else ""
        text = complete(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": prefix + part},
            ]
        )
        pieces.append((text or "").strip())
    return "\n\n".join(piece for piece in pieces if piece), False


def _write_pdf(build_pdf, folder: Path, stem: str, title: str, body: str) -> Path:
    path = folder / f"{stem}.pdf"
    path.write_bytes(build_pdf(title, body))
    return path


def run_job_application(
    *,
    complete,
    job_text: str,
    profile_text: str,
    n_ctx: int,
    stop_event,
    status,
    build_pdf,
    out_dir: Path,
) -> dict:
    """Distill, write, check claims, then summarize. Returns reply text and PDF paths."""
    result: dict = {
        "reply": "",
        "stopped": False,
        "passed": False,
        "pdf_paths": [],
        "pdf_saves": [],
        "unsupported": [],
    }
    jd_system = (
        "You distill a job description onto a board. The text may be English, Swedish, or another language. "
        + _ENGLISH
        + " Keep the role, required skills, and preferred merits. "
        "Drop firm contacts, equal-opportunity boilerplate, and benefits. "
        "If the user added a short instruction, put it under INSTRUCTION. "
        "Use these headings: ROLE, REQUIREMENTS, MERITS, INSTRUCTION."
    )
    status("Job application: reading the job description")
    jd_board, stopped = _ask(
        complete,
        status,
        stop_event,
        "Job application: distilling the job description",
        jd_system,
        job_text.strip(),
        n_ctx,
    )
    if stopped:
        result["stopped"] = True
        return result

    profile_system = (
        "You distill a professional profile for one job. "
        + _ENGLISH
        + " "
        + _HONEST
        + " Keep contact details, relevant roles, dates, skills, education, and results. "
        "Drop background that this job does not use. "
        "Use these headings: CONTACT, EXPERIENCE, SKILLS, EDUCATION."
    )
    profile_board, stopped = _ask(
        complete,
        status,
        stop_event,
        "Job application: distilling your profile",
        profile_system,
        "Job board:\n" + jd_board + "\n\nProfile:\n" + profile_text.strip(),
        n_ctx,
    )
    if stopped:
        result["stopped"] = True
        return result

    resume = ""
    letter = ""
    unsupported: list[str] = []
    passed = False
    fix = ""
    resume_label = "Job application: writing the resume (pass 1)"
    for pass_no in range(1, MAX_PASSES + 1):
        resume_system = (
            "Write a one-page resume in English. ATS friendly: plain headings, one column, no tables, no icons. "
            + _HONEST
            + " Headings: Contact, Summary, Skills, Experience, Education."
        )
        if fix:
            resume_system += " Remove or rewrite only these unsupported sentences:\n" + fix
        resume, stopped = _ask(
            complete,
            status,
            stop_event,
            resume_label,
            resume_system,
            "Profile board:\n" + profile_board + "\n\nJob board:\n" + jd_board,
            n_ctx,
        )
        if stopped:
            result["stopped"] = True
            return result
        letter_system = (
            "Write a one-page cover letter in English for this role. "
            + _HONEST
            + " Do not repeat the whole resume. No letterhead art."
        )
        if fix:
            letter_system += " Remove or rewrite only these unsupported sentences:\n" + fix
        letter, stopped = _ask(
            complete,
            status,
            stop_event,
            f"Job application: writing the cover letter (pass {pass_no})",
            letter_system,
            "Profile board:\n" + profile_board + "\n\nJob board:\n" + jd_board + "\n\nResume:\n" + resume,
            n_ctx,
        )
        if stopped:
            result["stopped"] = True
            return result
        eval_system = (
            "Check the resume and cover letter against the profile board. "
            "A claim is unsupported when an employer, title, date, skill, metric, or degree is not on the profile. "
            "Rephrasing a true fact is supported. "
            "Reply with one line per claim: 'supported: <sentence>' or 'unsupported: <sentence>'. "
            "Every unsupported line must quote the sentence. Skip a line you cannot quote."
        )
        verdict, stopped = _ask(
            complete,
            status,
            stop_event,
            f"Job application: checking claims (pass {pass_no})",
            eval_system,
            "Profile board:\n" + profile_board + "\n\nResume:\n" + resume + "\n\nCover letter:\n" + letter,
            n_ctx,
        )
        if stopped:
            result["stopped"] = True
            return result
        ratio, unsupported = claim_ratio(verdict)
        result["unsupported"] = unsupported
        parsed = "supported:" in verdict.lower() or bool(unsupported)
        if parsed and ratio <= HALLUCINATION_LIMIT:
            passed = True
            break
        if pass_no >= MAX_PASSES:
            break
        count = len(unsupported)
        noun = "claim" if count == 1 else "claims"
        fix = "\n".join(f"- {quote}" for quote in unsupported) or verdict.strip()
        resume_label = f"Job application: {count} {noun} not on the profile · rewriting (pass {pass_no + 1})"

    result["passed"] = passed
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    if build_pdf is not None and resume.strip():
        resume_path = _write_pdf(build_pdf, folder, "resume", "Resume", resume)
        result["pdf_paths"].append(str(resume_path))
        result["pdf_saves"].append({"label": "Save resume", "path": str(resume_path)})
    if build_pdf is not None and letter.strip():
        letter_path = _write_pdf(build_pdf, folder, "cover-letter", "Cover letter", letter)
        result["pdf_paths"].append(str(letter_path))
        result["pdf_saves"].append({"label": "Save cover letter", "path": str(letter_path)})

    summary_system = (
        "Summarize the chance of landing this job. English only. "
        "Judge from the profile and the job board, not from invented resume lines. "
        "Use these headings and a short justification under each: "
        "Skill match, Merits match, Resume match, Overall match. "
        "Skill match: required skills on the job board that appear in the profile. "
        "Merits match: preferred items that appear in the profile. "
        "Resume match: how much of the job the resume covers without leaving the profile. "
        "Overall match: your conclusion from those three, not an average."
    )
    summary, stopped = _ask(
        complete,
        status,
        stop_event,
        "Job application: writing the summary",
        summary_system,
        "Job board:\n"
        + jd_board
        + "\n\nProfile board:\n"
        + profile_board
        + "\n\nResume:\n"
        + resume
        + "\n\nCover letter:\n"
        + letter,
        n_ctx,
    )
    if stopped:
        result["stopped"] = True
        result["reply"] = summary
        return result
    if not passed:
        quotes = "\n".join(f"- {quote}" for quote in unsupported) or "- The checker could not confirm the claims."
        summary = (
            "This draft did not pass the claim check. "
            "Sentences still not on your profile:\n"
            + quotes
            + "\n\n"
            + summary
        )
    status("Job application: ready")
    result["reply"] = summary.strip()
    result["resume"] = resume.strip()
    result["letter"] = letter.strip()
    return result
