"""The beginner-facing output: what a player is told when they get it wrong.

The architecture rule is that nothing in the package imports `cli`. A test
importing it is not that rule being broken -- it creates no cycle, because
nothing imports the test.

Everything here asserts on escape-stripped text, so the assertions hold at
every colour depth (the T6 rule).
"""

import io
import re
import unittest
from contextlib import redirect_stdout

from vibecoder import cli
from vibecoder.levels import get_level
from vibecoder.models import RunResult, TestCase, TestOutcome

ESCAPES = re.compile(r"\033\[[0-9;]*m")


def plain(text: str) -> str:
    return ESCAPES.sub("", text)


def captured(fn, *args, **kwargs) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        fn(*args, **kwargs)
    return plain(buffer.getvalue())


class TestTheFailureBlock(unittest.TestCase):
    """Without the input, a player cannot reproduce the failure by hand."""

    TESTS = [
        TestCase("tie", [["cat", "dog"]], expected="cat"),
        TestCase("other", [["a"]], expected="a"),
    ]

    def result(self, **kwargs):
        return RunResult(outcomes=[
            TestOutcome(name="tie", passed=False, got="'dog'", expected="'cat'"),
            TestOutcome(name="other", passed=True),
        ], **kwargs)

    def test_the_input_is_shown(self):
        text = captured(cli._print_first_failure, self.result(), self.TESTS)
        self.assertIn("['cat', 'dog']", text)

    def test_the_expectation_and_the_answer_are_shown(self):
        text = captured(cli._print_first_failure, self.result(), self.TESTS)
        self.assertIn("'cat'", text)
        self.assertIn("'dog'", text)

    def test_nothing_is_printed_when_everything_passed(self):
        clean = RunResult(outcomes=[TestOutcome(name="tie", passed=True)])
        self.assertEqual(captured(cli._print_first_failure, clean, self.TESTS), "")

    def test_an_error_is_reported_instead_of_a_value(self):
        broken = RunResult(outcomes=[
            TestOutcome(name="tie", passed=False, error="IndexError: nope"),
        ])
        text = captured(cli._print_first_failure, broken, self.TESTS)
        self.assertIn("IndexError: nope", text)
        self.assertIn("raised", text)

    def test_identical_errors_are_collapsed_into_one_line(self):
        """Eight copies of one bug teaches nothing the first did not."""
        broken = RunResult(outcomes=[
            TestOutcome(name=f"t{i}", passed=False, error="IndexError: nope")
            for i in range(7)
        ])
        text = captured(cli._print_first_failure, broken, [])
        self.assertIn("The other 6 cases stopped the same way", text)
        self.assertEqual(text.count("IndexError: nope"), 1)

    def test_mixed_failures_are_counted_rather_than_collapsed(self):
        mixed = RunResult(outcomes=[
            TestOutcome(name="a", passed=False, error="IndexError: nope"),
            TestOutcome(name="b", passed=False, got="1", expected="2"),
        ])
        text = captured(cli._print_first_failure, mixed, [])
        self.assertIn("1 more case failed", text)

    def test_the_count_is_singular_for_one_other_case(self):
        mixed = RunResult(outcomes=[
            TestOutcome(name="a", passed=False, got="1", expected="2"),
            TestOutcome(name="b", passed=False, got="3", expected="4"),
        ])
        self.assertIn("1 more case failed", captured(cli._print_first_failure, mixed, []))

    def test_a_case_with_no_matching_test_still_reports(self):
        """The outcome names a case the caller did not supply."""
        orphan = RunResult(outcomes=[
            TestOutcome(name="unknown", passed=False, got="1", expected="2"),
        ])
        text = captured(cli._print_first_failure, orphan, self.TESTS)
        self.assertIn("WHAT WENT WRONG", text)


class TestLongValuesAreShortened(unittest.TestCase):
    def test_a_short_value_is_untouched(self):
        self.assertEqual(cli._echo([1, 2, 3]), "[1, 2, 3]")

    def test_a_long_value_is_shortened(self):
        text = cli._echo(list(range(400)))
        self.assertLessEqual(len(text), cli.MAX_ECHO)

    def test_both_ends_survive(self):
        """The ends say what the data is and where it stops."""
        text = cli._echo(list(range(400)))
        self.assertTrue(text.startswith("[0, 1"))
        self.assertTrue(text.endswith("399]"))
        self.assertIn("...", text)

    def test_a_string_is_echoed_without_extra_quoting(self):
        self.assertEqual(cli._echo("hello"), "hello")


class TestTheHintLadder(unittest.TestCase):
    LEVEL = get_level("w1-l6-tally")

    def test_the_first_attempt_prints_nothing(self):
        self.assertEqual(captured(cli._print_hints, self.LEVEL, 1), "")

    def test_the_second_attempt_prints_one_hint(self):
        text = captured(cli._print_hints, self.LEVEL, 2)
        self.assertIn("HINT", text)
        self.assertIn(self.LEVEL.hints[0][:30], text)

    def test_later_attempts_reprint_the_whole_ladder(self):
        """The earlier rungs have scrolled away, and the sequence is the point."""
        text = captured(cli._print_hints, self.LEVEL, 3)
        self.assertIn(self.LEVEL.hints[0][:30], text)
        self.assertIn(self.LEVEL.hints[1][:30], text)

    def test_a_level_with_no_hints_prints_nothing(self):
        self.assertEqual(captured(cli._print_hints, get_level("w3-l2-window"), 5), "")


class TestWhatComesNext(unittest.TestCase):
    """A win that ends at the shell prompt has to be re-entered on willpower."""

    def setUp(self):
        from vibecoder.session import Session

        self.session = Session()

    def next_up(self, level_id: str) -> str:
        return captured(cli._print_next_up, get_level(level_id), self.session)

    def test_the_following_level_is_named(self):
        text = self.next_up("w1-l1-greet")
        self.assertIn("Pick the Larger", text)
        self.assertIn("w1-l2-bigger", text)

    def test_finishing_a_world_is_marked(self):
        text = self.next_up("w1-l6-tally")
        self.assertIn("WORLD 1 COMPLETE", text)
        self.assertIn("First Steps", text)

    def test_a_mid_world_clear_is_not_marked_as_a_world_completion(self):
        self.assertNotIn("COMPLETE", self.next_up("w1-l2-bigger"))

    def test_the_next_world_s_first_level_follows_a_world_completion(self):
        self.assertIn("Revenue Above Threshold", self.next_up("w1-l6-tally"))

    def test_the_last_level_ends_the_campaign(self):
        text = self.next_up("w3-l3-wordfreq")
        self.assertIn("CAMPAIGN COMPLETE", text)
        self.assertNotIn("next up", text)

    def test_an_unknown_level_is_ignored_rather_than_raising(self):
        from vibecoder.models import Level

        stray = Level(
            id="nope", world=9, world_title="X", index=1, title="X",
            brief="x" * 50, func_name="f", starter="def f(): pass",
            reference="def f(): pass", make_tests=lambda rng: [],
        )
        self.assertEqual(captured(cli._print_next_up, stray, self.session), "")


if __name__ == "__main__":
    unittest.main()
