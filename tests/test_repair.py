"""Typing the fix into a paused fight (T3, Q67).

Composed headless, exactly as `test_editor` composes the editor: every frame
here is built by calling ``compose`` directly and asserting the plain text that
comes back. That is what makes a full-screen application testable in CI, and it
is why the pane keeps composition pure.

No pty, no child process, no terminal. The engine these frames drive is tested
in `test_stepping`; what is under test here is the pane a player types into.
"""

import unittest

from vibecoder.keymap import KEYMAP, REPAIR_HELP, binding, describe_keys
from vibecoder.keys import Key
from vibecoder.repair import Repair
from vibecoder.term import MIN_HEIGHT, MIN_WIDTH
from vibecoder.ui import Capabilities, Depth, PLAIN

FULL = Capabilities(depth=Depth.TRUECOLOR, unicode=True, animate=False, width=80)

BROKEN = '''def above_floor(rows, floor):
    """Keep rows priced at or above `floor`."""
    return [row for row in rows if row["prise"] >= floor]
'''


def pane(caps=PLAIN, **overrides) -> Repair:
    kwargs = dict(
        code=BROKEN,
        line=3,
        error="KeyError: 'prise'",
        func="above_floor",
        values={"floor": "10.0"},
        title="Drop the cheap stock",
        caps=caps,
    )
    kwargs.update(overrides)
    return Repair(**kwargs)


def press(target: Repair, text: str) -> None:
    for character in text:
        target.handle(Key("char", character))


def key(name: str, char: str = "", ctrl: bool = False) -> Key:
    return Key(name, char, ctrl=ctrl)


class TestWhereItStarts(unittest.TestCase):
    """The pane opens on the line that raised, because that is the line the
    player watched fail and the one they came here to change."""

    def test_the_cursor_is_on_the_failing_line(self):
        self.assertEqual(pane().buffer.row, 2)

    def test_the_cursor_skips_the_indent(self):
        """Landing in the leading whitespace means the first keystroke of
        every repair is a cursor move nobody asked for."""
        self.assertEqual(pane().buffer.column, 4)

    def test_a_failing_line_past_the_end_is_clamped(self):
        """A truncated recording, or a line number from a frame that is not
        the submission, must not put the cursor outside the buffer."""
        self.assertEqual(pane(line=99).buffer.row, 2)

    def test_a_failing_line_of_zero_is_clamped(self):
        self.assertEqual(pane(line=0).buffer.row, 0)

    def test_it_starts_wanting_to_resume_nothing(self):
        self.assertFalse(pane().applied)


class TestTheFrame(unittest.TestCase):
    def test_the_geometry_is_exactly_what_was_asked_for(self):
        frame = pane().compose(20, 70)
        self.assertEqual((frame.rows, frame.columns), (20, 70))

    def test_the_error_is_on_screen(self):
        self.assertIn("KeyError: 'prise'", pane().compose(20, 70).as_text())

    def test_the_failing_line_number_is_named(self):
        self.assertIn("line 3", pane().compose(20, 70).as_text())

    def test_the_step_and_function_are_named(self):
        text = pane().compose(20, 70).as_text()
        self.assertIn("Drop the cheap stock", text)
        self.assertIn("above_floor()", text)

    def test_the_source_is_on_screen(self):
        self.assertIn('row["prise"]', pane().compose(20, 70).as_text())

    def test_the_locals_at_the_failure_are_shown(self):
        """The alternate screen has just hidden the scrollback, so a fix
        argued from remembered values would be a guess."""
        self.assertIn("floor = 10.0", pane().compose(20, 70).as_text())

    def test_no_locals_is_not_a_blank_claim(self):
        text = pane(values={}).compose(20, 70).as_text()
        self.assertIn("KeyError", text)
        self.assertNotIn("=", text.splitlines()[2])

    def test_the_failing_line_is_marked_in_the_gutter(self):
        frame = pane(caps=FULL).compose(20, 70)
        marked = [line for line in frame.as_text().splitlines()
                  if 'row["prise"]' in line]
        self.assertTrue(marked[0].lstrip().startswith("✘"), marked[0])

    def test_it_opens_with_the_failing_line_in_view(self):
        """A real submission is longer than a short terminal. Opening at the
        top and making the player hunt for the line they just watched fail is
        the whole feature not working."""
        long_code = "\n".join(f"x = {n}" for n in range(60)) + "\nboom()\n"
        frame = pane(code=long_code, line=61).compose(MIN_HEIGHT, MIN_WIDTH)
        self.assertIn("boom()", frame.as_text())

    def test_the_mark_survives_scrolling_away_from_it(self):
        """It is the line the pane exists to fix; findable only by memory is
        not findable."""
        long_code = BROKEN + "\n".join(f"# filler {n}" for n in range(60))
        target = pane(code=long_code, caps=FULL)
        target.buffer.goto(50, 0)
        frame = target.compose(20, 70)
        self.assertNotIn('row["prise"]', frame.as_text())
        target.buffer.goto(2, 4)
        self.assertIn('row["prise"]', target.compose(20, 70).as_text())

    def test_the_keys_are_shown(self):
        self.assertIn("ctrl-r resume", pane().compose(20, 70).as_text())

    def test_a_tiny_terminal_says_so_rather_than_drawing_rubbish(self):
        frame = pane().compose(MIN_HEIGHT - 1, MIN_WIDTH - 1)
        self.assertIn("too small", frame.as_text())

    def test_the_frame_is_the_same_text_at_every_depth(self):
        """The T6 rule: colour is decoration, layout is content."""
        plain = pane(caps=PLAIN).compose(20, 70).as_text()
        colour = pane(caps=Capabilities(depth=Depth.ANSI16, unicode=False,
                                        animate=False, width=70))
        self.assertEqual(plain, colour.compose(20, 70).as_text())


class TestTyping(unittest.TestCase):
    def test_characters_land_in_the_buffer(self):
        target = pane()
        press(target, "XY")
        self.assertIn("XYreturn", target.buffer.text)

    def test_a_paste_lands_whole(self):
        target = pane()
        target.handle(Key("paste", text="pasted"))
        self.assertIn("pasted", target.buffer.text)

    def test_backspace_deletes(self):
        target = pane()
        press(target, "Z")
        target.handle(key("backspace"))
        self.assertEqual(target.buffer.text, BROKEN.rstrip("\n"))

    def test_undo_is_the_editors_undo(self):
        target = pane()
        press(target, "hello")
        target.handle(key("z", "z", ctrl=True))
        self.assertEqual(target.buffer.text, BROKEN.rstrip("\n"))

    def test_a_new_line_can_be_added(self):
        """A fix is not always a one-line edit, and a pane that only lets you
        retype the failing line would decide that for the player."""
        target = pane()
        target.handle(key("home"))
        press(target, "pass")
        target.handle(key("enter"))
        self.assertIn("pass", target.buffer.lines[2])

    def test_an_unknown_key_is_ignored_rather_than_inserted(self):
        target = pane()
        target.handle(key("f13"))
        self.assertEqual(target.buffer.text, BROKEN.rstrip("\n"))


class TestResuming(unittest.TestCase):
    def test_ctrl_r_asks_to_resume(self):
        target = pane()
        target.handle(key("r", "r", ctrl=True))
        self.assertTrue(target.applied)
        self.assertFalse(target.running)

    def test_the_edit_is_what_comes_back(self):
        target = pane()
        target.buffer.goto(2, 0)
        target.handle(key("k", "k", ctrl=True))
        press(target, "    return rows")
        target.handle(key("r", "r", ctrl=True))
        self.assertIn("return rows", target.buffer.text)
        self.assertTrue(target.applied)

    def test_giving_up_is_not_resuming(self):
        target = pane()
        press(target, "edited")
        target.handle(key("x", "x", ctrl=True))
        self.assertFalse(target.running)
        self.assertFalse(target.applied)

    def test_ctrl_c_also_gives_up(self):
        target = pane()
        target.handle(key("c", "c", ctrl=True))
        self.assertFalse(target.applied)


class TestTheSyntaxGuard(unittest.TestCase):
    """A fix that will not compile costs a step of the fight to discover.
    The pane can point at it while the cursor is still next to it."""

    def test_broken_syntax_does_not_resume(self):
        target = pane()
        press(target, "(")
        target.handle(key("r", "r", ctrl=True))
        self.assertFalse(target.applied)
        self.assertTrue(target.running)

    def test_it_says_what_is_wrong(self):
        target = pane()
        press(target, "(")
        target.handle(key("r", "r", ctrl=True))
        self.assertIn("not resuming", target.status)

    def test_the_complaint_reaches_the_frame(self):
        target = pane()
        press(target, "(")
        target.handle(key("r", "r", ctrl=True))
        self.assertIn("not resuming", target.compose(20, 70).as_text())

    def test_the_complaint_clears_on_the_next_key(self):
        target = pane()
        press(target, "(")
        target.handle(key("r", "r", ctrl=True))
        target.handle(key("backspace"))
        self.assertEqual(target.status, "")

    def test_a_fixed_fix_then_resumes(self):
        target = pane()
        press(target, "(")
        target.handle(key("r", "r", ctrl=True))
        target.handle(key("backspace"))
        target.handle(key("r", "r", ctrl=True))
        self.assertTrue(target.applied)

    def test_valid_python_that_is_still_wrong_is_allowed_through(self):
        """The guard is about compiling, not about being right. Deciding a
        fix is wrong is the fight's job, and doing it here would be scoring
        the player from a text editor."""
        target = pane()
        target.buffer.load("def above_floor(rows, floor):\n    return None\n")
        target.handle(key("r", "r", ctrl=True))
        self.assertTrue(target.applied)


class TestItSharesTheEditorsKeys(unittest.TestCase):
    """A player who has used the T7 editor should not have to learn a second
    set of bindings for the same actions."""

    def test_the_bindings_come_from_the_one_table(self):
        self.assertIs(KEYMAP.get(binding(key("r", "r", ctrl=True))),
                      KEYMAP.get("ctrl-r"))

    def test_the_help_labels_differ_because_the_actions_do(self):
        labels = dict(REPAIR_HELP)
        self.assertEqual(labels["ctrl-r"], "resume")
        self.assertEqual(labels["ctrl-x"], "give up")

    def test_describe_keys_still_defaults_to_the_editors_labels(self):
        self.assertIn("ctrl-r run", describe_keys())
        self.assertIn("ctrl-r resume", describe_keys(REPAIR_HELP))


if __name__ == "__main__":
    unittest.main()
