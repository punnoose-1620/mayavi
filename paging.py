"""Shared page windows. Not an agent-facing tool."""

from __future__ import annotations

from config import CHAR_PAGE, MAX_PAGE_SPAN, ROW_PAGE


def clamp_window(start: int | None, end: int | None) -> tuple[int, int]:
    start_i = 1 if start is None else int(start)
    end_i = start_i if end is None else int(end)
    if start_i < 1:
        start_i = 1
    if end_i < start_i:
        end_i = start_i
    if end_i - start_i + 1 > MAX_PAGE_SPAN:
        end_i = start_i + MAX_PAGE_SPAN - 1
    return start_i, end_i


def slice_chars(text: str, start: int | None, end: int | None) -> tuple[str, int, int, int]:
    start_i, end_i = clamp_window(start, end)
    total = max(1, (len(text) + CHAR_PAGE - 1) // CHAR_PAGE) if text else 1
    begin = (start_i - 1) * CHAR_PAGE
    stop = end_i * CHAR_PAGE
    return text[begin:stop], start_i, end_i, total


def slice_rows(rows: list, start: int | None, end: int | None) -> tuple[list, int, int, int]:
    start_i, end_i = clamp_window(start, end)
    total = max(1, (len(rows) + ROW_PAGE - 1) // ROW_PAGE) if rows else 1
    begin = (start_i - 1) * ROW_PAGE
    stop = end_i * ROW_PAGE
    return rows[begin:stop], start_i, end_i, total


def char_chunk_ok(text: str) -> bool:
    return len(text) <= CHAR_PAGE * MAX_PAGE_SPAN


def row_chunk_ok(rows: list) -> bool:
    return len(rows) <= ROW_PAGE * MAX_PAGE_SPAN
