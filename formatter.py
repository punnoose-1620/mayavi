"""Split answers into Markdown HTML and sandboxed HTML pages. Agents never import this."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import config

_FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_FULL_DOC = re.compile(r"(?is)(?:<!DOCTYPE\s+html\b[^>]*>\s*)?<html\b[^>]*>.*?</html>")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_DEVICE_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)
_SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]+\.html$", re.I)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^[-*+]\s+(.*)$")
_OL = re.compile(r"^\d+\.\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_IMG = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_STAR = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_ITALIC_UND = re.compile(r"(?<![A-Za-z0-9_])_([^_]+)_(?![A-Za-z0-9_])")
_TABLE_ROW = re.compile(r"^\s*\|(.+)\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")

_SKIP = frozenset(
    {
        "script",
        "iframe",
        "object",
        "embed",
        "link",
        "applet",
        "form",
        "input",
        "button",
        "textarea",
        "select",
        "base",
    }
)
_VOID = frozenset({"br", "hr", "img", "meta", "col", "wbr"})
_ALLOW = frozenset(
    {
        "html",
        "head",
        "body",
        "title",
        "meta",
        "style",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "div",
        "span",
        "br",
        "hr",
        "a",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "td",
        "th",
        "pre",
        "code",
        "blockquote",
        "strong",
        "em",
        "b",
        "i",
        "u",
        "img",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "nav",
        "figure",
        "figcaption",
        "dl",
        "dt",
        "dd",
        "small",
        "sub",
        "sup",
    }
)
_SAFE_ATTR = frozenset({"class", "id", "style", "colspan", "rowspan", "alt", "title", "width", "height"})
_MAX_PAGES = 12
_MAX_PAGE_CHARS = 200_000

CSP = (
    "default-src 'none'; img-src data: https: http:; style-src 'unsafe-inline'; "
    "script-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"
)


def format_answer(text: str) -> dict[str, Any]:
    """Turn raw answer text into sanitized Markdown HTML plus HTML view-pages."""
    raw = str(text or "")
    pages: list[dict[str, str]] = []
    chunks: list[str] = []
    idx = 0
    for match in _FENCE.finditer(raw):
        if match.start() > idx:
            md, docs = _take_documents(raw[idx : match.start()])
            pages.extend(docs)
            html_bit = render_markdown(md)
            if html_bit:
                chunks.append(html_bit)
        lang = (match.group(1) or "").strip().split()[0].lower() if match.group(1) else ""
        body = match.group(2) or ""
        label = html.escape(lang or "text")
        chunks.append(
            f'<pre class="code" data-lang="{label}"><code>'
            + html.escape(body.rstrip("\n"))
            + "</code></pre>"
        )
        if lang == "html":
            pages.append(_page(len(pages), "page", body))
        idx = match.end()
    if idx < len(raw):
        md, docs = _take_documents(raw[idx:])
        pages.extend(docs)
        html_bit = render_markdown(md)
        if html_bit:
            chunks.append(html_bit)
    elif not chunks:
        html_bit = render_markdown(raw)
        if html_bit:
            chunks.append(html_bit)
    return {"html": "\n".join(chunks), "pages": pages[:_MAX_PAGES]}


def render_markdown(text: str) -> str:
    source = str(text or "").replace("\r\n", "\n")
    if not source.strip():
        return ""
    lines = source.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            level = min(len(heading.group(1)), 6)
            out.append(f"<h{level}>" + _inline(heading.group(2)) + f"</h{level}>")
            i += 1
            continue
        if _HR.match(line):
            out.append("<hr>")
            i += 1
            continue
        quote = _QUOTE.match(line)
        if quote:
            bits = [quote.group(1)]
            i += 1
            while i < len(lines):
                nxt = _QUOTE.match(lines[i])
                if not nxt:
                    break
                bits.append(nxt.group(1))
                i += 1
            out.append("<blockquote>" + "<br>".join(_inline(b) for b in bits) + "</blockquote>")
            continue
        table = _try_table(lines, i)
        if table:
            html_table, nxt = table
            out.append(html_table)
            i = nxt
            continue
        ul = _UL.match(line)
        ol = _OL.match(line)
        if ul or ol:
            ordered = ol is not None
            tag = "ol" if ordered else "ul"
            items: list[str] = []
            while i < len(lines):
                m = _OL.match(lines[i]) if ordered else _UL.match(lines[i])
                if not m:
                    break
                items.append("<li>" + _inline(m.group(1)) + "</li>")
                i += 1
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip():
            if (
                _HEADING.match(lines[i])
                or _HR.match(lines[i])
                or _UL.match(lines[i])
                or _OL.match(lines[i])
                or _QUOTE.match(lines[i])
            ):
                break
            para.append(lines[i])
            i += 1
        out.append("<p>" + "<br>".join(_inline(p) for p in para) + "</p>")
    return "".join(out)


def html_dir(device_id: str | None = None) -> Path:
    did = str(device_id or "").strip()
    if did and _DEVICE_ID.fullmatch(did):
        path = config.UI_SESSION_DIR / did.lower() / "html"
    else:
        path = config.UI_SESSION_DIR / "html"
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_pages(
    run_id: str,
    pages: list[dict[str, str]],
    *,
    device_id: str | None = None,
) -> list[dict[str, Any]]:
    rid = run_id if _SAFE_ID.fullmatch(str(run_id or "")) else "none"
    folder = html_dir(device_id)
    out: list[dict[str, Any]] = []
    for i, page in enumerate((pages or [])[:_MAX_PAGES]):
        name = _file_name(str(page.get("name") or ""), i)
        body = str(page.get("html") or "")[:_MAX_PAGE_CHARS]
        (folder / f"{rid}_{i}.html").write_text(body, encoding="utf-8")
        query = {"run": rid, "n": str(i)}
        did = str(device_id or "").strip()
        if did and _DEVICE_ID.fullmatch(did):
            query["device"] = did.lower()
        out.append({"name": name, "index": i, "url": "/html?" + urlencode(query)})
    return out


def resolve_page(
    run_id: str | None,
    n: str | None,
    *,
    device_id: str | None = None,
) -> Path | None:
    rid = str(run_id or "").strip()
    if not _SAFE_ID.fullmatch(rid):
        return None
    try:
        index = int(str(n or "0").strip())
    except ValueError:
        return None
    if index < 0 or index >= _MAX_PAGES:
        return None
    folder = html_dir(device_id)
    target = (folder / f"{rid}_{index}.html").resolve()
    root = folder.resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    return target


def _take_documents(text: str) -> tuple[str, list[dict[str, str]]]:
    pages: list[dict[str, str]] = []

    def repl(match: re.Match[str]) -> str:
        pages.append(_page(len(pages), "page", match.group(0)))
        return "\n"

    rest = _FULL_DOC.sub(repl, text)
    return rest, pages


def _page(index: int, hint: str, body: str) -> dict[str, str]:
    return {"name": _file_name(hint, index), "html": wrap_document(body)}


def wrap_document(fragment: str) -> str:
    cleaned = sanitize_html(fragment)
    low = cleaned.lower()
    if "<html" in low:
        return cleaned
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f'<meta http-equiv="Content-Security-Policy" content="{html.escape(CSP, quote=True)}">'
        "<title>HTML</title></head><body>"
        + cleaned
        + "</body></html>"
    )


def sanitize_html(raw: str) -> str:
    parser = _Sanitizer()
    parser.feed(str(raw or "")[:_MAX_PAGE_CHARS])
    parser.close()
    return parser.out


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out = ""
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if name in _SKIP or self._skip:
            if name in _SKIP:
                self._skip += 1
            return
        if name not in _ALLOW:
            return
        self.out += "<" + name + _fmt_attrs(name, attrs)
        self.out += ">"

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in _SKIP:
            if self._skip:
                self._skip -= 1
            return
        if self._skip or name in _VOID or name not in _ALLOW:
            return
        self.out += f"</{name}>"

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.lower()
        if self._skip or name in _SKIP or name not in _ALLOW:
            return
        self.out += "<" + name + _fmt_attrs(name, attrs) + ">"

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        self.out += html.escape(data)


def _fmt_attrs(tag: str, attrs: list[tuple[str, str | None]]) -> str:
    parts: list[str] = []
    for key, value in attrs:
        attr = str(key or "").lower()
        if attr.startswith("on") or attr in {"srcset", "srcdoc", "action", "formaction"}:
            continue
        val = "" if value is None else str(value).strip()
        if attr == "href" and tag == "a":
            if not _safe_href(val):
                continue
        elif attr == "src" and tag == "img":
            if not _safe_src(val):
                continue
        elif attr == "charset" and tag == "meta":
            pass
        elif attr == "http-equiv":
            continue
        elif attr not in _SAFE_ATTR and attr not in {"href", "src", "charset"}:
            continue
        parts.append(" " + attr + '="' + html.escape(val, quote=True) + '"')
    return "".join(parts)


def _safe_href(value: str) -> bool:
    low = value.lower()
    if low.startswith(("javascript:", "data:", "vbscript:")):
        return False
    return low.startswith(("https://", "http://", "mailto:", "#", "/"))


def _safe_src(value: str) -> bool:
    low = value.lower()
    return low.startswith(("https://", "http://", "data:image/"))


def _inline(text: str) -> str:
    s = html.escape(text)
    codes: list[str] = []

    def stash_code(match: re.Match[str]) -> str:
        codes.append("<code>" + match.group(1) + "</code>")
        return f"\x00C{len(codes) - 1}\x00"

    s = _CODE.sub(stash_code, s)
    s = _IMG.sub(lambda m: m.group(1) or "", s)
    s = _LINK.sub(_link_sub, s)
    s = _BOLD.sub(r"<strong>\1</strong>", s)
    s = _ITALIC_STAR.sub(r"<em>\1</em>", s)
    s = _ITALIC_UND.sub(r"<em>\1</em>", s)
    for i, chunk in enumerate(codes):
        s = s.replace(f"\x00C{i}\x00", chunk)
    return s


def _link_sub(match: re.Match[str]) -> str:
    label = match.group(1)
    href = html.unescape(match.group(2)).strip()
    if not _safe_href(href):
        return label
    return (
        f'<a href="{html.escape(href, quote=True)}" rel="noopener noreferrer" '
        f'target="_blank">{label}</a>'
    )


def _try_table(lines: list[str], start: int) -> tuple[str, int] | None:
    if start + 1 >= len(lines):
        return None
    if not _TABLE_ROW.match(lines[start]) or not _TABLE_SEP.match(lines[start + 1]):
        return None
    header = _split_row(lines[start])
    rows: list[list[str]] = []
    i = start + 2
    while i < len(lines) and _TABLE_ROW.match(lines[i]):
        rows.append(_split_row(lines[i]))
        i += 1
    head = "".join(f"<th>{_inline(c)}</th>" for c in header)
    body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>", i


def _split_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|"):
        inner = inner[:-1]
    return [c.strip() for c in inner.split("|")]


def _file_name(hint: str, index: int) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(hint or "")).strip("-.")[:40]
    if slug.lower().endswith(".html"):
        slug = slug[:-5]
    if not slug:
        slug = "page"
    if index:
        slug = f"{slug}-{index + 1}"
    slug += ".html"
    if not _SAFE_FILE.fullmatch(slug):
        slug = f"page-{index + 1}.html"
    return slug
