"""Typing the fix into a paused fight (T3, Q67).

`boss --live` already pauses *on* the line that raised and resumes from an
edit. Until now the edit arrived as `--fix <path>`, which is scriptable and is
not playing: T3's exit criterion 6 asks for a fight fully playable from the
CLI, and a fix nobody can type does not meet it.

This is Q67's answer. **The edit belongs in the fight**, not in the T7 level
editor. `editor.Editor` is bound to a `Level` — it runs that level's tests,
scores the attempt and banks the result — and a boss step is none of those
things; threading one through a `Level`-shaped API would be dressing a
mismatch up as reuse. What is worth reusing sits a layer down and is reused
here in full: `Buffer` for the text, `KeyDecoder` for the input, and the same
`KEYMAP`, so a player who has used the editor already knows how to drive this.
Ctrl-R runs there and resumes here, which is one idea pointed at a paused
child rather than two bindings to learn.

**The child stays blocked for as long as the player thinks**, and that costs
nothing: its budget counts executing time and never time spent waiting on the
parent (S017). A fight cannot time out for being thought about, which is what
makes an editor at the pause point safe to open at all.

Composition is pure, exactly as the editor's is: `compose` builds a frame from
state and `handle` applies one key, so the whole pane is testable without a
pty, a child process, or a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .editing import Buffer
from .highlight import highlight_window
from .keymap import KEYMAP, REPAIR_HELP, binding, describe_keys
from .keys import Key, KeyDecoder
from .screen import Screen
from .term import MIN_HEIGHT, MIN_WIDTH, TerminalSession, supported
from .ui import (
    ACCENT,
    BAD,
    Capabilities,
    Depth,
    FAINT,
    GLYPHS,
    INK,
    MUTED,
    RGB,
    WARN,
    detect,
    sgr,
)

#: How long the loop waits for input before redrawing. Nothing here animates,
#: so this only decides how quickly a resize is noticed.
FRAME_INTERVAL = 0.1

#: Room for a mark, a line number, and a space either side.
GUTTER_MIN = 6


@dataclass
class Repair:
    """The paused fight, with its source open for editing.

    ``line`` is the 1-based line that raised, which is where the cursor starts
    and which stays marked in the gutter however far the player scrolls away
    from it — the whole point of the pane is to fix *that* line, and a marker
    that scrolls out of sight would make it findable only by remembering.
    """

    code: str
    line: int = 1
    error: str = ""
    func: str = ""
    values: dict[str, str] = field(default_factory=dict)
    title: str = ""
    caps: Capabilities | None = None
    term: TerminalSession | None = None

    def __post_init__(self) -> None:
        self.buffer = Buffer(self.code.rstrip("\n"))
        row = max(0, min(self.line - 1, len(self.buffer) - 1))
        text = self.buffer.lines[row]
        # Land on the first thing worth changing rather than in the indent.
        self.buffer.goto(row, len(text) - len(text.lstrip()))
        self.decoder = KeyDecoder()
        self.scroll = 0
        self.running = True
        #: Whether the player asked to resume, as opposed to giving up.
        self.applied = False
        self.status = ""
        self._previous: Screen | None = None

    # -- painting ----------------------------------------------------------

    @property
    def _caps(self) -> Capabilities:
        if self.caps is None:
            self.caps = detect()
        return self.caps

    def style(self, rgb: RGB | None = None, *, bold: bool = False,
              reverse: bool = False) -> str:
        parts = ""
        if bold:
            parts += "\033[1m"
        if reverse:
            parts += "\033[7m"
        if rgb is not None and self._caps.depth > Depth.NONE:
            parts += sgr(rgb, self._caps.depth)
        return parts

    def glyph(self, name: str) -> str:
        unicode_glyph, ascii_glyph = GLYPHS[name]
        return unicode_glyph if self._caps.unicode else ascii_glyph

    # -- layout ------------------------------------------------------------

    def compose(self, rows: int, columns: int) -> Screen:
        """Build one complete frame. Pure: no terminal, no side effects."""
        screen = Screen(rows, columns)
        if rows < MIN_HEIGHT or columns < MIN_WIDTH:
            self._draw_too_small(screen, rows, columns)
            return screen

        status_row = rows - 1
        code_bottom = status_row - 1  # exclusive; the separator sits on it

        self._draw_title(screen, columns)
        self._draw_failure(screen, 1, columns)
        self._draw_values(screen, 2, columns)
        self._draw_separator(screen, 3, columns)
        self._draw_code(screen, 4, code_bottom, columns)
        self._draw_separator(screen, code_bottom, columns)
        self._draw_status(screen, status_row, columns)
        return screen

    def _draw_too_small(self, screen: Screen, rows: int, columns: int) -> None:
        message = f"{columns}x{rows} too small"
        needed = f"need {MIN_WIDTH}x{MIN_HEIGHT}"
        screen.put(max(0, rows // 2 - 1), 0, message[:columns], self.style(BAD))
        if rows > 1:
            screen.put(rows // 2, 0, needed[:columns], self.style(MUTED))

    def _draw_title(self, screen: Screen, columns: int) -> None:
        screen.fill(0, 0, columns, self.glyph("h"), self.style(FAINT))
        left = " FIX "
        screen.put(0, 1, left, self.style(WARN, bold=True))
        label = f"{self.title} " if self.title else ""
        column = screen.put(0, 1 + len(left), label, self.style(INK))
        if self.func:
            screen.put(0, column, f"{self.func}() ", self.style(MUTED))

    def _draw_failure(self, screen: Screen, row: int, columns: int) -> None:
        mark = self.glyph("cross")
        text = f" {mark} line {self.line}: {self.error}"
        screen.put(row, 0, text[:columns], self.style(BAD, bold=True))

    def _draw_values(self, screen: Screen, row: int, columns: int) -> None:
        """What the code could see at the instant it raised.

        Drawn beside the source rather than left in the scrollback, because
        the alternate screen has just hidden the scrollback and a fix argued
        from remembered values is a guess.
        """
        if not self.values:
            return
        text = "   " + "   ".join(f"{k} = {v}" for k, v in self.values.items())
        screen.put(row, 0, text[:columns], self.style(MUTED))

    def _draw_separator(self, screen: Screen, row: int, columns: int) -> None:
        if row < 0:
            return
        screen.fill(row, 0, columns, self.glyph("h"), self.style(FAINT))

    def _gutter_width(self) -> int:
        return max(GUTTER_MIN, len(str(len(self.buffer))) + 4)

    def _draw_code(self, screen: Screen, top: int, bottom: int,
                   columns: int) -> None:
        height = bottom - top
        self._follow_cursor(height)
        gutter = self._gutter_width()
        # Only the visible slice is tokenised, for the reason T7 found the
        # hard way: highlighting the whole buffer to draw a screenful of it is
        # what put keystroke latency over budget.
        window = self.buffer.lines[self.scroll : self.scroll + height]
        coloured = highlight_window(window)

        for offset in range(height):
            index = self.scroll + offset
            row = top + offset
            if index >= len(self.buffer):
                break
            current = index == self.buffer.row
            broke = index + 1 == self.line
            mark = self.glyph("cross") if broke else " "
            number = str(index + 1).rjust(gutter - 4)
            colour = BAD if broke else (ACCENT if current else FAINT)
            screen.put(row, 0, f" {mark} {number} ",
                       self.style(colour, bold=broke or current))
            column = gutter
            for span in coloured[offset]:
                if column >= columns:
                    break
                column = screen.put(row, column, span.text, self.style(span.rgb))
            if current:
                self._draw_cursor(screen, row, gutter, columns)

    def _draw_cursor(self, screen: Screen, row: int, gutter: int,
                     columns: int) -> None:
        """A block cursor drawn into the frame, since the real one is hidden."""
        column = gutter + self.buffer.column
        if not (gutter <= column < columns):
            return
        under = screen.grid[row][column]
        char = under.char if under.char not in (" ", "\0") else " "
        screen.put(row, column, char, self.style(reverse=True))

    def _draw_status(self, screen: Screen, row: int, columns: int) -> None:
        if self.status:
            screen.put(row, 1, self.status[: columns - 2], self.style(BAD))
            return
        keys = describe_keys(REPAIR_HELP)
        screen.put(row, 1, keys[: columns - 2], self.style(FAINT))

    def _follow_cursor(self, height: int) -> None:
        if height <= 0:
            return
        if self.buffer.row < self.scroll:
            self.scroll = self.buffer.row
        elif self.buffer.row >= self.scroll + height:
            self.scroll = self.buffer.row - height + 1
        self.scroll = max(0, min(self.scroll, max(0, len(self.buffer) - 1)))

    # -- input -------------------------------------------------------------

    def handle(self, key: Key) -> None:
        """Apply one key. Unknown keys are ignored, never inserted."""
        self.status = ""
        if key.name == "paste":
            self.buffer.insert(key.text)
            return
        if key.printable:
            self.buffer.insert(key.char)
            return
        action = KEYMAP.get(binding(key))
        if action is not None:
            action(self)

    def execute(self) -> None:
        """Ctrl-R: hand the edit back to the fight.

        The source is compiled first, and a failure stops here rather than
        resuming. Restarting the child on code that cannot be imported would
        spend a step of the fight to tell the player about a typo this pane
        can point at while the cursor is still next to it.
        """
        try:
            compile(self.buffer.text, "<fix>", "exec")
        except SyntaxError as exc:
            where = f"line {exc.lineno}: " if exc.lineno else ""
            self.status = f"{where}{exc.msg} — not resuming"
            return
        except ValueError as exc:  # e.g. a NUL byte from a stray paste
            self.status = f"{exc} — not resuming"
            return
        self.applied = True
        self.running = False

    # -- the loop ----------------------------------------------------------

    def loop(self) -> bool:
        """Draw, wait, react. True if the player wants to resume."""
        term = self.term
        assert term is not None, "loop() needs a terminal session"
        while self.running:
            rows, columns = term.size()
            if term.resized:
                self._previous = None  # nothing on screen can be trusted

            frame = self.compose(rows, columns)
            output, _, _ = frame.diff(self._previous)
            term.write(output)
            self._previous = frame

            data = term.read(FRAME_INTERVAL)
            if not data:
                # No input: a lone Escape resolving, or just a tick.
                for key in self.decoder.flush():
                    self.handle(key)
                continue
            for key in self.decoder.feed(data):
                self.handle(key)
        return self.applied


def available() -> bool:
    """Whether a player could actually type here.

    False under a pipe, in CI, and in the test suite — which is why `--fix`
    stays: it is the same loop driven by a file instead of a person.
    """
    return supported()


def offer(code: str, *, line: int, error: str = "", func: str = "",
          values: dict[str, str] | None = None, title: str = "") -> str | None:
    """Let the player fix the paused line. The edited source, or ``None``.

    ``None`` means they gave up rather than that nothing changed: a player who
    edits and then quits has not asked for their edit to be run, and guessing
    otherwise would resume a fight they were trying to leave.
    """
    with TerminalSession() as term:
        pane = Repair(
            code=code, line=line, error=error, func=func,
            values=dict(values or {}), title=title,
            caps=detect(), term=term,
        )
        applied = pane.loop()
    return pane.buffer.text if applied else None
