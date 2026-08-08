"""Tests for the presentation layer.

The governing idea: **colour is decoration, layout is content**. Every element
must produce byte-identical escape-stripped output at every colour depth, so
these tests compare visible text rather than escape sequences. That is also what
makes them readable.
"""

from __future__ import annotations

import io
import os
import unittest
from unittest import mock

from vibecoder.ui import (
    ACCENT,
    GOOD,
    PLAIN,
    Capabilities,
    Depth,
    Renderer,
    detect,
    heat,
    lerp,
    sgr,
    strip_ansi,
    visible_width,
    wrap,
)

DEPTHS = (Depth.NONE, Depth.ANSI16, Depth.ANSI256, Depth.TRUECOLOR)


def renderer(depth=Depth.NONE, *, unicode=True, animate=False, stream=None) -> Renderer:
    caps = Capabilities(depth=depth, unicode=unicode, animate=animate, width=80)
    return Renderer(caps, stream or io.StringIO())


class FakeStream(io.StringIO):
    """A stream whose TTY-ness and encoding can be dictated.

    ``io.StringIO`` reports ``encoding`` read-only and always answers False to
    ``isatty``, so detection cannot be exercised against it directly.
    """

    def __init__(self, *, tty: bool = True, encoding: str = "utf-8") -> None:
        super().__init__()
        self._tty = tty
        self._encoding = encoding

    def isatty(self) -> bool:
        return self._tty

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return self._encoding


class TestCapabilityDetection(unittest.TestCase):
    def detect_with(self, *, tty: bool = True, encoding: str = "utf-8", **env):
        """Detect against a fully controlled environment and stream."""
        with mock.patch.dict(os.environ, env, clear=True):
            return detect(FakeStream(tty=tty, encoding=encoding))

    def test_a_pipe_gets_no_colour(self):
        self.assertEqual(self.detect_with(tty=False).depth, Depth.NONE)

    def test_no_color_disables_colour_on_a_tty(self):
        self.assertEqual(self.detect_with(NO_COLOR="1").depth, Depth.NONE)

    def test_no_color_beats_force_color(self):
        """Users set NO_COLOR deliberately; it must win."""
        caps = self.detect_with(NO_COLOR="1", FORCE_COLOR="3")
        self.assertEqual(caps.depth, Depth.NONE)

    def test_colorterm_implies_truecolor(self):
        self.assertEqual(self.detect_with(COLORTERM="truecolor").depth, Depth.TRUECOLOR)

    def test_term_256_implies_256(self):
        self.assertEqual(self.detect_with(TERM="xterm-256color").depth, Depth.ANSI256)

    def test_dumb_terminal_gets_no_colour(self):
        self.assertEqual(self.detect_with(TERM="dumb").depth, Depth.NONE)

    def test_force_color_overrides_a_non_tty(self):
        self.assertEqual(
            self.detect_with(tty=False, FORCE_COLOR="3").depth, Depth.TRUECOLOR
        )

    def test_animation_requires_a_tty(self):
        self.assertFalse(self.detect_with(tty=False, FORCE_COLOR="3").animate)

    def test_animation_can_be_disabled_explicitly(self):
        caps = self.detect_with(VIBECODER_NO_ANIM="1", COLORTERM="truecolor")
        self.assertFalse(caps.animate)

    def test_non_utf8_stream_loses_unicode(self):
        self.assertFalse(self.detect_with(encoding="ascii").unicode)

    def test_utf8_stream_keeps_unicode(self):
        self.assertTrue(self.detect_with(encoding="UTF-8").unicode)


class TestColour(unittest.TestCase):
    def test_no_depth_emits_nothing(self):
        self.assertEqual(sgr((255, 0, 0), Depth.NONE), "")

    def test_truecolor_emits_rgb(self):
        self.assertEqual(sgr((10, 20, 30), Depth.TRUECOLOR), "\033[38;2;10;20;30m")

    def test_256_emits_an_index(self):
        code = sgr((255, 0, 0), Depth.ANSI256)
        self.assertTrue(code.startswith("\033[38;5;"))

    def test_16_emits_a_basic_code(self):
        self.assertIn(sgr((255, 0, 0), Depth.ANSI16), {"\033[31m", "\033[91m"})

    def test_background_differs_from_foreground(self):
        fg = sgr((1, 2, 3), Depth.TRUECOLOR)
        bg = sgr((1, 2, 3), Depth.TRUECOLOR, background=True)
        self.assertNotEqual(fg, bg)

    def test_lerp_hits_both_ends(self):
        self.assertEqual(lerp((0, 0, 0), (100, 100, 100), 0.0), (0, 0, 0))
        self.assertEqual(lerp((0, 0, 0), (100, 100, 100), 1.0), (100, 100, 100))
        self.assertEqual(lerp((0, 0, 0), (100, 100, 100), 0.5), (50, 50, 50))

    def test_lerp_clamps_out_of_range(self):
        self.assertEqual(lerp((0, 0, 0), (10, 10, 10), 5.0), (10, 10, 10))
        self.assertEqual(lerp((0, 0, 0), (10, 10, 10), -5.0), (0, 0, 0))

    def test_heat_runs_bad_to_good(self):
        self.assertGreater(heat(0.0)[0], heat(1.0)[0])   # more red at the bottom
        self.assertGreater(heat(1.0)[1], heat(0.0)[1])   # more green at the top

    def test_heat_clamps(self):
        self.assertEqual(heat(-1.0), heat(0.0))
        self.assertEqual(heat(2.0), heat(1.0))


class TestDepthInvariance(unittest.TestCase):
    """The central guarantee: colour never changes what is on the screen."""

    def visible_at_every_depth(self, draw) -> list[str]:
        return [strip_ansi(draw(renderer(depth))) for depth in DEPTHS]

    def assert_invariant(self, draw):
        rendered = self.visible_at_every_depth(draw)
        self.assertEqual(
            len(set(rendered)), 1, f"output differs across depths: {set(rendered)}"
        )

    def test_gauge_is_invariant(self):
        self.assert_invariant(lambda ui: ui.gauge(63.0, width=20))

    def test_gradient_gauge_is_invariant(self):
        self.assert_invariant(lambda ui: ui.gradient_gauge(63.0, width=20))

    def test_stars_are_invariant(self):
        self.assert_invariant(lambda ui: ui.stars(2))

    def test_sparkline_is_invariant(self):
        self.assert_invariant(lambda ui: ui.sparkline([1, 5, 2, 8, 3]))

    def test_rule_is_invariant(self):
        self.assert_invariant(lambda ui: ui.rule("TITLE", width=40))

    def test_badge_is_invariant(self):
        """Regression: a background-filled badge changed the visible text."""
        self.assert_invariant(lambda ui: ui.badge("PASS", GOOD))

    def test_box_is_invariant(self):
        self.assert_invariant(lambda ui: "\n".join(ui.box(["a", "b"], width=30)))

    def test_health_bar_is_invariant(self):
        self.assert_invariant(lambda ui: ui.health_bar(40, 100, width=20))

    def test_axis_row_is_invariant(self):
        self.assert_invariant(lambda ui: ui.axis_row("accuracy", 87.5, 0.5, "(detail)"))

    def test_level_map_is_invariant(self):
        entries = [
            {"world": 1, "world_title": "W", "id": "a", "title": "A", "stars": 3},
            {"world": 1, "world_title": "W", "id": "b", "title": "B", "stars": 0},
        ]
        self.assert_invariant(lambda ui: "\n".join(ui.level_map(entries)))

    def test_banner_is_invariant(self):
        self.assert_invariant(lambda ui: "\n".join(ui.banner()))


class TestWidth(unittest.TestCase):
    def test_gauge_is_exactly_its_width(self):
        for width in (1, 8, 24, 60):
            for value in (0.0, 33.3, 100.0):
                with self.subTest(width=width, value=value):
                    ui = renderer(Depth.TRUECOLOR)
                    self.assertEqual(visible_width(ui.gauge(value, width=width)), width)

    def test_gradient_gauge_is_exactly_its_width(self):
        for width in (4, 20, 40):
            ui = renderer(Depth.TRUECOLOR)
            self.assertEqual(
                visible_width(ui.gradient_gauge(55.0, width=width)), width
            )

    def test_rule_respects_its_width(self):
        for width in (20, 40, 76):
            for title in ("", "A TITLE"):
                with self.subTest(width=width, title=title):
                    ui = renderer()
                    self.assertLessEqual(visible_width(ui.rule(title, width=width)), width)

    def test_box_lines_share_one_width(self):
        ui = renderer(Depth.ANSI256)
        lines = ui.box(["short", "a much longer line of text"], title="T", width=44)
        widths = {visible_width(line) for line in lines}
        self.assertEqual(widths, {44})

    def test_gauge_clamps_out_of_range_values(self):
        ui = renderer()
        self.assertEqual(visible_width(ui.gauge(500.0, width=10)), 10)
        self.assertEqual(visible_width(ui.gauge(-50.0, width=10)), 10)

    def test_a_zero_maximum_does_not_divide_by_zero(self):
        ui = renderer()
        self.assertEqual(visible_width(ui.gauge(5.0, width=10, maximum=0)), 10)


class TestGlyphFallback(unittest.TestCase):
    def test_ascii_terminals_get_ascii(self):
        ui = renderer(unicode=False)
        rendered = ui.gauge(50.0, width=10) + ui.stars(2) + "".join(ui.banner())
        self.assertTrue(rendered.isascii(), "non-ascii leaked into an ascii terminal")

    def test_unicode_terminals_get_blocks(self):
        self.assertIn("█", renderer().gauge(100.0, width=4))

    def test_ascii_layout_matches_unicode_layout(self):
        """Falling back must not shift anything."""
        wide = renderer().gauge(60.0, width=20)
        narrow = renderer(unicode=False).gauge(60.0, width=20)
        self.assertEqual(visible_width(wide), visible_width(narrow))

    def test_sparkline_falls_back(self):
        ui = renderer(unicode=False)
        self.assertTrue(ui.sparkline([1, 2, 3]).isascii())


class TestElements(unittest.TestCase):
    def test_gauge_fill_tracks_value(self):
        ui = renderer()
        self.assertEqual(ui.gauge(0.0, width=10).count("█"), 0)
        self.assertEqual(ui.gauge(50.0, width=10).count("█"), 5)
        self.assertEqual(ui.gauge(100.0, width=10).count("█"), 10)

    def test_stars_show_earned_and_missing(self):
        rendered = strip_ansi(renderer().stars(2))
        self.assertEqual(rendered, "★★☆")

    def test_sparkline_of_an_empty_series_is_empty(self):
        self.assertEqual(renderer().sparkline([]), "")

    def test_a_flat_series_renders_at_the_baseline(self):
        self.assertEqual(strip_ansi(renderer().sparkline([5, 5, 5])), "▁▁▁")

    def test_sparkline_length_matches_the_series(self):
        self.assertEqual(len(strip_ansi(renderer().sparkline([1, 2, 3, 4]))), 4)

    def test_health_bar_shows_the_ratio(self):
        rendered = strip_ansi(renderer().health_bar(25, 100, width=20))
        self.assertIn("25/100", rendered)
        self.assertEqual(rendered.count("█"), 5)

    def test_level_map_groups_by_world(self):
        entries = [
            {"world": 1, "world_title": "One", "id": "a", "title": "A", "stars": 0},
            {"world": 2, "world_title": "Two", "id": "b", "title": "B", "stars": 3},
        ]
        rendered = strip_ansi("\n".join(renderer().level_map(entries)))
        self.assertIn("WORLD 1", rendered)
        self.assertIn("WORLD 2", rendered)
        self.assertIn("One", rendered)

    def test_bar_chart_renders_one_row_per_item(self):
        rows = renderer().bar_chart([("a", 10.0), ("b", 90.0)])
        self.assertEqual(len(rows), 2)


class TestAnimation(unittest.TestCase):
    """Animation must be invisible to anything that is not a live terminal."""

    def test_reveal_writes_only_the_final_line_without_a_tty(self):
        stream = io.StringIO()
        ui = renderer(Depth.TRUECOLOR, animate=False, stream=stream)
        ui.reveal_gauge("accuracy", 80.0, 0.5)
        output = stream.getvalue()
        self.assertEqual(output.count("\n"), 1)
        self.assertNotIn("\r", output)

    def test_reveal_matches_the_static_row(self):
        """The animated and non-animated paths must agree on the final frame."""
        stream = io.StringIO()
        ui = renderer(Depth.NONE, animate=False, stream=stream)
        ui.reveal_gauge("accuracy", 80.0, 0.5, "(x)")
        self.assertEqual(
            stream.getvalue().rstrip("\n"), ui.axis_row("accuracy", 80.0, 0.5, "(x)")
        )

    def test_typewriter_degrades_to_a_single_write(self):
        stream = io.StringIO()
        ui = renderer(Depth.NONE, animate=False, stream=stream)
        ui.typewriter("hello")
        self.assertEqual(stream.getvalue(), "hello\n")

    def test_star_burst_degrades_to_a_single_line(self):
        stream = io.StringIO()
        ui = renderer(Depth.NONE, animate=False, stream=stream)
        ui.star_burst(2)
        self.assertEqual(strip_ansi(stream.getvalue()), "    ★★☆\n")

    def test_animation_never_runs_without_colour(self):
        """A colourless terminal cannot redraw a line meaningfully."""
        stream = io.StringIO()
        ui = renderer(Depth.NONE, animate=True, stream=stream)
        ui.reveal_gauge("accuracy", 80.0, 0.5)
        self.assertNotIn("\r", stream.getvalue())


class TestHelpers(unittest.TestCase):
    def test_strip_ansi_removes_sequences(self):
        self.assertEqual(strip_ansi("\033[1m\033[38;2;1;2;3mhi\033[0m"), "hi")

    def test_strip_ansi_leaves_plain_text(self):
        self.assertEqual(strip_ansi("plain"), "plain")

    def test_strip_ansi_survives_a_truncated_sequence(self):
        self.assertEqual(strip_ansi("ok\033[38;2"), "ok")

    def test_visible_width_ignores_colour(self):
        ui = renderer(Depth.TRUECOLOR)
        self.assertEqual(visible_width(ui.paint("abc", ACCENT)), 3)

    def test_paint_is_a_no_op_without_colour(self):
        self.assertEqual(renderer().paint("abc", ACCENT, bold=True), "abc")

    def test_paint_of_empty_text_stays_empty(self):
        self.assertEqual(renderer(Depth.TRUECOLOR).paint("", ACCENT), "")

    def test_wrap_respects_the_width(self):
        text = "the quick brown fox jumps over the lazy dog " * 3
        for line in wrap(text, 40):
            self.assertLessEqual(len(line), 40)

    def test_wrap_keeps_every_word(self):
        text = "alpha beta gamma delta"
        self.assertEqual(" ".join(w.strip() for w in wrap(text, 12)), text)

    def test_plain_capabilities_are_inert(self):
        self.assertFalse(PLAIN.colour)
        self.assertFalse(PLAIN.animate)
        self.assertFalse(PLAIN.unicode)


if __name__ == "__main__":
    unittest.main()
