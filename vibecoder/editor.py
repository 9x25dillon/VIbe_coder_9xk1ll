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

import gc
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from . import levels as level_registry
from . import style, tips, cockpit
from .keymap import KEYMAP, binding
from .editing import Buffer
from .highlight import highlight_window
from .keys import Key, KeyDecoder
from .models import Level, RunResult, ScoreBreakdown, Source
from .pulse import Pulse
from .runner import reference_benchmark, run_submission
from .screen import Screen, text_width
from .scoring import LEVEL_WEIGHTS, score_submission
from .session import Session
from .term import MIN_HEIGHT, MIN_WIDTH, TerminalSession, supported
from .ui import (
    ACCENT,
    BAD,
    Capabilities,
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
    Renderer,
)

#: Redraw cadence when nothing is being typed, so the rhythm trail keeps
#: moving. A keystroke wakes the loop immediately regardless.
FRAME_INTERVAL = 0.05
#: How long the score gauges take to fill once results arrive.
REVEAL_SECONDS = 0.9
#: A lone Escape is only a keypress once nothing follows it.
ESCAPE_TIMEOUT = 0.05

GUTTER_MIN = 4


@contextmanager
def steady_heap():
    """Keep garbage collection pauses off the keystroke path.

    CPython's collector is generational, and the cost of a pass is a function
    of how many objects it has to walk -- which for a running game means the
    levels, the profile and the session state, none of which a keystroke can
    make garbage. So the pause a player feels is set by the size of the rest
    of the process rather than by anything the editor did, and it grows as the
    game does. Measured at 4000 lines, identical work each time: a worst-case
    keystroke of 6.8ms on a bare process, 20.7ms with 420,000 extra live
    objects, and 102.7ms with 4.2 million.

    ``gc.freeze`` moves everything alive at entry into a permanent generation
    that collections skip, which flattens all three to 5-7ms. This
    does **not** disable collection: garbage created while editing is still
    collected normally. It trades the memory of one editing session -- cycles
    among the frozen objects are not reclaimed until exit -- for a bounded
    keystroke, which is the right way round for a session that lasts minutes
    and must never stutter.
    """
    gc.collect()
    gc.freeze()
    try:
        yield
    finally:
        gc.unfreeze()


@dataclass
class LiveRun:
    """A run in flight, as reported test by test.

    Accuracy is the one axis that can honestly assemble while a run is
    happening: it is passed-over-total and both are known as each test lands.
    Speed needs the elapsed total and Functional needs the operation count
    against the reference, and neither exists until the run is over -- so
    neither is drawn until it does. Filling all three from a partial result
    would look better and mean less.
    """

    total: int = 0
    done: int = 0
    passed: int = 0
    marks: list[bool] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        """0..100 over the tests reported so far."""
        return 100.0 * self.passed / self.done if self.done else 0.0


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
        self.horizontal_scroll = 0
        self.running = True
        self.outcome: RunOutcome | None = None
        self.status = ""
        self.attempt = 0
        self.first_run_clean = False
        self.started = time.monotonic()
        self.busy = False
        self.live: LiveRun | None = None
        self._previous: Screen | None = None
        self._frame_times: list[float] = []
        self._damage: list[tuple[int, int]] = []
        self._ref: tuple[int, int] | None = None
        self.objective_open = False
        self.help_open = False
        self.show_rhythm = False
        self.panel_scroll = 0
        self.advice = "Read the objective, then run your code with ctrl-r."
        self.previous_total: float | None = None
        self.score_delta: float | None = None
        self.earned_hint = ""

    # -- painting ----------------------------------------------------------

    @property
    def _caps(self) -> Capabilities:
        if self.caps is None:
            self.caps = detect()
        return self.caps

    def style(self, rgb: RGB | None = None, *, bold: bool = False,
              reverse: bool = False) -> str:
        """SGR prefix for a cell, honouring the terminal's colour depth.

        Color is suppressed at ``Depth.NONE``; reverse video remains available
        so the block cursor is visible without color.
        """
        return Renderer(self._caps).style(rgb, bold=bold, reverse=reverse)

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

        ui = Renderer(self._caps)
        code_bottom = rows - 6
        self._draw_title(screen, columns)
        if self.objective_open or self.help_open:
            width = columns - 4
            lines = self._help_lines(width) if self.help_open else self._objective_lines(width)
            self.panel_scroll = cockpit.document(
                screen, ui, lines, top=2, left=2, height=code_bottom - 2,
                width=width, offset=self.panel_scroll,
            )
        else:
            code_width = columns if columns < cockpit.WIDE else columns - 38
            self._draw_code(screen, 1, code_bottom, code_width)
            if code_width < columns:
                for row in range(1, code_bottom):
                    screen.put(row, code_width, self.glyph("v"), self.style(FAINT))
                cockpit.document(screen, ui, self._objective_lines(34),
                                 top=2, left=code_width + 2,
                                 height=code_bottom - 2, width=34, more="ctrl-o expand")
        cockpit.divider(screen, ui, rows - 6)
        self._draw_verdict(screen, rows - 5, columns)
        if self.show_rhythm:
            self._draw_pulse(screen, rows - 4, columns, now)
        else:
            cockpit.put(screen, rows - 4, 1, self._failure_detail(), columns - 2,
                        self.style(INK))
        cockpit.put(screen, rows - 3, 1, self.status or self.earned_hint or self.advice,
                    columns - 2, self.style(WARN if self.status or self.earned_hint else MUTED))
        self._draw_score(screen, rows - 2, columns, now)
        self._draw_status(screen, rows - 1, columns)
        return screen

    def _objective_lines(self, width: int) -> list[tuple[str, tuple]]:
        """Use the authored brief; never expose hidden test inputs as examples."""
        lines = cockpit.section("OBJECTIVE / " + self.level.title, self.level.brief, width)
        lines += cockpit.section("FUNCTION", self.level.func_name + "()", width)
        lines += cockpit.section("CONCEPTS", ", ".join(self.level.tags), width)
        lines += cockpit.section("SOLVE TIME", f"Par {self.level.par_seconds:.0f}s. Speed measures your solve time.", width)
        if self.earned_hint:
            lines += cockpit.section("EARNED HINT", self.earned_hint, width)
        if self.outcome is not None:
            lines += cockpit.section("LAST RUN", self._failure_detail(), width)
        lines += cockpit.section("NEXT ACTION", self.advice, width)
        return lines

    def _help_lines(self, width: int) -> list[tuple[str, tuple]]:
        text = ("ctrl-r  Run tests\nctrl-o  Objective / return to code\n"
                "ctrl-p  Show or hide typing rhythm\nctrl-g  Help / return to code\n"
                "ctrl-x  Quit\nctrl-z / ctrl-y  Undo / redo\n"
                "ctrl-k  Kill line\nctrl-a / ctrl-e  Start / end of line\n"
                "ctrl-l  Redraw\nPgUp / PgDn  Scroll this view\n"
                "Escape  Return to code")
        return cockpit.section("KEYBOARD", text, width)

    def _draw_verdict(self, screen: Screen, row: int, columns: int) -> None:
        if self.busy:
            text, tone = "RUNNING  /  testing your code", WARN
        elif self.outcome is None:
            text, tone = "READY  /  " + self.level.title, ACCENT
        elif self.outcome.result.fatal:
            text, tone = "RUN STOPPED  /  " + self.outcome.result.error_type, BAD
        else:
            result = self.outcome.result
            label = "ALL TESTS PASSED" if result.all_passed else "TESTS NEED ATTENTION"
            text = f"{label}  /  {result.passed_count}/{result.total_count} passed"
            if self.outcome.banked:
                text += "  /  banked"
            tone = GOOD if result.all_passed else WARN
        cockpit.put(screen, row, 1, text, columns - 2, self.style(tone, bold=True))

    def _failure_detail(self) -> str:
        if self.outcome is None:
            return "ctrl-o objective   ctrl-g help   ctrl-p rhythm"
        result = self.outcome.result
        if result.fatal:
            return self.outcome.message or result.error
        failed = next((case for case in result.outcomes if not case.passed), None)
        if failed:
            detail = failed.error or f"expected {failed.expected} | got {failed.got}"
            return f"FAIL {failed.name}: {detail}"
        delta = "" if self.score_delta is None else f"  /  {self.score_delta:+.1f} vs previous run"
        return f"{result.ops:,} operations  /  {result.peak_bytes / 1024:.1f} KiB peak" + delta

    def _draw_too_small(self, screen: Screen, rows: int, columns: int) -> None:
        """Exit criterion 9: say so, rather than draw a corrupted frame."""
        message = f"{columns}x{rows} too small"
        needed = f"need {MIN_WIDTH}x{MIN_HEIGHT}"
        screen.put(max(0, rows // 2 - 1), 0, message[:columns], self.style(BAD))
        if rows > 1:
            screen.put(rows // 2, 0, needed[:columns], self.style(MUTED))

    def _draw_title(self, screen: Screen, columns: int) -> None:
        title = f"{self.level.id} / {self.level.title}"
        meta = f"variant {self.seed} / attempt {self.attempt}"
        cockpit.header(screen, Renderer(self._caps), title, meta)

    def _gutter_width(self) -> int:
        return max(GUTTER_MIN, len(str(len(self.buffer))) + 2)

    def _draw_code(self, screen: Screen, top: int, bottom: int,
                   columns: int) -> None:
        height = bottom - top
        cursor_column = text_width(self.buffer.line[:self.buffer.column])
        available = max(1, columns - self._gutter_width() - 1)
        self.horizontal_scroll = min(self.horizontal_scroll, cursor_column)
        self.horizontal_scroll = max(self.horizontal_scroll, cursor_column - available)
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
            source_column = 0
            for span in coloured[offset]:
                span_width = text_width(span.text)
                start = max(0, self.horizontal_scroll - source_column)
                target = gutter + max(0, source_column - self.horizontal_scroll)
                if target >= columns:
                    break
                visible = cockpit.viewport(span.text, start, columns - target)
                cockpit.put(screen, row, target, visible, columns - target, self.style(span.rgb))
                source_column += span_width

            if current:
                self._draw_cursor(screen, row, gutter, columns)

    def _draw_cursor(self, screen: Screen, row: int, gutter: int,
                     columns: int) -> None:
        """A block cursor drawn into the frame, since the real one is hidden."""
        column = gutter + text_width(self.buffer.line[:self.buffer.column]) - self.horizontal_scroll
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
        """The rhythm row: a moving trail, or a static summary (criterion 8).

        The trail is a function of ``now`` -- it scrolls, dims and drains while
        the player sits still, which is the whole point of it and is also the
        thing a terminal that cannot animate must not be sent. So when
        `animate` is false this degrades to a reading taken at the last
        keystroke, and two frames composed a minute apart with nothing typed
        between them come out identical. `Frame.diff` then emits nothing at
        all, so an unattended editor puts no bytes on the wire.
        """
        if not self._caps.animate:
            self._draw_pulse_summary(screen, row, columns)
            return
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

    def _draw_pulse_summary(self, screen: Screen, row: int,
                            columns: int) -> None:
        """The same information, none of the motion.

        Deliberately carries `total` where the animated row carries state:
        "how much have I typed" is the part of the rhythm that survives not
        being able to watch it happen, and a state that reads `thinking`
        forever because the clock is not consulted would be a lie rather than
        a summary.
        """
        reading = self.pulse.summary()
        screen.put(row, 1, self.glyph("spark"),
                   self.style(GOLD if reading.total else FAINT))
        text = (
            f"  {reading.wpm:>3.0f} wpm"
            f"   {reading.evenness:>3.0%} even"
            f"   {reading.total} keys"
        )
        if 3 + len(text) < columns:
            screen.put(row, 3, text,
                       self.style(INK if reading.total else MUTED))

    def _trail_colour(self, value: float, energy: float) -> RGB:
        if value > 0.75:
            return GOLD if energy > 0.3 else WARN
        if value > 0.35:
            return WARN if energy > 0.2 else MUTED
        return MUTED

    def _draw_score(self, screen: Screen, row: int, columns: int,
                    now: float) -> None:
        if self.busy:
            self._draw_live(screen, row, columns)
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

        score = outcome.score
        labels = ("Accuracy", "Solve time", "Efficiency") if columns >= 76 else ("Acc", "Time", "Eff")
        values = (score.accuracy, score.speed, score.functional)
        column = 1
        for label, value in zip(labels, values):
            text = f"{label} {value * progress:.0f}  "
            column = cockpit.put(screen, row, column, text, columns - column - 1,
                                 self.style(INK))
        tail = f"TOTAL {score.total * progress:.1f} {self.glyph('star_full') * score.stars}"
        if column + len(tail) < columns:
            cockpit.put(screen, row, columns - len(tail) - 1, tail, len(tail),
                        self.style(GOLD, bold=True))

    def _draw_live(self, screen: Screen, row: int, columns: int) -> None:
        """A run in flight: ticks landing, and Accuracy filling as they do."""
        live = self.live
        if live is None or live.total == 0:
            screen.put(row, 1, "running", self.style(WARN, bold=True))
            return

        column = screen.put(row, 1, "run ", self.style(MUTED))
        for index in range(live.total):
            if index < len(live.marks):
                glyph = self.glyph("tick") if live.marks[index] else self.glyph("cross")
                colour = GOOD if live.marks[index] else BAD
            else:
                glyph = self.glyph("bar_empty")
                colour = FAINT
            if column >= columns - 1:
                break
            column = screen.put(row, column, glyph, self.style(colour))
        column = screen.put(row, column, "  ", "")

        column = self._draw_axis(
            screen, row, column, "acc", live.accuracy, GOOD, columns
        )
        tail = f"{live.done}/{live.total}"
        if column + len(tail) + 1 < columns:
            screen.put(row, columns - len(tail) - 1, tail, self.style(MUTED))

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
        # Controls stay visible even when a warning or a hint is present.
        keys = "ctrl-r run  ctrl-o objective  ctrl-g help  ctrl-x quit"
        if columns < 60:
            keys = "^R run  ^O brief  ^G help  ^X quit"
        cockpit.put(screen, row, 1, keys, columns - 2, self.style(ACCENT))

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
        command = binding(key)
        if command in ("ctrl-o", "ctrl-g", "ctrl-p"):
            if command == "ctrl-p":
                self.show_rhythm = not self.show_rhythm
            elif command == "ctrl-o":
                self.objective_open = not self.objective_open
                self.help_open = False
            else:
                self.help_open = not self.help_open
                self.objective_open = False
            self.panel_scroll = 0
            return
        if self.objective_open or self.help_open:
            if command == "escape":
                self.objective_open = self.help_open = False
            elif command in ("down", "pgdn"):
                self.panel_scroll += 1 if command == "down" else 8
            elif command in ("up", "pgup"):
                self.panel_scroll = max(0, self.panel_scroll - (1 if command == "up" else 8))
            elif command in ("ctrl-x", "ctrl-c"):
                self.running = False
            elif command == "ctrl-r":
                self.objective_open = self.help_open = False
                self.execute()
            return
        self.status = ""

        if key.name == "paste":
            self.buffer.insert(key.text)
            return
        if key.printable:
            self.pulse.press(now)
            self.buffer.insert(key.char)
            return

        action = KEYMAP.get(binding(key))
        if action is None:
            return
        self.pulse.press(now)
        action(self)

    # -- running -----------------------------------------------------------

    def execute(self) -> None:
        """Run the buffer against the level's tests and score the attempt."""
        self.busy = True
        self.status = ""
        started = self.started
        self.attempt += 1
        self.live = LiveRun(total=len(self.tests))
        # The buffer is whatever the player typed, on their own machine.
        result = run_submission(
            self.level, self.buffer.text, self.tests, source=Source.PLAYER,
            on_progress=self._on_test,
        )
        if self.attempt == 1:
            self.first_run_clean = not result.fatal
        elapsed = time.monotonic() - started

        if result.fatal:
            self.advice = "Fix the error above, then run again. ctrl-o shows full details."
            self.outcome = RunOutcome(
                result, None, time.monotonic(), elapsed,
                message=f"{result.error_type}: {result.error}",
            )
            self.busy = False
            self.live = None
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
        self.score_delta = None if self.previous_total is None else score.total - self.previous_total
        self.previous_total = score.total
        advice = tips.generate(self.buffer.text, self.level.func_name, result,
                               ref_ops=ref_ops, vibe=self.session.vibe if self.session else None,
                               style_results=style_results)
        self.advice = advice[0] if advice else "All clear. Refine your solution or choose another level."
        passed = f"{result.passed_count}/{result.total_count} tests"
        self.outcome = RunOutcome(
            result, score, time.monotonic(), elapsed, message=passed
        )
        self.busy = False
        self.live = None

        if result.all_passed:
            self._bank(score)
        else:
            # Only the newest hint: the status line is one row, and a player
            # who wants the whole ladder has it in `vibecoder play`. Earning
            # one is silent until the second failed run -- see Level.hints.
            earned = self.level.hints_after(self.attempt)
            if earned:
                self.earned_hint = earned[-1]
                self.status = f"{self.glyph('hint')} {earned[-1]}"

    def _on_test(self, index: int, total: int, name: str, passed: bool) -> None:
        """One test reported. Redraw so the player sees it land.

        The run loop is blocked inside `execute` while this happens, so the
        frame has to be pushed from here rather than waited for.
        """
        if self.live is None:
            return
        self.live.total = total
        self.live.done = index + 1
        self.live.passed += 1 if passed else 0
        self.live.marks.append(passed)
        self.redraw()

    def redraw(self) -> None:
        """Compose and emit one frame immediately, outside the main loop."""
        if self.term is None:
            return
        frame = self.compose(*self.term.size())
        output, emitted, changed = frame.diff(self._previous)
        self.term.write(output)
        self._previous = frame
        if changed:
            self._damage.append((emitted, changed))

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

        with steady_heap():
            return self._loop(term)

    def _loop(self, term: TerminalSession) -> int:
        """The loop body, split out so `steady_heap` wraps the whole of it."""
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
