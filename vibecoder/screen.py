"""A cell grid that emits only what changed. T7 W4.

Repainting the whole screen on every keystroke is the obvious implementation
and it is wrong twice: it flickers, and over ssh it spends a kilobyte to move
one character. So a frame is composed into a grid, compared against the frame
already on screen, and only the differing cells are written.

The unit is a *cell*, not a character, because they are not the same thing. An
emoji in a comment is one character and two columns wide; a combining accent is
one character and zero. Getting this wrong shifts everything to the right of it,
which is the class of bug that makes a terminal UI look broken rather than
buggy. ``put`` measures in columns and marks the second half of a wide
character as a continuation cell so the diff never splits one.

The damage ratio -- cells emitted over cells changed -- is the instrument check
for this waypoint. It should sit near 1.0; drift upward means the diff is
giving up and repainting more than it needs to.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field

RESET = "\033[0m"

#: Moving the cursor costs bytes too, so two changed runs separated by only a
#: few unchanged cells are cheaper to emit as one. Roughly the length of a
#: cursor-position sequence.
RUN_GAP = 6

#: Marks the right-hand half of a double-width character. Never emitted.
CONTINUATION = "\0"


def char_width(char: str) -> int:
    """Columns one character occupies: 0, 1, or 2."""
    if unicodedata.combining(char):
        return 0
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return 2
    if char == "\0":
        return 0
    return 1


def text_width(text: str) -> int:
    return sum(char_width(character) for character in text)


@dataclass(frozen=True)
class Cell:
    char: str = " "
    style: str = ""

    def __bool__(self) -> bool:
        return self.char != " " or bool(self.style)


BLANK = Cell()


@dataclass
class Screen:
    """A fixed-size grid of styled cells."""

    rows: int
    columns: int
    grid: list[list[Cell]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.grid:
            self.clear()

    def clear(self) -> None:
        self.grid = [
            [BLANK for _ in range(self.columns)] for _ in range(self.rows)
        ]

    def resize(self, rows: int, columns: int) -> None:
        self.rows, self.columns = rows, columns
        self.clear()

    # -- composing ---------------------------------------------------------

    def put(self, row: int, column: int, text: str, style: str = "") -> int:
        """Write ``text`` at ``(row, column)``. Returns the column after it.

        Clips at the right edge rather than wrapping: a frame that wraps has
        already lost, because the row below it belongs to something else.
        """
        if not (0 <= row < self.rows):
            return column
        for character in text:
            width = char_width(character)
            if width == 0:
                continue  # combining marks attach to the previous cell
            if column >= self.columns:
                break
            if column < 0:
                column += width
                continue
            self.grid[row][column] = Cell(character, style)
            if width == 2 and column + 1 < self.columns:
                self.grid[row][column + 1] = Cell(CONTINUATION, style)
            column += width
        return column

    def fill(self, row: int, column: int, width: int, char: str = " ",
             style: str = "") -> None:
        self.put(row, column, char * width, style)

    def hline(self, row: int, column: int, width: int, char: str,
              style: str = "") -> None:
        self.fill(row, column, width, char, style)

    # -- emitting ----------------------------------------------------------

    def diff(self, previous: "Screen | None") -> tuple[str, int, int]:
        """Escape string that turns ``previous`` into ``self``.

        Also returns ``(cells_emitted, cells_changed)`` for the damage ratio.
        A ``previous`` of a different size is treated as no previous frame at
        all, because nothing on screen can be trusted after a resize.
        """
        full = (
            previous is None
            or previous.rows != self.rows
            or previous.columns != self.columns
        )
        out: list[str] = []
        emitted = changed = 0
        if full:
            out.append("\033[2J")

        for row in range(self.rows):
            old = None if full else previous.grid[row]
            new = self.grid[row]
            spans = self._spans(old, new)
            for start, end in spans:
                changed += sum(
                    1 for i in range(start, end)
                    if old is None or old[i] != new[i]
                )
                emitted += end - start
                out.append(f"\033[{row + 1};{start + 1}H")
                out.append(self._paint(new, start, end))

        return "".join(out), emitted, changed

    def _spans(self, old: list[Cell] | None, new: list[Cell]) -> list[tuple[int, int]]:
        """Column ranges worth redrawing, with near-misses merged."""
        dirty = [
            column
            for column in range(self.columns)
            if old is None or old[column] != new[column]
        ]
        if not dirty:
            return []
        spans: list[list[int]] = [[dirty[0], dirty[0] + 1]]
        for column in dirty[1:]:
            if column - spans[-1][1] <= RUN_GAP:
                spans[-1][1] = column + 1
            else:
                spans.append([column, column + 1])
        # A span must not begin on the trailing half of a wide character, or
        # the cursor lands mid-glyph and the terminal draws nonsense.
        adjusted = []
        for start, end in spans:
            while start > 0 and new[start].char == CONTINUATION:
                start -= 1
            adjusted.append((start, end))
        return adjusted

    def _paint(self, row: list[Cell], start: int, end: int) -> str:
        out: list[str] = []
        style = ""
        for column in range(start, end):
            cell = row[column]
            if cell.char == CONTINUATION:
                continue  # drawn by the cell to its left
            if cell.style != style:
                out.append(RESET if not cell.style else cell.style)
                style = cell.style
            out.append(cell.char)
        if style:
            out.append(RESET)
        return "".join(out)

    # -- inspection --------------------------------------------------------

    def line(self, row: int) -> str:
        """Row ``row`` as plain text. For tests and for snapshotting frames."""
        return "".join(
            cell.char for cell in self.grid[row] if cell.char != CONTINUATION
        ).rstrip()

    def as_text(self) -> str:
        return "\n".join(self.line(row) for row in range(self.rows))
