"""Shared terminal composition: bounded regions, quiet chrome, readable prose.

All helpers compose cells, never write to a terminal. Widths are terminal
columns, so a long source line or a wide glyph cannot overwrite an inspector.
"""

from __future__ import annotations

import textwrap

from .screen import Screen, char_width, text_width
from .ui import ACCENT, FAINT, INK, MUTED, Renderer

WIDE = 110


def clip(text: str, width: int) -> str:
    """Fit one line in a region without splitting a double-width character."""
    result = []
    used = 0
    for char in text.replace("\t", "    ").replace("\n", " "):
        size = char_width(char)
        if used + size > max(0, width):
            break
        if char.isprintable() and size:
            result.append(char)
            used += size
    return "".join(result)


def prose(text: str, width: int) -> list[str]:
    """Wrap prose and long values, preserving paragraph breaks."""
    lines = []
    for paragraph in text.splitlines() or [""]:
        for line in textwrap.wrap(paragraph, max(1, width)) or [""]:
            while text_width(line) > width:
                part = clip(line, width)
                if not part:
                    break
                lines.append(part)
                line = line[len(part):]
            lines.append(clip(line, width))
    return lines


def put(screen: Screen, row: int, col: int, text: str, width: int,
        style: str = "") -> int:
    """Write within a caller-owned region rather than the whole screen."""
    return screen.put(row, col, clip(text, width), style)


def header(screen: Screen, ui: Renderer, title: str, meta: str = "") -> None:
    """Reserve metadata first so long titles cannot paint over it."""
    width = screen.columns - 2
    meta = clip(meta, max(0, width // 2))
    left = width - text_width(meta) - (2 if meta else 0)
    put(screen, 0, 1, title, left, ui.style(ACCENT, bold=True))
    if meta:
        screen.put(0, screen.columns - text_width(meta) - 1,
                   meta, ui.style(MUTED))


def divider(screen: Screen, ui: Renderer, row: int) -> None:
    screen.hline(row, 1, max(0, screen.columns - 2), ui.glyph("h"),
                 ui.style(FAINT))


def document(screen: Screen, ui: Renderer, lines: list[tuple[str, tuple]], *,
             top: int, left: int, height: int, width: int, offset: int = 0,
             more: str = "PgUp/PgDn") -> int:
    """A scrollable inspector. Returns its clamped offset after a resize.

Reserve the last row for position whenever the document does not fit, so
truncation is visible and every remaining line is reachable by scrolling.
"""
    available = max(1, height - 1) if len(lines) > height else height
    offset = max(0, min(offset, max(0, len(lines) - available)))
    for index, (text, tone) in enumerate(lines[offset:offset + available]):
        put(screen, top + index, left, text, width, ui.style(tone))
    if len(lines) > height:
        note = f"{offset + 1}-{min(len(lines), offset + available)}/{len(lines)}  {more}"
        put(screen, top + height - 1, left, note, width, ui.style(MUTED))
    return offset


def section(title: str, text: str, width: int) -> list[tuple[str, tuple]]:
    """One inspector section, shared by objectives and paused variables."""
    return ([(line, ACCENT) for line in prose(title, width)]
            + [(line, INK) for line in prose(text, width)] + [("", MUTED)])


def viewport(text: str, start: int, width: int) -> str:
    """Slice terminal columns; a partly visible wide glyph becomes a space."""
    result = []
    column = 0
    for char in text:
        size = char_width(char)
        end = column + size
        if size and end > start and column < start + width:
            if column >= start and end <= start + width:
                result.append(char)
            else:
                result.append(" " * (min(end, start + width) - max(column, start)))
        column = end
        if column >= start + width:
            break
    return "".join(result)
