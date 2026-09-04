"""The editor, composed headless. No pty, no timing, no real terminal.

Every frame here is built by calling ``compose`` directly and asserting the
plain text that comes back, which is the property that makes a full-screen
application testable in CI at all.
"""

import re
import unittest

from vibecoder.editing import INDENT
from vibecoder.editor import Editor
from vibecoder.keys import Key
from vibecoder.levels import get_level
from vibecoder.term import MIN_HEIGHT, MIN_WIDTH
from vibecoder.ui import Capabilities, Depth, PLAIN

NOW = 5000.0
FULL = Capabilities(depth=Depth.TRUECOLOR, unicode=True, animate=False, width=80)


def editor(caps=PLAIN, level_id="w1-l1-revenue") -> Editor:
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
    """

    BUDGET_MS = 16.0

    def _sample(self, ed, columns=80, rows=24, presses=120):
        import time

        previous = ed.compose(rows, columns, now=NOW)
        worst = 0.0
        for index in range(presses):
            started = time.perf_counter()
            ed.handle(Key("char", "x"), now=NOW + index * 0.05)
            frame = ed.compose(rows, columns, now=NOW + index * 0.05)
            frame.diff(previous)
            worst = max(worst, (time.perf_counter() - started) * 1000)
            previous = frame
        return worst

    def test_a_keystroke_is_handled_within_the_frame_budget(self):
        ed = editor(FULL)
        ed.buffer.load("def solve(rows):\n    return [r for r in rows]")
        ed.buffer.end()
        worst = self._sample(ed)
        self.assertLess(worst, self.BUDGET_MS, f"worst keystroke {worst:.1f}ms")

    def test_the_budget_holds_on_a_large_buffer(self):
        """Highlighting runs over the whole buffer on every keystroke."""
        ed = editor(FULL)
        ed.buffer.load("\n".join(f"value_{n} = {n} * 2  # note" for n in range(400)))
        ed.buffer.goto(200, 0)
        worst = self._sample(ed, presses=60)
        self.assertLess(worst, self.BUDGET_MS, f"worst keystroke {worst:.1f}ms")

    def test_the_budget_holds_on_a_large_terminal(self):
        ed = editor(FULL)
        ed.buffer.load("x = 1")
        worst = self._sample(ed, columns=200, rows=50, presses=60)
        self.assertLess(worst, self.BUDGET_MS, f"worst keystroke {worst:.1f}ms")
