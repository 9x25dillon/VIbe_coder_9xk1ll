"""Interaction and layout contracts for the shared terminal overhaul."""

import tempfile
from pathlib import Path
import unittest
from unittest import mock

from vibecoder import campaign, cockpit, encounter, vision
from vibecoder.campaign import Campaign
from vibecoder.editor import Editor, RunOutcome
from vibecoder.fight import Fight
from vibecoder.keys import Key
from vibecoder.levels import all_bosses, all_levels, get_level
from vibecoder.models import RunResult, ScoreBreakdown, TestOutcome
from vibecoder.repair import Repair
from vibecoder.runner import Step
from vibecoder.screen import Screen, text_width
from vibecoder.session import Session
from vibecoder.ui import Capabilities, Depth, PLAIN, Renderer


def ctrl(char):
    return Key("char", char, ctrl=True)


class TestEditorCockpit(unittest.TestCase):
    def setUp(self):
        self.editor = Editor(get_level("w2-l1-revenue"), caps=PLAIN)

    def test_objective_toggle_never_edits_the_buffer(self):
        before = self.editor.buffer.text
        self.editor.handle(ctrl("o"))
        self.editor.handle(Key("char", "x"))
        self.editor.handle(Key("paste", text="unwanted edit"))
        self.assertIn("OBJECTIVE", self.editor.compose(24, 80).as_text())
        self.assertEqual(before, self.editor.buffer.text)
        self.editor.handle(Key("escape"))
        self.assertFalse(self.editor.objective_open)

    def test_long_objective_can_be_read_to_the_end(self):
        self.editor.level = mock.Mock(wraps=self.editor.level)
        self.editor.level.title = "Long objective"
        self.editor.level.brief = "word " * 400 + "END_OF_BRIEF"
        self.editor.level.tags = ("data",)
        self.editor.level.func_name = "solve"
        self.editor.level.par_seconds = 120
        self.editor.handle(ctrl("o"))
        seen = ""
        for _ in range(80):
            seen += self.editor.compose(12, 48).as_text()
            self.editor.handle(Key("down"))
        self.assertIn("END_OF_BRIEF", seen)

    def test_wide_sidebar_does_not_overlap_long_code(self):
        self.editor.buffer.load("x = '" + "a" * 300 + "'")
        frame = self.editor.compose(24, 120)
        self.assertEqual(frame.grid[1][82].char, "|")
        self.assertNotIn("a", frame.line(1)[83:])
        self.assertIn("OBJECTIVE", frame.as_text())

    def test_horizontal_scroll_keeps_the_cursor_visible(self):
        self.editor.buffer.load("x = '" + "a" * 300 + "END'")
        self.editor.buffer.end()
        frame = self.editor.compose(24, 80)
        self.assertIn("END'", frame.line(1))
        self.assertTrue(any("\033[7m" in cell.style for cell in frame.grid[1]))
        self.editor.buffer.home()
        self.assertIn("x =", self.editor.compose(24, 80).line(1))

    def test_failed_case_and_controls_remain_visible_together(self):
        result = RunResult(outcomes=[TestOutcome("boundary", False, got="3", expected="4")])
        self.editor.outcome = RunOutcome(result, ScoreBreakdown(), 0, 1)
        self.editor.status = "Try checking the boundary."
        text = self.editor.compose(24, 80).as_text()
        for expected in ("0/1 passed", "expected 4", "got 3", "ctrl-r run", "Try checking"):
            self.assertIn(expected, text)

    def test_rhythm_is_opt_in_and_reversible(self):
        self.assertFalse(self.editor.show_rhythm)
        self.editor.handle(ctrl("p"))
        self.assertIn("wpm", self.editor.compose(24, 80).as_text())
        self.editor.handle(ctrl("p"))
        self.assertFalse(self.editor.show_rhythm)

    def test_help_lists_all_new_controls(self):
        self.editor.handle(ctrl("g"))
        text = self.editor.compose(32, 80).as_text()
        for key in ("ctrl-o", "ctrl-p", "ctrl-g", "ctrl-x"):
            self.assertIn(key, text)

    def test_long_title_does_not_overwrite_attempt(self):
        self.editor.level = mock.Mock(wraps=self.editor.level)
        self.editor.level.title = "Long " * 40
        self.editor.level.id = "level"
        self.editor.attempt = 123
        frame = self.editor.compose(12, 80)
        self.assertIn("attempt 123", frame.line(0))

    def test_geometry_and_text_are_identical_across_depths(self):
        for width in (48, 80, 109, 110, 160):
            frames = []
            for depth in Depth:
                self.editor.caps = Capabilities(depth, False, False, width)
                frame = self.editor.compose(24, width)
                frames.append(frame.as_text())
                self.assertTrue(all(text_width(frame.line(row)) <= width for row in range(24)))
            self.assertEqual(len(set(frames)), 1)


class TestRepairInspector(unittest.TestCase):
    def test_long_values_are_reachable_without_modifying_code(self):
        repair = Repair("def f():\n    pass", caps=PLAIN,
                        values={"payload": "x" * 600 + " END_OF_VALUE"},
                        resources="BOSS 80/100 HP / repairs 3")
        repair.handle(ctrl("o"))
        seen = ""
        for _ in range(50):
            seen += repair.compose(12, 48).as_text()
            repair.handle(Key("down"))
        self.assertIn("END_OF_VALUE", seen)
        self.assertIn("BOSS 80/100", seen)
        self.assertEqual(repair.buffer.text, "def f():\n    pass")

    def test_syntax_failure_keeps_resume_and_quit_visible(self):
        repair = Repair("def f(:", caps=PLAIN)
        repair.execute()
        text = repair.compose(24, 80).as_text()
        self.assertIn("not resuming", text)
        self.assertIn("ctrl-r resume", text)
        self.assertIn("ctrl-x give up", text)


class TestCampaign(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.session = Session.load(Path(self.temp.name) / "profile.json")
        self.browser = Campaign(list(all_levels()), list(all_bosses()),
                                self.session, Renderer(PLAIN))

    def test_enter_returns_the_selected_level(self):
        self.browser.handle(Key("down"))
        expected = self.browser.entries[1]
        self.browser.handle(Key("enter"))
        self.assertEqual(self.browser.choice, expected)
        self.assertFalse(self.browser.running)

    def test_boss_is_selectable_in_its_world(self):
        index = next(i for i, (kind, _) in enumerate(self.browser.entries) if kind == "boss")
        self.browser.selected = index
        text = self.browser.compose(24, 120).as_text()
        self.assertIn("BOSS ENCOUNTER", text)
        self.browser.handle(Key("enter"))
        self.assertEqual(self.browser.choice[0], "boss")

    def test_details_scroll_without_changing_selection(self):
        self.browser.handle(ctrl("o"))
        self.browser.handle(Key("pgdn"))
        self.assertEqual(self.browser.selected, 0)
        self.assertEqual(self.browser.detail_scroll, 8)
        self.browser.handle(Key("escape"))
        self.assertTrue(self.browser.running)
        self.assertFalse(self.browser.details_open)

    def test_selection_clamps_and_remains_visible_after_resize(self):
        for _ in range(100):
            self.browser.handle(Key("down"))
        for width in (48, 80, 120):
            text = self.browser.compose(12, width).as_text()
            self.assertIn(self.browser.entries[-1][1].title, text)

    def test_escape_quits_without_launching_or_saving(self):
        self.browser.handle(Key("escape"))
        self.assertIsNone(self.browser.choice)
        self.assertFalse(self.browser.running)
        self.assertFalse(self.session.path.exists())

    def test_empty_campaign_does_not_crash_on_enter(self):
        self.browser.entries = []
        self.browser.handle(Key("enter"))
        self.assertIsNone(self.browser.choice)
        self.assertIn("No challenges", self.browser.compose(24, 80).as_text())

    def test_browser_loop_observes_the_terminal_resize_property(self):
        terminal = mock.Mock()
        terminal.resized = False
        terminal.size.return_value = (24, 80)
        terminal.read.return_value = b"\r"
        terminal.__enter__ = mock.Mock(return_value=terminal)
        terminal.__exit__ = mock.Mock(return_value=False)
        with mock.patch.object(campaign, "supported", return_value=True), \
                mock.patch.object(campaign, "TerminalSession", return_value=terminal):
            choice, selected = campaign.choose(list(all_levels()), list(all_bosses()), self.session)
        self.assertEqual(choice[0], "level")
        self.assertEqual(selected, 0)
        terminal.__exit__.assert_called_once()


class TestEncounter(unittest.TestCase):
    SOURCE = "def f(x):\n    return x + 1\n"

    def test_hud_uses_actual_resources_and_trace_values(self):
        machine = vision.build_machine(self.SOURCE, "f")
        frame = vision.frames(machine, [{"line": 2, "func": "f", "locals": {"x": "9"}}])[-1]
        fight = Fight(3)
        fight.repair(0.5)
        for width in (48, 80, 120):
            text = encounter.compose(machine, frame, fight, "Example", Renderer(PLAIN), 24, width).as_text()
            self.assertIn("HP 100/100", text)
            self.assertIn("repairs 4", text)
            self.assertIn("x = 9", text)
            self.assertIn("step 1/3", text)
            self.assertIn("event 1 / live", text)

    def test_terminal_is_restored_when_live_display_raises(self):
        terminal = mock.Mock()
        terminal.resized = False
        terminal.size.return_value = (24, 80)
        terminal.write.side_effect = RuntimeError("display failed")
        with mock.patch.object(encounter, "TerminalSession", return_value=terminal):
            with self.assertRaises(RuntimeError):
                with encounter.Encounter("Example", "f", Fight(1)) as display:
                    display.enabled = True
                    display.show(self.SOURCE, [Step(0, 2, "f", {"x": "1"})])
        terminal.restore.assert_called_once()

    def test_no_animation_does_not_claim_the_terminal(self):
        with mock.patch.object(encounter, "detect", return_value=PLAIN), \
                mock.patch.object(encounter, "TerminalSession") as terminal:
            with encounter.Encounter("Example", "f", Fight(1)) as display:
                display.show(self.SOURCE, [Step(0, 2, "f", {})])
            terminal.assert_not_called()

    def test_quit_key_stops_the_live_display(self):
        terminal = mock.Mock()
        terminal.resized = False
        terminal.size.return_value = (24, 80)
        terminal.read.return_value = b"q"
        with mock.patch.object(encounter, "TerminalSession", return_value=terminal):
            with encounter.Encounter("Example", "f", Fight(1)) as display:
                display.enabled = True
                display.show(self.SOURCE, [Step(0, 2, "f", {})])
                self.assertTrue(display.cancelled)


class TestBoundedText(unittest.TestCase):
    def test_wide_glyph_at_region_edge_does_not_spill(self):
        screen = Screen(1, 12)
        cockpit.put(screen, 0, 0, "abcd界", 5)
        self.assertEqual(screen.grid[0][5].char, " ")
        self.assertEqual(cockpit.viewport("a界z", 2, 2), " z")

    def test_long_values_wrap_to_the_terminal_width(self):
        lines = cockpit.prose("界" * 40, 7)
        self.assertTrue(all(text_width(line) <= 7 for line in lines))
        self.assertEqual("".join(lines), "界" * 40)
