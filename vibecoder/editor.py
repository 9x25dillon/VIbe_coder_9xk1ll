"""The full-screen editor: write, run and score without leaving the screen.

T7 W7 and W8. This is the module that assembles the others -- a terminal
session (W1) feeding a key decoder (W2) that drives a buffer (W3), composed
into a damage-tracked frame (W4) with syntax colour (W5) and a rhythm
visualiser (W6) along the bottom.

It deliberately holds no editing logic and no drawing primitives of its own.
Everything here is layout and dispatch, which is what keeps the correctness of
the text provable headless: `compose` can be called against a fake terminal
and the resulting frame asserted as plain text, with no pty involved.

One consequence worth naming. `cli.py` observes that scoring a file from disk
has no honest solve time, so it drops the Speed axis and refuses to bank the
run. This front-end *does* know how long the player worked -- the clock starts
when the editor opens and stops when the tests pass -- so it scores and banks
in full. That is the front-end the comment in `cmd_play` was anticipating.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import levels as level_registry
from . import style
from .keymap import KEYMAP, describe_keys
from .editing import Buffer
from .highlight import highlight_window
from .keys import Key, KeyDecoder
from .models import Level, RunResult, ScoreBreakdown
from .pulse import Pulse
from .runner import reference_benchmark, run_submission
from .screen import Screen
from .scoring import LEVEL_WEIGHTS, score_submission
from .session import Session
from .term import MIN_HEIGHT, MIN_WIDTH, TerminalSession, supported
from .ui import (
    ACCENT,
    BAD,
    Capabilities,
    Depth,
    FAINT,
    GOLD,
    GOOD,
    INK,
    MUTED,
    RGB,
    SPARKS,
    SPARKS_ASCII,
    VIOLET,
    WARN,
    detect,
    sgr,
)

#: Redraw cadence when nothing is being typed, so the rhythm trail keeps
#: moving. A keystroke wakes the loop immediately regardless.
FRAME_INTERVAL = 0.05
#: How long the score gauges take to fill once results arrive.
REVEAL_SECONDS = 0.9
#: A lone Escape is only a keypress once nothing follows it.
ESCAPE_TIMEOUT = 0.05

GUTTER_MIN = 4


@dataclass
class RunOutcome:
    """What the last execution produced, and when, so it can animate in."""

    result: RunResult
    score: ScoreBreakdown | None
    at: float
    elapsed: float
    banked: bool = False
    message: str = ""


@dataclass
class Editor:
    """A level, a buffer, and a screen to draw them on."""

    level: Level
    seed: int = 1
    caps: Capabilities | None = None
    term: TerminalSession | None = None
    session: Session | None = None

    buffer: Buffer = field(init=False)
    pulse: Pulse = field(init=False)
    decoder: KeyDecoder = field(init=False)

    def __post_init__(self) -> None:
        self.buffer = Buffer(self.level.starter.rstrip("\n"))
        self.pulse = Pulse()
        self.decoder = KeyDecoder()
        self.tests = self.level.tests_for(self.seed)
        self.scroll = 0
        self.running = True
        self.outcome: RunOutcome | None = None
        self.status = ""
        self.attempt = 0
        self.first_run_clean = False
        self.started = time.monotonic()
        self.busy = False
        self._previous: Screen | None = None
        self._frame_times: list[float] = []
        self._damage: list[tuple[int, int]] = []
        self._ref: tuple[int, int] | None = None

    # -- painting ----------------------------------------------------------

    @property
    def _caps(self) -> Capabilities:
        if self.caps is None:
            self.caps = detect()
        return self.caps

    def style(self, rgb: RGB | None = None, *, bold: bool = False,
              reverse: bool = False) -> str:
        """SGR prefix for a cell, honouring the terminal's colour depth.

        Returns an empty string at ``Depth.NONE``, which is what makes the
        editor legible on a terminal with no colour at all -- exit criterion 2.
        """
        parts = ""
        if bold:
            parts += "\033[1m"
        if reverse:
            parts += "\033[7m"
        if rgb is not None and self._caps.depth > Depth.NONE:
            parts += sgr(rgb, self._caps.depth)
        return parts

    def glyph(self, name: str) -> str:
        from .ui import GLYPHS

        unicode_glyph, ascii_glyph = GLYPHS[name]
        return unicode_glyph if self._caps.unicode else ascii_glyph

    # -- layout ------------------------------------------------------------

    def compose(self, rows: int, columns: int, now: float | None = None) -> Screen:
        """Build one complete frame. Pure: no terminal, no side effects."""
        now = time.monotonic() if now is None else now
        screen = Screen(rows, columns)

        if rows < MIN_HEIGHT or columns < MIN_WIDTH:
            self._draw_too_small(screen, rows, columns)
            return screen

        code_top = 1
        status_row = rows - 1
        score_row = rows - 2
        pulse_row = rows - 4
        code_bottom = pulse_row - 1  # exclusive

        self._draw_title(screen, columns)
        self._draw_code(screen, code_top, code_bottom, columns)
        self._draw_separator(screen, pulse_row - 1, columns)
        self._draw_pulse(screen, pulse_row, columns, now)
        self._draw_separator(screen, score_row - 1, columns)
        self._draw_score(screen, score_row, columns, now)
        self._draw_status(screen, status_row, columns)
        return screen

    def _draw_too_small(self, screen: Screen, rows: int, columns: int) -> None:
        """Exit criterion 9: say so, rather than draw a corrupted frame."""
        message = f"{columns}x{rows} too small"
        needed = f"need {MIN_WIDTH}x{MIN_HEIGHT}"
        screen.put(max(0, rows // 2 - 1), 0, message[:columns], self.style(BAD))
        if rows > 1:
            screen.put(rows // 2, 0, needed[:columns], self.style(MUTED))

    def _draw_title(self, screen: Screen, columns: int) -> None:
        left = f" {self.level.id} "
        title = f"{self.level.title} "
        screen.fill(0, 0, columns, self.glyph("h"), self.style(FAINT))
        screen.put(0, 1, left, self.style(ACCENT, bold=True))
        screen.put(0, 1 + len(left), title, self.style(INK))
        dot = self.glyph("pause")
        right = f" variant {self.seed} {dot} attempt {self.attempt} "
        if len(right) + 2 < columns:
            screen.put(0, columns - len(right) - 1, right, self.style(FAINT))

    def _gutter_width(self) -> int:
        return max(GUTTER_MIN, len(str(len(self.buffer))) + 2)

    def _draw_code(self, screen: Screen, top: int, bottom: int,
                   columns: int) -> None:
        height = bottom - top
        self._follow_cursor(height)
        gutter = self._gutter_width()
        # Only the visible slice is tokenised: highlighting the whole buffer
        # to draw twenty lines of it is what broke the keystroke budget.
        window = self.buffer.lines[self.scroll : self.scroll + height]
        coloured = highlight_window(window)

        for offset in range(height):
            index = self.scroll + offset
            row = top + offset
            if index >= len(self.buffer):
                break
            current = index == self.buffer.row
            number = str(index + 1).rjust(gutter - 2)
            screen.put(
                row, 0, f" {number} ",
                self.style(ACCENT if current else FAINT, bold=current),
            )
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

    def _draw_separator(self, screen: Screen, row: int, columns: int) -> None:
        if row < 0:
            return
        screen.fill(row, 0, columns, self.glyph("h"), self.style(FAINT))

    def _draw_pulse(self, screen: Screen, row: int, columns: int,
                    now: float) -> None:
        sparks = SPARKS if self._caps.unicode else SPARKS_ASCII
        state = self.pulse.state(now)
        width = max(8, min(28, columns - 34))
        trail = self.pulse.trail(width, now)
        energy = self.pulse.energy(now)

        screen.put(row, 1, self.glyph("spark"),
                   self.style(GOLD if energy > 0.25 else FAINT))
        column = 3
        for value in trail:
            # The glow rides on the trail: recent buckets are brighter, and
            # the whole thing dims as the player stops typing.
            index = min(len(sparks) - 1, int(value * (len(sparks) - 1)))
            colour = FAINT if value == 0 else self._trail_colour(value, energy)
            column = screen.put(row, column, sparks[index], self.style(colour))

        readout = f"  {self.pulse.wpm(now):>3.0f} wpm  {state}"
        if column + len(readout) < columns:
            screen.put(row, column, readout,
                       self.style(MUTED if state in ("idle", "thinking") else INK))

    def _trail_colour(self, value: float, energy: float) -> RGB:
        if value > 0.75:
            return GOLD if energy > 0.3 else WARN
        if value > 0.35:
            return WARN if energy > 0.2 else MUTED
        return MUTED

    def _draw_score(self, screen: Screen, row: int, columns: int,
                    now: float) -> None:
        if self.busy:
            screen.put(row, 1, "running...", self.style(WARN, bold=True))
            return
        if self.outcome is None:
            hint = f"{self.glyph('run')} ctrl-r to run"
            screen.put(row, 1, hint, self.style(FAINT))
            return

        outcome = self.outcome
        # The gauges fill over REVEAL_SECONDS. This is an animated reveal of a
        # finished result, not a live stream: the harness returns one JSON
        # object at the end of a run, so there is nothing to stream yet.
        progress = 1.0
        if self._caps.animate:
            progress = min(1.0, (now - outcome.at) / REVEAL_SECONDS)

        if outcome.result.fatal or outcome.score is None:
            screen.put(row, 1, outcome.message[: columns - 2], self.style(BAD))
            return

        column = 1
        for label, value, rgb in (
            ("acc", outcome.score.accuracy, GOOD),
            ("spd", outcome.score.speed, ACCENT),
            ("fn", outcome.score.functional, VIOLET),
        ):
            column = self._draw_axis(
                screen, row, column, label, value * progress, rgb, columns
            )
        total = f"{outcome.score.total * progress:5.1f}"
        stars = self.glyph("star_full") * outcome.score.stars
        stars += self.glyph("star_empty") * (3 - outcome.score.stars)
        tail = f"{total}  {stars}"
        if column + len(tail) + 1 < columns:
            screen.put(row, columns - len(tail) - 1, tail,
                       self.style(GOLD, bold=True))

    def _draw_axis(self, screen: Screen, row: int, column: int, label: str,
                   value: float, rgb: RGB, columns: int) -> int:
        bar_width = 8
        if column + len(label) + bar_width + 3 >= columns:
            return column
        column = screen.put(row, column, f"{label} ", self.style(MUTED))
        filled = int(round(value / 100.0 * bar_width))
        column = screen.put(
            row, column, self.glyph("bar_full") * filled, self.style(rgb)
        )
        column = screen.put(
            row, column, self.glyph("bar_empty") * (bar_width - filled),
            self.style(FAINT),
        )
        return screen.put(row, column, "  ", "")

    def _draw_status(self, screen: Screen, row: int, columns: int) -> None:
        if self.status:
            screen.put(row, 1, self.status[: columns - 2], self.style(WARN))
            return
        screen.put(row, 1, describe_keys()[: columns - 2], self.style(FAINT))

    def _follow_cursor(self, height: int) -> None:
        if height <= 0:
            return
        if self.buffer.row < self.scroll:
            self.scroll = self.buffer.row
        elif self.buffer.row >= self.scroll + height:
            self.scroll = self.buffer.row - height + 1
        self.scroll = max(0, min(self.scroll, max(0, len(self.buffer) - 1)))

    # -- input -------------------------------------------------------------

    def handle(self, key: Key, now: float | None = None) -> None:
        """Apply one key. Unknown keys are ignored, never inserted."""
        now = time.monotonic() if now is None else now
        self.status = ""

        if key.name == "paste":
            self.buffer.insert(key.text)
            return
        if key.printable:
            self.pulse.press(now)
            self.buffer.insert(key.char)
            return

        action = KEYMAP.get(self._binding(key))
        if action is None:
            return
        self.pulse.press(now)
        action(self)

    @staticmethod
    def _binding(key: Key) -> str:
        if key.ctrl and key.char:
            return f"ctrl-{key.char}"
        return key.name

    # -- running -----------------------------------------------------------

    def execute(self) -> None:
        """Run the buffer against the level's tests and score the attempt."""
        self.busy = True
        started = self.started
        self.attempt += 1
        result = run_submission(self.level, self.buffer.text, self.tests)
        if self.attempt == 1:
            self.first_run_clean = not result.fatal
        elapsed = time.monotonic() - started

        if result.fatal:
            self.outcome = RunOutcome(
                result, None, time.monotonic(), elapsed,
                message=f"{result.error_type}: {result.error}",
            )
            self.busy = False
            return

        if self._ref is None:
            self._ref = reference_benchmark(self.level, self.seed)
        ref_ops, ref_peak = self._ref

        style_results = style.evaluate(
            self.buffer.text, self.level.func_name, self.level.style_goals
        )
        score = score_submission(
            result,
            elapsed_seconds=elapsed,
            par_seconds=self.level.par_seconds,
            ref_ops=ref_ops,
            ref_peak_bytes=ref_peak,
            attempt=self.attempt,
            style_goals_met=style.all_met(style_results),
            first_run_clean=self.first_run_clean,
            weights=LEVEL_WEIGHTS,
        )
        passed = f"{result.passed_count}/{result.total_count} tests"
        self.outcome = RunOutcome(
            result, score, time.monotonic(), elapsed, message=passed
        )
        self.busy = False

        if result.all_passed:
            self._bank(score)

    def _bank(self, score: ScoreBreakdown) -> None:
        """Record a cleared level.

        Unlike ``cmd_play`` reading a file from disk, this front-end knows the
        real solve time, so the Speed axis is honest and the run is banked in
        full rather than treated as practice.
        """
        if self.session is None:
            return
        multipliers = {
            lvl.id: lvl.multiplier for lvl in level_registry.all_levels()
        }
        self.session.submit(
            self.level.id, score, seed=self.seed, multipliers=multipliers
        )
        self.session.save_run(
            self.level.id,
            {
                "level_id": self.level.id,
                "seed": self.seed,
                "attempt": self.attempt,
                "practice": False,
                "code": self.buffer.text,
                "score": score.to_json(),
                "result": self.outcome.result.to_json() if self.outcome else {},
            },
        )
        self.session.save()
        if self.outcome:
            self.outcome.banked = True

    # -- the loop ----------------------------------------------------------

    def loop(self) -> int:
        """Draw, wait, react. Returns a process exit status."""
        term = self.term
        assert term is not None, "loop() needs a terminal session"
        self.started = time.monotonic()

        while self.running:
            rows, columns = term.size()
            if term.resized:
                self._previous = None  # nothing on screen can be trusted

            frame = self.compose(rows, columns)
            output, emitted, changed = frame.diff(self._previous)
            term.write(output)
            self._previous = frame
            if changed:
                self._damage.append((emitted, changed))

            data = term.read(FRAME_INTERVAL)
            if not data:
                # No input: either a lone Escape resolving, or just a tick to
                # keep the rhythm trail moving.
                for key in self.decoder.flush():
                    self.handle(key)
                continue

            arrived = time.monotonic()
            for key in self.decoder.feed(data):
                self.handle(key)
            # Exit criterion 3 is about the delay a person can feel, so it is
            # measured from input arriving to the frame being on the wire.
            frame = self.compose(*term.size())
            output, emitted, changed = frame.diff(self._previous)
            term.write(output)
            self._previous = frame
            self._frame_times.append(time.monotonic() - arrived)
            if changed:
                self._damage.append((emitted, changed))

        return 0

    # -- instruments -------------------------------------------------------

    @property
    def keystroke_latency_ms(self) -> list[float]:
        return [t * 1000 for t in self._frame_times]

    @property
    def damage_ratio(self) -> float:
        """Cells emitted over cells changed. Near 1.0 is the target."""
        emitted = sum(e for e, _ in self._damage)
        changed = sum(c for _, c in self._damage)
        return emitted / changed if changed else 1.0


def play(level: Level, *, seed: int = 1, session: Session | None = None) -> int:
    """Open the editor on ``level``. Restores the terminal whatever happens."""
    if not supported():
        raise RuntimeError(
            "the interactive editor needs a real terminal on both stdin and "
            "stdout; use `vibecoder play` for the non-interactive flow"
        )
    with TerminalSession() as term:
        editor = Editor(level, seed=seed, caps=detect(), term=term,
                        session=session)
        return editor.loop()
