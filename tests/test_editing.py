"""The text buffer. T7 exit criterion 5: proved without a terminal."""

import unittest

from vibecoder.editing import INDENT, Buffer, code_part, logical_line, scan


class TestInsertion(unittest.TestCase):
    def test_typing_advances_the_cursor(self):
        b = Buffer()
        b.insert("hi")
        self.assertEqual(b.text, "hi")
        self.assertEqual((b.row, b.column), (0, 2))

    def test_insertion_happens_at_the_cursor_not_the_end(self):
        b = Buffer("ac")
        b.goto(0, 1)
        b.insert("b")
        self.assertEqual(b.text, "abc")

    def test_a_paste_containing_newlines_becomes_multiple_lines(self):
        b = Buffer()
        b.insert("one\ntwo\nthree")
        self.assertEqual(b.lines, ["one", "two", "three"])
        self.assertEqual((b.row, b.column), (2, 5))

    def test_inserting_nothing_changes_nothing(self):
        b = Buffer("x")
        b.insert("")
        self.assertEqual(b.text, "x")


class TestNewlineIndentation(unittest.TestCase):
    """Auto-indent is why the editor is usable for Python at all."""

    def test_a_newline_carries_the_current_indentation(self):
        b = Buffer("    x = 1")
        b.end()
        b.newline()
        self.assertEqual(b.lines[1], " " * INDENT)
        self.assertEqual(b.column, INDENT)

    def test_a_colon_opens_a_block(self):
        b = Buffer("def f():")
        b.end()
        b.newline()
        self.assertEqual(b.lines[1], " " * INDENT)

    def test_an_indented_colon_adds_a_level(self):
        b = Buffer("    if x:")
        b.end()
        b.newline()
        self.assertEqual(b.lines[1], " " * (INDENT * 2))

    def test_a_newline_mid_line_splits_it(self):
        b = Buffer("abcd")
        b.goto(0, 2)
        b.newline()
        self.assertEqual(b.lines, ["ab", "cd"])


class TestDeletion(unittest.TestCase):
    def test_backspace_at_the_very_start_does_nothing(self):
        b = Buffer("x")
        b.goto(0, 0)
        b.backspace()
        self.assertEqual(b.text, "x")

    def test_backspace_at_column_zero_joins_the_previous_line(self):
        b = Buffer("ab\ncd")
        b.goto(1, 0)
        b.backspace()
        self.assertEqual(b.text, "abcd")
        self.assertEqual((b.row, b.column), (0, 2))

    def test_backspace_in_leading_whitespace_removes_a_whole_indent(self):
        b = Buffer("        x")
        b.goto(0, 8)
        b.backspace()
        self.assertEqual(b.line, " " * INDENT + "x")

    def test_backspace_after_text_removes_one_character(self):
        b = Buffer("    x = 1")
        b.end()
        b.backspace()
        self.assertEqual(b.line, "    x = ")

    def test_forward_delete_at_end_of_line_joins_the_next(self):
        b = Buffer("ab\ncd")
        b.goto(0, 2)
        b.delete()
        self.assertEqual(b.text, "abcd")

    def test_forward_delete_at_the_very_end_does_nothing(self):
        b = Buffer("ab")
        b.end()
        b.delete()
        self.assertEqual(b.text, "ab")

    def test_kill_line_truncates_at_the_cursor(self):
        b = Buffer("keep this")
        b.goto(0, 4)
        b.kill_line()
        self.assertEqual(b.text, "keep")


class TestCursor(unittest.TestCase):
    def test_left_at_column_zero_wraps_to_the_previous_line_end(self):
        b = Buffer("ab\ncd")
        b.goto(1, 0)
        b.move(d_column=-1)
        self.assertEqual((b.row, b.column), (0, 2))

    def test_right_at_line_end_wraps_to_the_next_line(self):
        b = Buffer("ab\ncd")
        b.goto(0, 2)
        b.move(d_column=1)
        self.assertEqual((b.row, b.column), (1, 0))

    def test_vertical_motion_remembers_the_column(self):
        """Travelling through a short line and back must return to column 8."""
        b = Buffer("a longer line\nx\nanother long one")
        b.goto(0, 8)
        b.move(d_row=1)
        self.assertEqual(b.column, 1)  # clamped by the short line
        b.move(d_row=1)
        self.assertEqual(b.column, 8)  # restored on the long one

    def test_home_toggles_between_indent_and_column_zero(self):
        b = Buffer("    x")
        b.end()
        b.home()
        self.assertEqual(b.column, 4)
        b.home()
        self.assertEqual(b.column, 0)

    def test_the_cursor_cannot_leave_the_buffer(self):
        b = Buffer("a")
        b.move(d_row=-5)
        b.move(d_column=-5)
        self.assertEqual((b.row, b.column), (0, 0))
        b.move(d_row=99)
        b.move(d_column=99)
        self.assertEqual((b.row, b.column), (0, 1))


class TestIndent(unittest.TestCase):
    def test_tab_in_leading_whitespace_indents_the_line(self):
        b = Buffer("x")
        b.goto(0, 0)
        b.tab()
        self.assertEqual(b.line, " " * INDENT + "x")

    def test_tab_after_text_aligns_to_the_next_stop(self):
        b = Buffer("ab")
        b.end()
        b.tab()
        self.assertEqual(len(b.line), INDENT)

    def test_dedent_removes_one_level(self):
        b = Buffer("        x")
        b.dedent()
        self.assertEqual(b.line, " " * INDENT + "x")

    def test_dedent_on_an_unindented_line_does_nothing(self):
        b = Buffer("x")
        b.dedent()
        self.assertEqual(b.line, "x")


class TestUndo(unittest.TestCase):
    """Undo steps, not keystrokes: typing a word is one undo, not five."""

    def test_consecutive_typing_collapses_into_one_step(self):
        b = Buffer()
        for character in "hello":
            b.insert(character)
        b.undo()
        self.assertEqual(b.text, "")

    def test_typing_then_deleting_is_two_steps(self):
        b = Buffer()
        b.insert("ab")
        b.backspace()
        self.assertEqual(b.text, "a")
        b.undo()
        self.assertEqual(b.text, "ab")
        b.undo()
        self.assertEqual(b.text, "")

    def test_undo_restores_the_cursor_too(self):
        b = Buffer("x")
        b.end()
        b.insert("yz")
        b.undo()
        self.assertEqual((b.row, b.column), (0, 1))

    def test_redo_reapplies_what_undo_removed(self):
        b = Buffer()
        b.insert("abc")
        b.undo()
        b.redo()
        self.assertEqual(b.text, "abc")

    def test_editing_after_undo_discards_the_redo_stack(self):
        b = Buffer()
        b.insert("abc")
        b.undo()
        b.insert("z")
        self.assertFalse(b.redo())

    def test_undo_on_an_untouched_buffer_reports_nothing_to_do(self):
        self.assertFalse(Buffer("x").undo())

    def test_undo_crosses_multiple_lines(self):
        """Exit criterion 5 names multi-line undo specifically."""
        b = Buffer("def f():")
        b.end()
        b.newline()
        b.insert("return 1")
        self.assertEqual(len(b), 2)
        b.undo()          # the insert
        b.undo()          # the newline
        self.assertEqual(b.text, "def f():")
        self.assertEqual(len(b), 1)

    def test_a_paste_undoes_as_a_single_step(self):
        b = Buffer()
        b.insert("one\ntwo\nthree")
        b.undo()
        self.assertEqual(b.text, "")

    def test_history_is_bounded(self):
        b = Buffer(undo_limit=5)
        for index in range(50):
            b.insert(str(index))
            b.break_undo()
        self.assertLessEqual(len(b._undo), 5)


class TestLoad(unittest.TestCase):
    def test_load_replaces_everything_and_is_undoable(self):
        b = Buffer("old")
        b.load("new\ntext")
        self.assertEqual(b.lines, ["new", "text"])
        b.undo()
        self.assertEqual(b.text, "old")

    def test_an_empty_buffer_still_has_one_line(self):
        self.assertEqual(Buffer("").lines, [""])


class TestTrailingComments(unittest.TestCase):
    """`if x:  # note` opens a block exactly as much as `if x:` does."""

    def _indent_after(self, line: str) -> int:
        b = Buffer(line)
        b.end()
        b.newline()
        return len(b.lines[1])

    def test_a_colon_followed_by_a_comment_still_opens_a_block(self):
        self.assertEqual(self._indent_after("if x:  # only the big ones"), INDENT)

    def test_a_comment_alone_does_not_open_a_block(self):
        self.assertEqual(self._indent_after("x = 1  # a colon: not really"), 0)

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        """`sep = "#"` must not be cut in half."""
        self.assertEqual(code_part('sep = "#"'), 'sep = "#"')

    def test_a_hash_inside_single_quotes_is_not_a_comment(self):
        self.assertEqual(code_part("sep = '#'"), "sep = '#'")

    def test_an_escaped_quote_does_not_end_the_string(self):
        self.assertEqual(code_part(r"s = 'it\'s #x'"), r"s = 'it\'s #x'")

    def test_a_comment_after_a_string_is_still_removed(self):
        self.assertEqual(code_part('s = "a"  # note').rstrip(), 's = "a"')

    def test_a_dict_literal_ending_in_a_colon_comment_indents(self):
        self.assertEqual(self._indent_after("for k, v in d.items():  # pairs"), INDENT)

    def test_a_line_with_no_comment_is_unchanged(self):
        self.assertEqual(code_part("def f():"), "def f():")

    def test_an_indented_block_with_a_comment_adds_a_level(self):
        b = Buffer("    if x:  # note")
        b.end()
        b.newline()
        self.assertEqual(len(b.lines[1]), INDENT * 2)


class TestLogicalLines(unittest.TestCase):
    """A colon opens a block only at bracket depth zero.

    The physical line is the wrong unit. ``'key':`` and ``b):`` both end in a
    colon and only one of them starts a block, so every case here is a pair
    that a raw-line check gets wrong in one direction or the other.
    """

    def _indent_after(self, text: str) -> int:
        """Indentation of the line Enter creates at the end of ``text``."""
        b = Buffer(text)
        lines = text.split("\n")
        b.goto(len(lines) - 1, len(lines[-1]))
        b.newline()
        return len(b.line) - len(b.line.lstrip())

    # -- the colon that does not open a block ------------------------------

    def test_a_colon_inside_a_dict_literal_does_not_open_a_block(self):
        """The failure this class exists for: a raw-line check indents here."""
        self.assertEqual(self._indent_after("d = {\n    'key':"), INDENT)

    def test_a_colon_in_a_subscript_does_not_open_a_block(self):
        self.assertEqual(self._indent_after("x = d['k':]"), 0)

    def test_a_colon_inside_a_string_does_not_open_a_block(self):
        self.assertEqual(self._indent_after("s = 'a:'"), 0)

    def test_a_lambda_colon_mid_line_does_not_open_a_block(self):
        self.assertEqual(self._indent_after("f = lambda x: x"), 0)

    # -- the colon that does ------------------------------------------------

    def test_a_continued_signature_opens_a_block(self):
        """``b):`` closes the bracket, so its colon is at depth zero."""
        self.assertEqual(self._indent_after("def f(a,\n      b):"), INDENT)

    def test_a_body_indents_from_the_statement_not_the_continuation(self):
        """One level in from ``def``, not one level in from ``b``."""
        self.assertEqual(self._indent_after("    def m(self,\n            x):"),
                         INDENT * 2)

    def test_an_opener_after_a_closed_multiline_call_still_opens(self):
        self.assertEqual(self._indent_after("foo(\n    a,\n)\nif z:"), INDENT)

    # -- continuations keep the alignment the author chose ------------------

    def test_a_hand_aligned_continuation_is_preserved(self):
        self.assertEqual(
            self._indent_after("    x = foo(a,\n              b,"), 14
        )

    def test_an_open_bracket_alone_does_not_indent(self):
        self.assertEqual(self._indent_after("x = foo(a,"), 0)

    # -- the scanner underneath ---------------------------------------------

    def test_scan_counts_brackets_outside_strings(self):
        self.assertEqual(scan("foo(a, [b], {c})")[1], 0)

    def test_scan_ignores_brackets_inside_strings(self):
        self.assertEqual(scan('s = "(("')[1], 0)

    def test_scan_ignores_brackets_inside_comments(self):
        self.assertEqual(scan("x = 1  # ((( note")[1], 0)

    def test_scan_reports_an_unclosed_bracket(self):
        self.assertEqual(scan("x = foo(a,")[1], 1)

    def test_scan_reports_a_closing_bracket(self):
        self.assertEqual(scan("      b)")[1], -1)

    def test_a_logical_line_starts_where_its_bracket_opened(self):
        lines = ["d = {", "    'a': 1,", "    'key':"]
        self.assertEqual(logical_line(lines, 2), (0, 1))

    def test_a_complete_statement_is_its_own_logical_line(self):
        lines = ["x = 1", "y = 2"]
        self.assertEqual(logical_line(lines, 1), (1, 0))

    def test_a_balanced_call_above_does_not_continue_into_the_next_line(self):
        lines = ["foo(", "    a,", ")", "if z:"]
        self.assertEqual(logical_line(lines, 3), (3, 0))

    def test_the_backward_walk_is_bounded(self):
        """An unclosed bracket beyond the lookback must not cost the buffer.

        The bound is the reason one Enter keypress stays constant-time on a
        large file; this pins that it is actually applied.
        """
        from vibecoder.editing import LOOKBACK

        lines = ["foo("] + ["    a," for _ in range(LOOKBACK + 50)] + ["    b:"]
        self.assertEqual(logical_line(lines, len(lines) - 1)[0],
                         len(lines) - 1)


if __name__ == "__main__":
    unittest.main()
