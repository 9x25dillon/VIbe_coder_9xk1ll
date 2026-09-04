"""Syntax colour. Exit criterion 6: colour changes, text never does."""

import unittest

from vibecoder.highlight import Span, highlight, highlight_line
from vibecoder.ui import FAINT, GOOD, INK, VIOLET, WARN


def rendered(line_spans) -> str:
    return "".join(span.text for span in line_spans)


class TestTextPreservation(unittest.TestCase):
    """The T6 rule, extended into the editor: layout is content."""

    SOURCES = [
        "def solve(rows):\n    return [r for r in rows if r > 10]",
        "x = 'hello'  # a comment",
        "",
        "   ",
        "def f(",                       # incomplete
        "x = 'unterminated",            # incomplete
        "if True:\n\tbad_indent = 1",   # mixed tabs
        "s = '''multi\nline\nstring'''",
        "# just a comment",
        "🎹 = 1",                        # non-ascii identifier-ish
    ]

    def test_highlighting_never_alters_the_text(self):
        for source in self.SOURCES:
            with self.subTest(source=source[:24]):
                lines = highlight(source)
                self.assertEqual(
                    "\n".join(rendered(line) for line in lines), source
                )

    def test_a_line_count_is_preserved(self):
        source = "a\nb\nc"
        self.assertEqual(len(highlight(source)), 3)


class TestColours(unittest.TestCase):
    def _colour_of(self, source, word):
        """Colour of the span containing ``word``.

        Uncoloured stretches are merged into one INK span, so an identifier
        arrives as "rows " rather than "rows" -- match on the stripped text.
        """
        for line in highlight(source):
            for span in line:
                if span.text == word or span.text.strip() == word:
                    return span.rgb
        return None

    def test_keywords_are_coloured(self):
        self.assertEqual(self._colour_of("return 1", "return"), VIOLET)

    def test_strings_are_coloured(self):
        self.assertEqual(self._colour_of("x = 'hi'", "'hi'"), GOOD)

    def test_numbers_are_coloured(self):
        self.assertEqual(self._colour_of("x = 42", "42"), WARN)

    def test_comments_are_dimmed(self):
        self.assertEqual(self._colour_of("x = 1  # note", "# note"), FAINT)

    def test_a_defined_name_differs_from_the_keyword_introducing_it(self):
        source = "def solve(x):\n    pass"
        self.assertNotEqual(
            self._colour_of(source, "def"), self._colour_of(source, "solve")
        )

    def test_plain_identifiers_stay_ink(self):
        self.assertEqual(self._colour_of("rows = 1", "rows"), INK)


class TestIncompleteInput(unittest.TestCase):
    """A buffer mid-edit is almost never valid Python. That is normal."""

    def test_incomplete_source_still_colours_what_parsed(self):
        spans = highlight("def f(")[0]
        self.assertEqual(spans[0].rgb, VIOLET)

    def test_an_unterminated_string_does_not_raise(self):
        self.assertEqual(rendered(highlight("x = 'abc")[0]), "x = 'abc")

    def test_every_prefix_of_a_program_highlights_without_raising(self):
        """The editor calls this on every keystroke, so every prefix matters."""
        source = "def solve(rows):\n    return sum(r['n'] for r in rows)"
        for length in range(len(source) + 1):
            prefix = source[:length]
            with self.subTest(length=length):
                lines = highlight(prefix)
                self.assertEqual(
                    "\n".join(rendered(line) for line in lines), prefix
                )


class TestSpans(unittest.TestCase):
    def test_an_empty_line_produces_no_spans(self):
        self.assertEqual(highlight_line("", []), [])

    def test_a_line_with_no_colour_is_one_ink_span(self):
        self.assertEqual(highlight_line("abc", []), [Span("abc", INK)])

    def test_overlapping_spans_do_not_duplicate_text(self):
        out = highlight_line("abcdef", [(0, 3, GOOD), (2, 5, WARN)])
        self.assertEqual("".join(s.text for s in out), "abcdef")

    def test_a_span_beyond_the_line_is_clipped(self):
        out = highlight_line("ab", [(0, 99, GOOD)])
        self.assertEqual("".join(s.text for s in out), "ab")


if __name__ == "__main__":
    unittest.main()
