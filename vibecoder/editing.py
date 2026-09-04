"""Text buffer, cursor and undo history. No drawing, no terminal, no timing.

T7 W3. Everything an editor needs to be *correct* lives here, deliberately
separated from everything it needs to be *visible*. The split is what lets
exit criterion 5 hold -- editing behaviour is proved headless, in CI, without
a pty -- and it means a bug in the renderer can never be a bug in the text.

The buffer is a list of lines with no trailing newline; the cursor is a
``(row, column)`` pair that is always inside it. Column is measured in
characters, not display cells: a line's rendered width is the renderer's
problem, and conflating the two is how editors end up with a cursor that
drifts on a line containing an emoji.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterator, Sequence

INDENT = 4
#: Lines ending in one of these open a block, so the next line indents.
OPENERS = (":",)
QUOTES = ("'", '"')
#: Typing one of these as the first thing on a line closes a block.
DEDENT_KEYWORDS = ("else", "elif", "except", "finally", "return", "pass", "raise")
OPEN_BRACKETS = "([{"
CLOSE_BRACKETS = ")]}"
#: How far back to look for the start of a logical line. A statement spanning
#: more than this many physical lines is pathological, and an unbounded walk
#: would make one Enter keypress cost the whole buffer.
LOOKBACK = 200


def scan(line: str) -> tuple[str, int]:
    """``line`` without its trailing comment, and its net bracket depth change.

    One pass answers both questions because they need the same thing to be
    correct: knowing which characters are inside a string literal. A plain
    ``split("#")`` cuts ``sep = "#"`` in half, and a plain ``count("(")``
    counts the parenthesis in ``s = "(("``.

    The quoting model is deliberately shallow -- single and double quotes with
    backslash escapes -- and does not attempt triple-quoted strings. That
    covers every line that ends a statement, which is all the auto-indent
    looks at. A line inside a docstring can be misread; the cost is one
    wrong indent level, not a wrong program.
    """
    quote = ""
    escaped = False
    depth = 0
    for index, character in enumerate(line):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if quote:
            if character == quote:
                quote = ""
            continue
        if character in QUOTES:
            quote = character
            continue
        if character == "#":
            return line[:index], depth
        if character in OPEN_BRACKETS:
            depth += 1
        elif character in CLOSE_BRACKETS:
            depth -= 1
    return line, depth


def code_part(line: str) -> str:
    """``line`` with any trailing comment removed.

    ``if x:  # only the expensive ones`` opens a block just as much as
    ``if x:`` does, so the auto-indent check has to look past the comment.
    """
    return scan(line)[0]


def logical_line(lines: Sequence[str], row: int) -> tuple[int, int]:
    """``(first row of the logical line ending at row, bracket depth inherited)``.

    Walks backwards rather than forwards from the top of the buffer, because
    this runs on every Enter and a forward scan would make that cost grow with
    the file. Accumulating deltas from ``row - 1`` downwards, the first line
    that leaves the running total *positive* is the one holding a bracket open
    across our line: it starts the logical line, and the total is the depth we
    inherit from it. A balanced pair that opened and closed above us nets out
    to zero on the way past, which is exactly the answer we want.
    """
    depth = 0
    for index in range(row - 1, max(-1, row - 1 - LOOKBACK), -1):
        depth += scan(lines[index])[1]
        if depth > 0:
            return index, depth
    return row, 0


def depth_before(lines: Sequence[str], row: int) -> int:
    """Bracket depth at the start of ``lines[row]``."""
    return logical_line(lines, row)[1]


def opens_block_at(line: str, inherited_depth: int) -> bool:
    """Whether ``line`` opens a block, given the depth it inherits.

    Split from :func:`opens_block` so a caller that already knows where the
    logical line starts does not walk backwards a second time to find out.
    """
    code, delta = scan(line)
    return code.rstrip().endswith(OPENERS) and inherited_depth + delta <= 0


def opens_block(lines: Sequence[str], row: int) -> bool:
    """Whether the logical line ending at ``lines[row]`` opens an indented block.

    The test is a trailing colon **at bracket depth zero**, which is what makes
    this a question about the logical line rather than the physical one. Inside
    brackets a colon is a dict entry, a slice or an annotation, and indenting
    after it is wrong::

        d = {
            'key':      <- a value follows, not a block

    while a colon that closes a continued signature is right::

        def f(a,
              b):       <- a block follows

    Both lines end in a colon. Only the depth tells them apart.
    """
    return opens_block_at(lines[row], depth_before(lines, row))


@dataclass(frozen=True)
class Snapshot:
    """An immutable point in the buffer's history."""

    lines: tuple[str, ...]
    row: int
    column: int


class Buffer:
    """Editable text with a cursor and an undo history.

    Mutating methods coalesce into undo *steps* rather than recording one
    entry per keystroke: typing a word then deleting it is two undos, not
    eleven. The rule is that consecutive edits of the same kind merge, and any
    other action -- a newline, a cursor move, a different kind of edit --
    closes the current step.
    """

    def __init__(self, text: str = "", *, undo_limit: int = 200) -> None:
        self.lines: list[str] = text.split("\n") if text else [""]
        self.row = 0
        self.column = 0
        self._undo: list[Snapshot] = []
        self._redo: list[Snapshot] = []
        self._open_kind: str | None = None
        self._undo_limit = undo_limit
        #: Column the cursor *wants* when moving vertically, so travelling
        #: through a short line and out the other side returns to where it
        #: started. Editors that omit this feel subtly broken.
        self._goal: int | None = None

    # -- reading -----------------------------------------------------------

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def line(self) -> str:
        return self.lines[self.row]

    def __len__(self) -> int:
        return len(self.lines)

    def __iter__(self) -> Iterator[str]:
        return iter(self.lines)

    def snapshot(self) -> Snapshot:
        return Snapshot(tuple(self.lines), self.row, self.column)

    # -- history -----------------------------------------------------------

    def _checkpoint(self, kind: str) -> None:
        """Open a new undo step unless the current one is the same kind."""
        if self._open_kind == kind:
            return
        self._undo.append(self.snapshot())
        if len(self._undo) > self._undo_limit:
            self._undo.pop(0)
        self._redo.clear()
        self._open_kind = kind

    def break_undo(self) -> None:
        """Close the current undo step. The next edit starts a fresh one."""
        self._open_kind = None

    def _restore(self, snap: Snapshot) -> None:
        self.lines = list(snap.lines)
        self.row = snap.row
        self.column = snap.column
        self._goal = None

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.snapshot())
        self._restore(self._undo.pop())
        self._open_kind = None
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.snapshot())
        self._restore(self._redo.pop())
        self._open_kind = None
        return True

    # -- cursor ------------------------------------------------------------

    def _clamp(self) -> None:
        self.row = max(0, min(self.row, len(self.lines) - 1))
        self.column = max(0, min(self.column, len(self.lines[self.row])))

    def move(self, d_row: int = 0, d_column: int = 0) -> None:
        self.break_undo()
        if d_row:
            # Vertical motion remembers the column it started from.
            goal = self._goal if self._goal is not None else self.column
            self.row = max(0, min(self.row + d_row, len(self.lines) - 1))
            self.column = min(goal, len(self.line))
            self._goal = goal
            return
        self._goal = None
        if d_column < 0 and self.column == 0 and self.row > 0:
            self.row -= 1
            self.column = len(self.line)
            return
        if d_column > 0 and self.column == len(self.line) and self.row < len(self.lines) - 1:
            self.row += 1
            self.column = 0
            return
        self.column = max(0, min(self.column + d_column, len(self.line)))

    def home(self) -> None:
        """First non-space, then column zero. The second press does the rest."""
        self.break_undo()
        self._goal = None
        stripped = len(self.line) - len(self.line.lstrip())
        self.column = 0 if self.column == stripped else stripped

    def end(self) -> None:
        self.break_undo()
        self._goal = None
        self.column = len(self.line)

    def goto(self, row: int, column: int) -> None:
        self.break_undo()
        self._goal = None
        self.row, self.column = row, column
        self._clamp()

    # -- editing -----------------------------------------------------------

    def insert(self, text: str) -> None:
        """Insert printable text at the cursor. Newlines are handled."""
        if not text:
            return
        if "\n" in text:
            # A paste. One undo step for the whole thing.
            self._checkpoint("paste")
            self.break_undo()
            head, *rest = text.split("\n")
            self._insert_inline(head)
            for chunk in rest:
                self._split_line()
                self._insert_inline(chunk)
            return
        self._checkpoint("insert")
        self._insert_inline(text)

    def _insert_inline(self, text: str) -> None:
        line = self.line
        self.lines[self.row] = line[: self.column] + text + line[self.column :]
        self.column += len(text)
        self._goal = None

    def _split_line(self) -> None:
        line = self.line
        self.lines[self.row] = line[: self.column]
        self.lines.insert(self.row + 1, line[self.column :])
        self.row += 1
        self.column = 0
        self._goal = None

    def newline(self) -> None:
        """Split the line, carrying the indentation the code implies."""
        self._checkpoint("newline")
        self.break_undo()
        current = self.line
        # One backward walk answers both questions: whether a block opens, and
        # where to measure its indentation from.
        start_row, inherited = logical_line(self.lines, self.row)
        if opens_block_at(current, inherited):
            # Indent the body from where the *statement* began, not from this
            # physical line: the body of ``def f(a,\n      b):`` belongs one
            # level in from ``def``, not one level in from ``b``.
            start = self.lines[start_row]
            indent = len(start) - len(start.lstrip()) + INDENT
        else:
            # No block: keep this line's own indentation, which is what holds
            # a hand-aligned continuation where the author put it.
            indent = len(current) - len(current.lstrip())
        self._split_line()
        if indent:
            self._insert_inline(" " * indent)

    def backspace(self) -> None:
        if self.column == 0 and self.row == 0:
            return
        self._checkpoint("delete")
        if self.column == 0:
            above = self.lines[self.row - 1]
            self.column = len(above)
            self.lines[self.row - 1] = above + self.line
            del self.lines[self.row]
            self.row -= 1
            self._goal = None
            return
        # Inside leading whitespace, delete back to the previous indent stop.
        line = self.line
        if line[: self.column].strip() == "" and self.column % INDENT == 0:
            width = INDENT
        else:
            width = 1
        self.lines[self.row] = line[: self.column - width] + line[self.column :]
        self.column -= width
        self._goal = None

    def delete(self) -> None:
        """Forward delete."""
        line = self.line
        if self.column == len(line):
            if self.row == len(self.lines) - 1:
                return
            self._checkpoint("delete")
            self.lines[self.row] = line + self.lines[self.row + 1]
            del self.lines[self.row + 1]
            return
        self._checkpoint("delete")
        self.lines[self.row] = line[: self.column] + line[self.column + 1 :]

    def indent(self) -> None:
        self._checkpoint("indent")
        self.break_undo()
        self.lines[self.row] = " " * INDENT + self.line
        self.column += INDENT

    def dedent(self) -> None:
        line = self.line
        removable = len(line) - len(line.lstrip())
        if not removable:
            return
        self._checkpoint("indent")
        self.break_undo()
        width = min(INDENT, removable)
        self.lines[self.row] = line[width:]
        self.column = max(0, self.column - width)

    def tab(self) -> None:
        """Tab indents the line when leading, inserts spaces when not."""
        if self.line[: self.column].strip() == "":
            self.indent()
        else:
            self.insert(" " * (INDENT - self.column % INDENT))

    def kill_line(self) -> None:
        """Delete to end of line, or join the next line when already there."""
        if self.column == len(self.line):
            self.delete()
            return
        self._checkpoint("kill")
        self.break_undo()
        self.lines[self.row] = self.line[: self.column]

    def load(self, text: str) -> None:
        """Replace the whole buffer, as one undo step."""
        self._checkpoint("load")
        self.break_undo()
        self.lines = text.split("\n") if text else [""]
        self.row = min(self.row, len(self.lines) - 1)
        self._clamp()
