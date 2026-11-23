"""Typed stdio wrappers. Outside clients pass device; they do not get a factory jail."""

from __future__ import annotations

import json
from typing import Any

import tenant
from mcp.registry import PACKS, STDIO_PACKS

FACTORY_ONLY = tuple(name for name in PACKS if name not in STDIO_PACKS)


def _device(raw: str) -> str:
    did = tenant.parse_device_id(raw)
    if not did:
        raise ValueError("missing_device")
    return did


def _dump(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _err(exc: BaseException) -> str:
    return _dump({"ok": False, "error": str(exc)})


def search_web(device: str, query: str, max_n: int = 10, start: int = 1, end: int = 1) -> str:
    try:
        _device(device)
        import web_scrape

        return _dump(web_scrape.search_web(query=query, max_n=max_n, start=start, end=end))
    except Exception as exc:
        return _err(exc)


def get_url(device: str, url: str, start: int = 1, end: int = 1) -> str:
    try:
        _device(device)
        import web_scrape

        return _dump(web_scrape.get_url(url=url, start=start, end=end))
    except Exception as exc:
        return _err(exc)


def post_url(
    device: str,
    url: str,
    body: str = "",
    content_type: str = "application/x-www-form-urlencoded",
    start: int = 1,
    end: int = 1,
) -> str:
    try:
        _device(device)
        import web_scrape

        return _dump(
            web_scrape.post_url(
                url=url,
                body=body or None,
                content_type=content_type,
                start=start,
                end=end,
            )
        )
    except Exception as exc:
        return _err(exc)


def search_dir(
    device: str,
    directory: str,
    name: str = "",
    type: str = "",
    recursive: bool = False,
) -> str:
    try:
        _device(device)
        import file_tools

        return _dump(
            file_tools.search_dir(
                directory=directory,
                name=name or None,
                type=type or None,
                recursive=recursive,
            )
        )
    except Exception as exc:
        return _err(exc)


def read_file(
    device: str,
    directory: str = "",
    name: str = "",
    file_path: str = "",
    start: int = 1,
    end: int = 1,
) -> str:
    try:
        _device(device)
        import file_tools

        return _dump(
            file_tools.read_file(
                directory=directory or None,
                name=name or None,
                file_path=file_path or None,
                start=start,
                end=end,
            )
        )
    except Exception as exc:
        return _err(exc)


def write_doc(
    device: str,
    directory: str,
    name: str,
    type: str = "txt",
    content: str = "",
) -> str:
    try:
        _device(device)
        import file_tools

        return _dump(
            file_tools.write_doc(
                directory=directory,
                name=name,
                type=type,
                content=content,
            )
        )
    except Exception as exc:
        return _err(exc)


def write_pdf(device: str, directory: str, name: str, content: str = "") -> str:
    try:
        _device(device)
        import file_tools

        return _dump(file_tools.write_pdf(directory=directory, name=name, content=content))
    except Exception as exc:
        return _err(exc)


def write_json(device: str, directory: str, name: str, content: str = "") -> str:
    try:
        _device(device)
        import file_tools

        return _dump(file_tools.write_json(directory=directory, name=name, content=content))
    except Exception as exc:
        return _err(exc)


def mkdir(device: str, directory: str, name: str) -> str:
    try:
        _device(device)
        import file_tools

        return _dump(file_tools.mkdir(directory=directory, name=name))
    except Exception as exc:
        return _err(exc)


def append_file(device: str, directory: str, name: str, type: str = "txt", content: str = "") -> str:
    try:
        _device(device)
        import file_tools

        return _dump(
            file_tools.append_file(directory=directory, name=name, type=type, content=content)
        )
    except Exception as exc:
        return _err(exc)


def read_profile(device: str) -> str:
    try:
        did = _device(device)
        import career

        text = career.profile_text(did)
        return _dump({"ok": True, "text": text[:8000]})
    except Exception as exc:
        return _err(exc)


def save_profile(device: str, profile: str) -> str:
    try:
        did = _device(device)
        import career
        import profiledoc

        blob: Any = json.loads(profile) if str(profile).lstrip().startswith("{") else {"text": profile}
        if not isinstance(blob, dict):
            return _dump({"ok": False, "error": "bad_profile"})
        saved = career.save_resume(did, blob, merge=True)
        return _dump({"ok": True, "text": profiledoc.render_profile(saved)[:4000]})
    except Exception as exc:
        return _err(exc)


def check_claims(device: str, text: str) -> str:
    try:
        _device(device)
        import jobapp

        ratio, unsupported = jobapp.claim_ratio(text)
        passed = ratio <= jobapp.HALLUCINATION_LIMIT
        return _dump(
            {
                "ok": True,
                "passed": passed,
                "ratio": ratio,
                "unsupported": unsupported[:20],
            }
        )
    except Exception as exc:
        return _err(exc)


def register(server: Any, names: list[str]) -> list[str]:
    """Attach typed tools for the requested stdio-safe packs. Returns mounted names."""
    wanted = {n.strip() for n in names if n.strip()}
    mounted: list[str] = []
    if "web" in wanted:
        server.tool()(search_web)
        server.tool()(get_url)
        server.tool()(post_url)
        mounted.append("web")
    if "files.read" in wanted:
        server.tool()(search_dir)
        server.tool()(read_file)
        mounted.append("files.read")
    if "files.write" in wanted:
        server.tool()(write_doc)
        server.tool()(write_pdf)
        server.tool()(write_json)
        server.tool()(append_file)
        server.tool()(mkdir)
        mounted.append("files.write")
    if "profile" in wanted:
        server.tool()(read_profile)
        server.tool()(save_profile)
        server.tool()(check_claims)
        mounted.append("profile")
    return mounted
