"""Turn a reply into display blocks plus sanitized HTML pages. No factory imports."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser

_FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_FULL_DOC = re.compile(r"(?is)(?:<!DOCTYPE\s+html\b[^>]*>\s*)?<html\b[^>]*>.*?</html>")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_HR = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})\s*$")
_UL = re.compile(r"^[-*+]\s+(.*)$")
_OL = re.compile(r"^\d+\.\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_SAFE_FILE = re.compile(r"^[A-Za-z0-9._-]+\.html$", re.I)

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


@dataclass
class Block:
    kind: str
    text: str = ""
    level: int = 0
    lang: str = ""
    items: tuple[str, ...] = ()
    html: str = ""
    name: str = ""
    ordered: bool = False


def format_blocks(text: str) -> list[Block]:
    """Parse Markdown-ish text into widgets the USB History can embed."""
    raw = str(text or "").replace("\r\n", "\n")
    blocks: list[Block] = []
    idx = 0
    for match in _FENCE.finditer(raw):
        if match.start() > idx:
            blocks.extend(_md_and_docs(raw[idx : match.start()]))
        lang = (match.group(1) or "").strip().split()[0].lower() if match.group(1) else ""
        body = (match.group(2) or "").rstrip("\n")
        blocks.append(Block(kind="code", text=body, lang=lang))
        if lang == "html":
            blocks.append(_html_block(len(blocks), body))
        idx = match.end()
    if idx < len(raw):
        blocks.extend(_md_and_docs(raw[idx:]))
    elif not blocks:
        blocks.extend(_md_and_docs(raw))
    return blocks or [Block(kind="paragraph", text=raw.strip())]


def html_pages(blocks: list[Block]) -> list[Block]:
    return [b for b in blocks if b.kind == "html_doc" and b.html.strip()]


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


def _md_and_docs(text: str) -> list[Block]:
    pages: list[Block] = []

    def repl(match: re.Match[str]) -> str:
        pages.append(_html_block(len(pages), match.group(0)))
        return "\n"

    rest = _FULL_DOC.sub(repl, text)
    return _markdown_blocks(rest) + pages[: _MAX_PAGES - 0]


def _html_block(index: int, body: str) -> Block:
    name = _file_name("page", index)
    return Block(kind="html_doc", name=name, html=wrap_document(body), text=name)


def _markdown_blocks(text: str) -> list[Block]:
    source = str(text or "")
    if not source.strip():
        return []
    lines = source.split("\n")
    out: list[Block] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            out.append(Block(kind="heading", text=heading.group(2).strip(), level=min(len(heading.group(1)), 6)))
            i += 1
            continue
        if _HR.match(line):
            out.append(Block(kind="rule"))
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
            out.append(Block(kind="quote", text="\n".join(bits)))
            continue
        ul = _UL.match(line)
        ol = _OL.match(line)
        if ul or ol:
            ordered = ol is not None
            items: list[str] = []
            while i < len(lines):
                m = _OL.match(lines[i]) if ordered else _UL.match(lines[i])
                if not m:
                    break
                items.append(m.group(1))
                i += 1
            out.append(Block(kind="list", items=tuple(items), ordered=ordered, text="\n".join(items)))
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
        out.append(Block(kind="paragraph", text="\n".join(para)))
    return out


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
