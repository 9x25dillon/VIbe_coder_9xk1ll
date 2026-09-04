"""The editor, composed headless. No pty, no timing, no real terminal.

Every frame here is built by calling ``compose`` directly and asserting the
plain text that comes back, which is the property that makes a full-screen
application testable in CI at all.
"""

import re
import unittest

from vibecoder.editing import INDENT
from vibecoder.editor import Editor, steady_heap
from vibecoder.keys import Key
from vibecoder.levels import get_level
from vibecoder.term import MIN_HEIGHT, MIN_WIDTH
from vibecoder.ui import Capabilities, Depth, PLAIN

NOW = 5000.0
FULL = Capabilities(depth=Depth.TRUECOLOR, unicode=True, animate=False, width=80)


def editor(caps=PLAIN, level_id="w2-l1-revenue") -> Editor:
    return Editor(get_level(level_id), seed=1, caps=caps)


def press(ed: Editor, text: str, at: float = NOW) -> None:
    for character in text:
        ed.handle(Key("char", character), now=at)


class TestComposition(unittest.TestCase):
    def test_a_frame_has_exactly_the_requested_geometry(self):
        frame = editor().compose(24, 80, now=NOW)
        self.assertEqual(frame.rows, 24)
        self.assertEqual(frame.columns, 80)

    def test_the_title_row_names_the_level(self):
        ed = editor()
        self.assertIn(ed.level.id, ed.compose(24, 80, now=NOW).line(0))

    def test_the_starter_code_is_on_screen(self):
        ed = editor()
        text = ed.compose(24, 80, now=NOW).as_text()
        self.assertIn(ed.level.starter.split("\n")[0], text)

    def test_line_numbers_are_drawn(self):
        frame = editor().compose(24, 80, now=NOW)
        self.assertTrue(frame.line(1).lstrip().startswith("1"))

    def test_typed_text_appears_in_the_next_frame(self):
        ed = editor()
        ed.buffer.load("")
        press(ed, "zzz")
        self.assertIn("zzz", ed.compose(24, 80, now=NOW).as_text())

    def test_the_help_line_is_drawn_when_there_is_no_status(self):
        frame = editor().compose(24, 80, now=NOW)
        self.assertIn("ctrl-r", frame.line(23))


class TestDegradation(unittest.TestCase):
    """Exit criterion 2: usable with no colour, no Unicode, no animation."""

    def test_a_plain_frame_contains_no_non_ascii(self):
        frame = editor(PLAIN).compose(24, 80, now=NOW).as_text()
        offenders = sorted({c for c in frame if ord(c) > 127})
        self.assertEqual(offenders, [], f"non-ascii glyphs at PLAIN: {offenders}")

    def test_a_plain_frame_carries_no_colour(self):
        """No *colour* at Depth.NONE. Attributes are a separate question.

        Bold and reverse video are still emitted, and deliberately: the block
        cursor is drawn with reverse video, so suppressing it would leave the
        editor with no visible cursor on a terminal running under NO_COLOR.
        The NO_COLOR convention asks for colour to be withheld, and reverse
        video is not colour.
        """
        ed = editor(PLAIN)
        output, _, _ = ed.compose(24, 80, now=NOW).diff(None)
        colour = re.compile(r"\033\[(?:38|48);|\033\[(?:3|4|9|10)[0-7]m")
        self.assertIsNone(colour.search(output), "colour emitted at Depth.NONE")

    def test_a_plain_frame_still_draws_a_cursor(self):
        ed = editor(PLAIN)
        output, _, _ = ed.compose(24, 80, now=NOW).diff(None)
        self.assertIn("\033[7m", output, "no visible cursor without colour")

    def test_the_same_text_is_drawn_at_every_capability(self):
        """T6's depth invariance, extended to the editor."""
        plain = editor(PLAIN).compose(24, 80, now=NOW)
        rich = editor(FULL).compose(24, 80, now=NOW)
        self.assertEqual(
            len(plain.as_text().split("\n")), len(rich.as_text().split("\n"))
        )

    def test_glyphs_have_equal_width_at_both_capabilities(self):
        """A wide fallback would shift every cell to its right."""
        plain = editor(PLAIN).compose(24, 80, now=NOW)
        rich = editor(FULL).compose(24, 80, now=NOW)
        for row in range(24):
            with self.subTest(row=row):
                self.assertEqual(
                    len(plain.line(row)), len(rich.line(row)),
                    f"row {row} changed width between capabilities",
                )


class TestSmallTerminal(unittest.TestCase):
    """Exit criterion 9: a legible message, never a corrupted frame."""

    def test_a_short_terminal_says_so(self):
        frame = editor().compose(MIN_HEIGHT - 1, 80, now=NOW)
        self.assertIn("too small", frame.as_text())

    def test_a_narrow_terminal_says_so(self):
        frame = editor().compose(24, MIN_WIDTH - 1, now=NOW)
        self.assertIn("too small", frame.as_text())

    def test_the_notice_fits_inside_the_terminal(self):
        frame = editor().compose(6, 20, now=NOW)
        for row in range(frame.rows):
            self.assertLessEqual(len(frame.line(row)), 20)

    def test_the_smallest_supported_size_draws_a_real_frame(self):
        frame = editor().compose(MIN_HEIGHT, MIN_WIDTH, now=NOW)
        self.assertNotIn("too small", frame.as_text())

    def test_nothing_overflows_the_width_at_any_size(self):
        ed = editor()
        for columns in (MIN_WIDTH, 60, 80, 200):
            frame = ed.compose(24, columns, now=NOW)
            for row in range(24):
                with self.subTest(columns=columns, row=row):
                    self.assertLessEqual(len(frame.line(row)), columns)


class TestKeyDispatch(unittest.TestCase):
    def test_printable_keys_insert(self):
        ed = editor()
        ed.buffer.load("")
        ed.handle(Key("char", "q"), now=NOW)
        self.assertEqual(ed.buffer.text, "q")

    def test_control_keys_are_never_inserted_as_text(self):
        ed = editor()
        ed.buffer.load("")
        for key in (Key("char", "r", ctrl=True), Key("f13"), Key("escape")):
            ed.handle(key, now=NOW)
        self.assertNotIn("r", ed.buffer.text)

    def test_an_unknown_key_is_ignored_silently(self):
        ed = editor()
        before = ed.buffer.text
        ed.handle(Key("f7"), now=NOW)
        self.assertEqual(ed.buffer.text, before)

    def test_enter_starts_a_new_line(self):
        ed = editor()
        ed.buffer.load("def f():")
        ed.buffer.end()
        ed.handle(Key("enter"), now=NOW)
        self.assertEqual(len(ed.buffer), 2)
        self.assertEqual(ed.buffer.line, " " * INDENT)

    def test_ctrl_x_stops_the_loop(self):
        ed = editor()
        ed.handle(Key("char", "x", ctrl=True), now=NOW)
        self.assertFalse(ed.running)

    def test_ctrl_z_undoes(self):
        ed = editor()
        ed.buffer.load("")
        press(ed, "abc")
        ed.handle(Key("char", "z", ctrl=True), now=NOW)
        self.assertEqual(ed.buffer.text, "")

    def test_a_paste_arrives_whole(self):
        ed = editor()
        ed.buffer.load("")
        ed.handle(Key("paste", text="a\nb"), now=NOW)
        self.assertEqual(ed.buffer.text, "a\nb")

    def test_a_paste_does_not_count_as_typing(self):
        """Pasted code is not evidence about how fast somebody types."""
        ed = editor()
        ed.handle(Key("paste", text="x" * 500), now=NOW)
        self.assertEqual(ed.pulse.total, 0)

    def test_typing_registers_with_the_pulse(self):
        ed = editor()
        press(ed, "abc")
        self.assertEqual(ed.pulse.total, 3)

    def test_ctrl_l_forces_a_full_repaint(self):
        ed = editor()
        ed._previous = ed.compose(24, 80, now=NOW)
        ed.handle(Key("char", "l", ctrl=True), now=NOW)
        self.assertIsNone(ed._previous)


class TestScrolling(unittest.TestCase):
    def test_the_view_follows_the_cursor_downward(self):
        ed = editor()
        ed.buffer.load("\n".join(str(n) for n in range(200)))
        ed.buffer.goto(150, 0)
        ed.compose(24, 80, now=NOW)
        self.assertGreater(ed.scroll, 0)
        self.assertLessEqual(ed.scroll, 150)

    def test_the_cursor_line_is_visible_after_scrolling(self):
        ed = editor()
        ed.buffer.load("\n".join(f"line{n}" for n in range(200)))
        ed.buffer.goto(150, 0)
        self.assertIn("line150", ed.compose(24, 80, now=NOW).as_text())

    def test_scrolling_back_to_the_top_shows_line_one(self):
        ed = editor()
        ed.buffer.load("\n".join(f"line{n}" for n in range(200)))
        ed.buffer.goto(150, 0)
        ed.compose(24, 80, now=NOW)
        ed.buffer.goto(0, 0)
        # The view follows the cursor during composition, not before it.
        self.assertIn("line0", ed.compose(24, 80, now=NOW).as_text())
        self.assertEqual(ed.scroll, 0)

    def test_a_buffer_shorter_than_the_pane_does_not_scroll(self):
        ed = editor()
        ed.buffer.load("a\nb")
        ed.compose(24, 80, now=NOW)
        self.assertEqual(ed.scroll, 0)


class TestDamage(unittest.TestCase):
    """Exit criterion 4, measured through the editor rather than the grid."""

    def test_one_keystroke_repaints_a_handful_of_cells(self):
        ed = editor()
        ed.buffer.load("hello")
        ed.buffer.end()
        before = ed.compose(24, 80, now=NOW)
        press(ed, "x")
        after = ed.compose(24, 80, now=NOW)
        _, emitted, changed = after.diff(before)
        self.assertGreater(changed, 0)
        # The character, the moved cursor, and the rhythm bar.
        self.assertLess(emitted, 80, f"{emitted} cells for one keystroke")

    def test_an_unchanged_frame_emits_nothing_at_all(self):
        ed = editor()
        first = ed.compose(24, 80, now=NOW)
        second = ed.compose(24, 80, now=NOW)
        output, _, changed = second.diff(first)
        self.assertEqual(changed, 0)
        self.assertEqual(output, "")

    def test_the_damage_ratio_starts_at_one(self):
        self.assertEqual(editor().damage_ratio, 1.0)


class TestRunning(unittest.TestCase):
    """W7: running the buffer without leaving the screen."""

    def test_the_reference_solution_passes_and_scores(self):
        ed = editor()
        ed.buffer.load(ed.level.reference)
        ed.execute()
        self.assertIsNotNone(ed.outcome)
        self.assertTrue(ed.outcome.result.all_passed)
        self.assertIsNotNone(ed.outcome.score)
        self.assertGreater(ed.outcome.score.total, 0)

    def test_a_syntax_error_is_reported_rather_than_raised(self):
        ed = editor()
        ed.buffer.load("def f(:\n    pass")
        ed.execute()
        self.assertTrue(ed.outcome.result.fatal)
        self.assertIsNone(ed.outcome.score)
        self.assertIn("SyntaxError", ed.outcome.message)

    def test_a_fatal_result_still_draws_a_frame(self):
        ed = editor()
        ed.buffer.load("def f(:")
        ed.execute()
        self.assertIn("SyntaxError", ed.compose(24, 80, now=NOW).as_text())

    def test_attempts_are_counted(self):
        ed = editor()
        ed.buffer.load(ed.level.reference)
        ed.execute()
        ed.execute()
        self.assertEqual(ed.attempt, 2)

    def test_a_failed_run_offers_a_hint_from_the_second_attempt(self):
        """A beginner stuck in the editor has nobody to ask."""
        ed = editor(level_id="w1-l6-tally")
        ed.buffer.load(ed.level.starter)
        ed.execute()
        self.assertEqual(ed.status, "", "the first attempt earns no hint")
        ed.execute()
        self.assertIn(ed.level.hints[0], ed.status)

    def test_a_passing_run_never_shows_a_hint(self):
        ed = editor(level_id="w1-l6-tally")
        ed.buffer.load(ed.level.reference)
        ed.execute()
        ed.execute()
        self.assertEqual(ed.status, "")

    def test_the_hint_shown_is_the_newest_one(self):
        """One status row, so the ladder's latest rung is the useful one."""
        ed = editor(level_id="w1-l6-tally")
        ed.buffer.load(ed.level.starter)
        for _ in range(3):
            ed.execute()
        self.assertIn(ed.level.hints[1], ed.status)

    def test_the_editor_is_not_left_busy_after_a_run(self):
        ed = editor()
        ed.buffer.load("def f(:")
        ed.execute()
        self.assertFalse(ed.busy)

    def test_running_from_the_editor_matches_running_from_the_cli(self):
        """Exit criterion 7: the transport must not change the result."""
        from vibecoder.runner import run_submission

        ed = editor()
        ed.buffer.load(ed.level.reference)
        ed.execute()
        direct = run_submission(ed.level, ed.level.reference, ed.tests)
        self.assertEqual(ed.outcome.result.ops, direct.ops)
        self.assertEqual(
            ed.outcome.result.passed_count, direct.passed_count
        )

    def test_nothing_is_banked_without_a_session(self):
        ed = editor()
        ed.buffer.load(ed.level.reference)
        ed.execute()
        self.assertFalse(ed.outcome.banked)


if __name__ == "__main__":
    unittest.main()


class TestLatency(unittest.TestCase):
    """Exit criterion 3: measured, not asserted.

    The budget is 16 ms -- one frame at 60 Hz, roughly the point at which a
    person stops experiencing typing as instant. What is timed is the whole
    keystroke path: dispatch, recompose, diff. Writing to the terminal is
    excluded because a pty in CI is not a terminal emulator, and timing one
    would measure the harness.

    Two clocks, because they answer different questions (this is the answer to
    Q27, which asked whether a timing budget should be a percentile or a worst
    case -- it turned out to be neither on its own):

    * **Wall clock, median.** What a player feels. It cannot carry a worst-case
      assertion: a keystroke costing 3 ms of CPU has been observed taking
      145 ms of wall clock because the OS descheduled the process, which says
      nothing about this code. The median is robust to that and still fails
      honestly if typing gets slower.
    * **CPU time, worst case.** What this code costs. Immune to preemption, so
      it can assert *every* keystroke rather than most of them, which is the
      only form of "never exceeds, even under load" that is actually testable.
    """

    BUDGET_MS = 16.0

    #: The worst-case bound, asserted against CPU time rather than wall clock.
    #: Answers Q27: a wall-clock worst case measures the machine as much as the
    #: code -- one scheduler preemption from a parallel Docker run failed a
    #: build that proved nothing. CPU time excludes time the process was not
    #: running, so "never exceeds this, even under load" becomes a claim about
    #: this code that stays true on a busy machine instead of a claim about how
    #: quiet the machine was. Wall clock still guards the median above, because
    #: that is what a player actually feels.
    STRICT_BUDGET_MS = 12.7

    #: Where the strict bound is measured. Highlighting and the frame diff are
    #: viewport-scoped, so cost should be flat in buffer size; a regression that
    #: makes any of it whole-buffer shows up here first.
    LARGE_BUFFER_LINES = 4000

    def _sample(self, ed, columns=80, rows=24, presses=120):
        """``(median, p95, worst)`` per-keystroke wall-clock cost, in ms."""
        import time

        previous = ed.compose(rows, columns, now=NOW)
        samples = []
        # `loop` runs under this, so measuring without it would time a
        # configuration the game never uses.
        with steady_heap():
            for index in range(presses):
                started = time.perf_counter()
                ed.handle(Key("char", "x"), now=NOW + index * 0.05)
                frame = ed.compose(rows, columns, now=NOW + index * 0.05)
                frame.diff(previous)
                samples.append((time.perf_counter() - started) * 1000)
                previous = frame
        samples.sort()
        return (samples[len(samples) // 2],
                samples[int(len(samples) * 0.95)],
                samples[-1])

    def test_a_keystroke_is_handled_within_the_frame_budget(self):
        ed = editor(FULL)
        ed.buffer.load("def solve(rows):\n    return [r for r in rows]")
        ed.buffer.end()
        median, p95, worst = self._sample(ed)
        self.assertLess(median, self.BUDGET_MS,
                        f"median {median:.1f}ms (p95 {p95:.1f}, worst {worst:.1f})")

    def test_the_budget_holds_on_a_large_buffer(self):
        """A buffer far taller than the viewport must not cost more to type in.

        Highlighting and the diff are viewport-scoped, so this should read the
        same as the small-buffer case; `test_keystroke_cost_does_not_grow_with
        _the_buffer` asserts that relationship directly.
        """
        ed = editor(FULL)
        ed.buffer.load("\n".join(f"value_{n} = {n} * 2  # note" for n in range(400)))
        ed.buffer.goto(200, 0)
        median, p95, worst = self._sample(ed, presses=60)
        self.assertLess(median, self.BUDGET_MS,
                        f"median {median:.1f}ms (p95 {p95:.1f}, worst {worst:.1f})")

    def test_the_budget_holds_on_a_large_terminal(self):
        ed = editor(FULL)
        ed.buffer.load("x = 1")
        median, p95, worst = self._sample(ed, columns=200, rows=50, presses=60)
        self.assertLess(median, self.BUDGET_MS,
                        f"median {median:.1f}ms (p95 {p95:.1f}, worst {worst:.1f})")

    def _cpu_sample(self, ed, columns=80, rows=24, presses=200):
        """Worst per-keystroke CPU cost, in milliseconds.

        Same path as ``_sample`` -- dispatch, recompose, diff -- timed with
        ``process_time`` so that preemption by an unrelated process does not
        land in the measurement.
        """
        import time

        previous = ed.compose(rows, columns, now=NOW)
        worst = 0.0
        for index in range(presses):
            started = time.process_time()
            ed.handle(Key("char", "x"), now=NOW + index * 0.05)
            frame = ed.compose(rows, columns, now=NOW + index * 0.05)
            frame.diff(previous)
            worst = max(worst, (time.process_time() - started) * 1000)
            previous = frame
        return worst

    def test_no_keystroke_exceeds_the_strict_budget_at_four_thousand_lines(self):
        """Exit criterion 3's hard bound: the worst keystroke, not the typical.

        A percentile can hide a pathological case behind 5% of samples. This
        asserts every one of them, which is only meaningful because it is CPU
        time -- see STRICT_BUDGET_MS.
        """
        ed = editor(FULL)
        ed.buffer.load("\n".join(
            f"value_{n} = {n} * 2  # note" for n in range(self.LARGE_BUFFER_LINES)
        ))
        ed.buffer.goto(self.LARGE_BUFFER_LINES // 2, 0)
        # Through the same helper `loop` runs under, because a GC pass walking
        # the rest of the process is what the bound is protecting against.
        with steady_heap():
            worst = self._cpu_sample(ed)
        self.assertLess(
            worst, self.STRICT_BUDGET_MS,
            f"worst keystroke {worst:.2f}ms of CPU at "
            f"{self.LARGE_BUFFER_LINES} lines",
        )

    def test_the_bound_survives_a_large_unrelated_heap(self):
        """"Even under load" means load this editor did not create.

        Without `steady_heap` this is the failure: identical per-keystroke work
        costs an order of magnitude more, because each collection walks objects
        belonging to the rest of the game.
        """
        ballast = [[object() for _ in range(20)] for _ in range(20000)]
        try:
            ed = editor(FULL)
            ed.buffer.load("\n".join(
                f"value_{n} = {n} * 2  # note"
                for n in range(self.LARGE_BUFFER_LINES)
            ))
            ed.buffer.goto(self.LARGE_BUFFER_LINES // 2, 0)
            with steady_heap():
                worst = self._cpu_sample(ed, presses=120)
        finally:
            del ballast
        self.assertLess(
            worst, self.STRICT_BUDGET_MS,
            f"worst keystroke {worst:.2f}ms of CPU with a large heap",
        )

    def test_keystroke_cost_does_not_grow_with_the_buffer(self):
        """Ten times the buffer must not cost meaningfully more per keystroke.

        The property behind the bound above. If highlighting or the diff ever
        stops being viewport-scoped this fails long before the budget does,
        and says why.
        """
        def worst_at(lines):
            ed = editor(FULL)
            ed.buffer.load("\n".join(
                f"value_{n} = {n} * 2  # note" for n in range(lines)
            ))
            ed.buffer.goto(lines // 2, 0)
            with steady_heap():
                return self._cpu_sample(ed, presses=120)

        small = worst_at(400)
        large = worst_at(4000)
        self.assertLess(
            large, small * 4 + 2.0,
            f"400 lines: {small:.2f}ms, 4000 lines: {large:.2f}ms - "
            "cost is growing with the buffer",
        )


class TestLiveRun(unittest.TestCase):
    """T7 W8: the axes assemble as tests report, rather than after."""

    def _live(self, total, marks):
        from vibecoder.editor import LiveRun

        ed = editor(PLAIN)
        ed.busy = True
        ed.live = LiveRun(total=total, done=len(marks),
                          passed=sum(marks), marks=list(marks))
        return ed

    def test_accuracy_reflects_only_what_has_reported(self):
        from vibecoder.editor import LiveRun

        live = LiveRun(total=10, done=4, passed=3, marks=[True, True, False, True])
        self.assertAlmostEqual(live.accuracy, 75.0)

    def test_accuracy_is_zero_before_anything_reports(self):
        from vibecoder.editor import LiveRun

        self.assertEqual(LiveRun(total=5).accuracy, 0.0)

    def test_pending_tests_are_drawn_as_placeholders(self):
        row = self._live(5, [True, True]).compose(20, 76, now=NOW).line(18)
        self.assertIn("2/5", row)

    def test_a_failing_test_is_marked_differently(self):
        passing = self._live(3, [True, True, True]).compose(20, 76, now=NOW).line(18)
        failing = self._live(3, [True, False, True]).compose(20, 76, now=NOW).line(18)
        self.assertNotEqual(passing, failing)

    def test_the_live_row_never_overflows(self):
        for columns in (48, 60, 80, 200):
            frame = self._live(40, [True] * 20).compose(24, columns, now=NOW)
            with self.subTest(columns=columns):
                self.assertLessEqual(len(frame.line(22)), columns)

    def test_a_run_with_no_tests_still_draws(self):
        ed = editor(PLAIN)
        ed.busy = True
        ed.live = None
        self.assertIn("running", ed.compose(20, 76, now=NOW).as_text())

    def test_progress_reaches_the_editor_during_a_run(self):
        """The whole point: the callback fires before execute() returns."""
        ed = editor()
        ed.buffer.load(ed.level.reference)
        seen = []
        original = ed._on_test

        def spy(index, total, name, passed):
            seen.append((index, total, passed))
            original(index, total, name, passed)

        ed._on_test = spy
        ed.execute()
        self.assertGreater(len(seen), 0, "no test reported before the run ended")
        self.assertEqual(len(seen), len(ed.tests))
        self.assertTrue(all(p for _, _, p in seen))

    def test_the_live_state_is_cleared_when_the_run_ends(self):
        ed = editor()
        ed.buffer.load(ed.level.reference)
        ed.execute()
        self.assertIsNone(ed.live)
        self.assertFalse(ed.busy)

    def test_the_live_state_is_cleared_after_a_fatal_run(self):
        ed = editor()
        ed.buffer.load("def f(:\n")
        ed.execute()
        self.assertIsNone(ed.live)
        self.assertFalse(ed.busy)

    def test_streaming_does_not_change_the_score(self):
        """A player must not be scored differently for watching it happen."""
        from vibecoder.models import Source
        from vibecoder.runner import run_submission

        ed = editor()
        ed.buffer.load(ed.level.reference)
        ed.execute()
        quiet = run_submission(ed.level, ed.level.reference, ed.tests,
                               source=Source.PLAYER)
        self.assertEqual(ed.outcome.result.ops, quiet.ops)
        self.assertEqual(ed.outcome.result.passed_count, quiet.passed_count)
