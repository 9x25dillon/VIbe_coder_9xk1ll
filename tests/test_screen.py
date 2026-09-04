"""The cell grid and its diff. T7 exit criterion 4 lives here."""

import unittest

from vibecoder.screen import CONTINUATION, RESET, Screen, char_width, text_width


class TestWidth(unittest.TestCase):
    def test_ascii_is_one_column(self):
        self.assertEqual(char_width("a"), 1)

    def test_east_asian_characters_are_two_columns(self):
        self.assertEqual(char_width("日"), 2)

    def test_combining_marks_are_zero_columns(self):
        self.assertEqual(char_width("́"), 0)

    def test_text_width_sums_its_characters(self):
        self.assertEqual(text_width("a日"), 3)


class TestPut(unittest.TestCase):
    def test_text_lands_where_it_was_put(self):
        s = Screen(2, 10)
        s.put(1, 2, "hi")
        self.assertEqual(s.line(1), "  hi")

    def test_text_clips_at_the_right_edge_rather_than_wrapping(self):
        """A frame that wraps has overwritten the row below it."""
        s = Screen(2, 5)
        s.put(0, 0, "abcdefgh")
        self.assertEqual(s.line(0), "abcde")
        self.assertEqual(s.line(1), "")

    def test_a_row_outside_the_screen_is_ignored(self):
        s = Screen(1, 5)
        s.put(9, 0, "x")
        self.assertEqual(s.as_text(), "")

    def test_put_returns_the_next_column(self):
        s = Screen(1, 10)
        self.assertEqual(s.put(0, 0, "abc"), 3)

    def test_a_wide_character_occupies_two_cells(self):
        s = Screen(1, 6)
        end = s.put(0, 0, "日")
        self.assertEqual(end, 2)
        self.assertEqual(s.grid[0][1].char, CONTINUATION)

    def test_a_continuation_cell_is_never_shown_as_text(self):
        s = Screen(1, 6)
        s.put(0, 0, "日x")
        self.assertEqual(s.line(0), "日x")


class TestDiff(unittest.TestCase):
    def test_the_first_frame_clears_and_paints_everything(self):
        s = Screen(2, 4)
        s.put(0, 0, "ab")
        output, emitted, _ = s.diff(None)
        self.assertIn("\033[2J", output)
        self.assertEqual(emitted, 8)

    def test_an_identical_frame_emits_nothing(self):
        a = Screen(2, 6)
        a.put(0, 0, "hello")
        b = Screen(2, 6)
        b.put(0, 0, "hello")
        output, emitted, changed = b.diff(a)
        self.assertEqual(output, "")
        self.assertEqual((emitted, changed), (0, 0))

    def test_a_single_character_edit_repaints_a_single_cell(self):
        """Exit criterion 4, stated as directly as it can be."""
        a = Screen(4, 40)
        a.put(0, 0, "hello world")
        b = Screen(4, 40)
        b.put(0, 0, "hellO world")
        output, emitted, changed = b.diff(a)
        self.assertEqual((emitted, changed), (1, 1))
        self.assertNotIn("\033[2J", output)

    def test_the_damage_ratio_stays_near_one(self):
        a = Screen(4, 40)
        a.put(1, 5, "abcdefgh")
        b = Screen(4, 40)
        b.put(1, 5, "abcdefgX")
        _, emitted, changed = b.diff(a)
        self.assertLessEqual(emitted / changed, 2.0)

    def test_nearby_changes_merge_into_one_run(self):
        """Two cursor moves cost more bytes than the gap between them."""
        a = Screen(1, 20)
        b = Screen(1, 20)
        b.put(0, 0, "x")
        b.put(0, 3, "y")
        output, emitted, changed = b.diff(a)
        self.assertEqual(changed, 2)
        self.assertEqual(output.count("\033["), 1)

    def test_distant_changes_do_not_merge(self):
        a = Screen(1, 40)
        b = Screen(1, 40)
        b.put(0, 0, "x")
        b.put(0, 30, "y")
        output, _, _ = b.diff(a)
        self.assertEqual(output.count("H"), 2)

    def test_a_resize_forces_a_full_repaint(self):
        """Nothing on screen can be trusted after the geometry changes."""
        a = Screen(2, 10)
        b = Screen(3, 10)
        output, _, _ = b.diff(a)
        self.assertIn("\033[2J", output)

    def test_a_style_change_alone_counts_as_damage(self):
        a = Screen(1, 4)
        a.put(0, 0, "ab")
        b = Screen(1, 4)
        b.put(0, 0, "ab", "\033[31m")
        _, _, changed = b.diff(a)
        self.assertEqual(changed, 2)

    def test_a_style_never_leaks_past_the_end_of_a_run(self):
        """Whatever is drawn next must not inherit this frame's colour."""
        s = Screen(1, 4)
        s.put(0, 0, "abcd", "\033[31m")
        output, _, _ = s.diff(None)
        self.assertTrue(output.endswith(RESET), repr(output))

    def test_a_style_is_reset_before_unstyled_cells_in_the_same_run(self):
        s = Screen(1, 4)
        s.put(0, 0, "a", "\033[31m")
        output, _, _ = s.diff(None)
        self.assertIn(RESET, output)
        self.assertTrue(output.endswith("   "), repr(output))

    def test_a_run_never_starts_on_the_tail_of_a_wide_character(self):
        """Landing mid-glyph makes the terminal draw nonsense."""
        a = Screen(1, 8)
        a.put(0, 0, "日本")
        b = Screen(1, 8)
        b.put(0, 0, "日本")
        b.grid[0][1] = b.grid[0][1].__class__(CONTINUATION, "\033[31m")
        output, _, _ = b.diff(a)
        self.assertNotIn(CONTINUATION, output)


class TestInspection(unittest.TestCase):
    def test_line_strips_trailing_blanks(self):
        s = Screen(1, 20)
        s.put(0, 0, "x")
        self.assertEqual(s.line(0), "x")

    def test_clear_empties_the_grid(self):
        s = Screen(2, 4)
        s.put(0, 0, "ab")
        s.clear()
        self.assertEqual(s.as_text().strip(), "")


if __name__ == "__main__":
    unittest.main()
