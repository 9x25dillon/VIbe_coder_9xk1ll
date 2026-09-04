"""Syntax colouring for a buffer that is usually not valid Python. T7 W5.

The hazard this module exists to handle: source being typed is incomplete
almost all of the time. ``def f(`` is not a program, and ``tokenize`` says so
by raising. An editor that treats that as an error flickers between coloured
and uncoloured on every keystroke.

So a tokenise failure is the normal case, not the error case. Tokens are
consumed until the generator gives up, whatever it produced is kept, and the
rest of the buffer renders plain. Colour degrades; text never does -- which is
T6's rule (`docs/UI.md`) extended into the editor, and exit criterion 6 for
this trajectory.

The output is renderer-independent: spans carry palette RGB values, and
painting them is the caller's job at whatever depth the terminal supports.
"""

from __future__ import annotations

import io
import keyword
import token as token_module
import tokenize
from typing import NamedTuple

from .ui import ACCENT, FAINT, GOOD, INK, RGB, VIOLET, WARN

#: Names that are always the same colour regardless of what they are bound to.
SOFT_KEYWORDS = frozenset({"match", "case", "_"})

BUILTIN_ACCENT = frozenset({
    "self", "cls", "True", "False", "None",
})


class Span(NamedTuple):
    """A run of characters sharing one colour."""

    text: str
    rgb: RGB | None


def _colour_for(tok: tokenize.TokenInfo, previous: str) -> RGB | None:
    """Palette colour for one token, or None to leave it as plain ink."""
    kind = tok.type
    if kind == token_module.COMMENT:
        return FAINT
    if kind == token_module.STRING or kind == getattr(token_module, "FSTRING_START", -1):
        return GOOD
    if kind == token_module.NUMBER:
        return WARN
    if kind == token_module.NAME:
        if keyword.iskeyword(tok.string):
            return VIOLET
        if tok.string in BUILTIN_ACCENT:
            return VIOLET
        # The name being defined reads better than the keyword introducing it.
        if previous in ("def", "class"):
            return ACCENT
        if tok.string in SOFT_KEYWORDS:
            return VIOLET
        return None
    if kind == token_module.OP:
        return FAINT
    return None


def _tokens(source: str) -> list[tokenize.TokenInfo]:
    """Every token the source yields before it stops being parseable."""
    collected: list[tokenize.TokenInfo] = []
    reader = io.StringIO(source).readline
    generator = tokenize.generate_tokens(reader)
    while True:
        try:
            collected.append(next(generator))
        except StopIteration:
            break
        except (tokenize.TokenError, IndentationError, SyntaxError, ValueError):
            # Incomplete input: keep what parsed, stop asking for more.
            break
    return collected


def colour_map(source: str) -> dict[int, list[tuple[int, int, RGB]]]:
    """``{row: [(start_col, end_col, rgb), ...]}``, rows 0-based."""
    spans: dict[int, list[tuple[int, int, RGB]]] = {}
    previous_name = ""
    for tok in _tokens(source):
        if tok.type in (token_module.NEWLINE, token_module.NL,
                        token_module.INDENT, token_module.DEDENT,
                        token_module.ENDMARKER):
            continue
        rgb = _colour_for(tok, previous_name)
        if tok.type == token_module.NAME:
            previous_name = tok.string
        elif tok.type != token_module.OP:
            previous_name = ""
        if rgb is None:
            continue
        (start_row, start_col), (end_row, end_col) = tok.start, tok.end
        if start_row == end_row:
            spans.setdefault(start_row - 1, []).append((start_col, end_col, rgb))
            continue
        # A triple-quoted string spans lines; colour each row it covers.
        for row in range(start_row, end_row + 1):
            begin = start_col if row == start_row else 0
            finish = end_col if row == end_row else 1_000_000
            spans.setdefault(row - 1, []).append((begin, finish, rgb))
    return spans


def highlight_line(line: str, spans: list[tuple[int, int, RGB]]) -> list[Span]:
    """Split one line into coloured runs. Uncoloured stretches become INK."""
    if not spans:
        return [Span(line, INK)] if line else []
    out: list[Span] = []
    cursor = 0
    for start, end, rgb in sorted(spans):
        start = max(start, cursor)
        end = min(end, len(line))
        if end <= start:
            continue
        if start > cursor:
            out.append(Span(line[cursor:start], INK))
        out.append(Span(line[start:end], rgb))
        cursor = end
    if cursor < len(line):
        out.append(Span(line[cursor:], INK))
    return out


def highlight(source: str) -> list[list[Span]]:
    """Colour every line of ``source``. Never raises, whatever it is given."""
    lines = source.split("\n")
    spans = colour_map(source)
    return [
        highlight_line(line, spans.get(index, []))
        for index, line in enumerate(lines)
    ]


def highlight_window(lines: list[str]) -> list[list[Span]]:
    """Colour a slice of a buffer without tokenising the whole thing.

    The editor calls this on every keystroke, so its cost must depend on the
    size of the *window* rather than the size of the file -- highlighting 400
    lines to draw 18 of them is what put keystroke latency over the 16 ms
    budget in T7 exit criterion 3.

    Two things make a slice harder to tokenise than a whole file. It may begin
    indented, which ``tokenize`` rejects outright as an unexpected indent; and
    it may begin inside a triple-quoted string, which it cannot know about. The
    first is handled by dedenting the slice and shifting the resulting columns
    back. The second degrades to plain text for the affected lines, which is
    the same contract the rest of this module keeps: colour degrades, text
    never does.
    """
    if not lines:
        return []
    indents = [
        len(line) - len(line.lstrip())
        for line in lines
        if line.strip()
    ]
    shift = min(indents) if indents else 0
    if shift:
        body = "\n".join(
            line[shift:] if line.strip() else line for line in lines
        )
    else:
        body = "\n".join(lines)

    spans = colour_map(body)
    out: list[list[Span]] = []
    for index, line in enumerate(lines):
        local = spans.get(index, [])
        if shift and line.strip():
            # Columns were measured against the dedented text.
            local = [(a + shift, b + shift, rgb) for a, b, rgb in local]
        out.append(highlight_line(line, local))
    return out
