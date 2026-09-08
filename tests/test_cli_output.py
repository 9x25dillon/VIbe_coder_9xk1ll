"""The beginner-facing output: what a player is told when they get it wrong.

The architecture rule is that nothing in the package imports `cli`. A test
importing it is not that rule being broken -- it creates no cycle, because
nothing imports the test.

Everything here asserts on escape-stripped text, so the assertions hold at
every colour depth (the T6 rule).
"""

import argparse
import io
import os
import re
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

from vibecoder import cli
from vibecoder.levels import get_boss, get_level
from vibecoder.models import RunResult, TestCase, TestOutcome

ESCAPES = re.compile(r"\033\[[0-9;]*m")


def plain(text: str) -> str:
    return ESCAPES.sub("", text)


def captured(fn, *args, **kwargs) -> str:
    with everything_printed() as buffer:
        fn(*args, **kwargs)
    return plain(buffer.getvalue())


@contextmanager
def everything_printed():
    """Capture everything a command emits, including what `print` never sees.

    `UI` binds its stream when it is constructed, so `redirect_stdout` alone
    catches the plain prints and misses every gauge and star burst -- which is
    most of a scorecard. Both have to be swapped, or a test reads a transcript
    with the score cut out of the middle of it.
    """
    buffer = io.StringIO()
    original, cli.UI.stream = cli.UI.stream, buffer
    try:
        with redirect_stdout(buffer):
            yield buffer
    finally:
        cli.UI.stream = original


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


class TestFixingABossMidFight(unittest.TestCase):
    """T3 W4/W5 from the outside: the fight is playable, the edit carries
    forward, and a replay that stopped matching is said out loud.

    Runs real children through a real backend, because what is under test is
    the whole loop -- watch, fail, edit, resume -- and a mocked runner would
    only prove that the printing works.
    """

    BOSS = "w1-boss-pipeline"

    def setUp(self):
        reference = get_boss(self.BOSS).reference_source()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.fixed = root / "fixed.py"
        self.fixed.write_text(reference, encoding="utf-8")
        self.broken = root / "broken.py"
        self.broken.write_text(
            reference.replace('row["price"] >= floor', 'row["prise"] >= floor'),
            encoding="utf-8",
        )
        # A "fix" that also changes a line the player already watched run.
        self.divergent = root / "divergent.py"
        self.divergent.write_text(
            reference.replace(
                "    return [row for row in rows if row[\"price\"] >= floor]",
                "    floor = floor - 5\n"
                "    return [row for row in rows if row[\"price\"] >= floor]",
            ),
            encoding="utf-8",
        )

    def fight(self, fix=None, repairs=5, reference=False) -> tuple[int, str]:
        args = argparse.Namespace(
            boss_id=self.BOSS, seed=1, live=True, reference=reference,
            solution=None if reference else str(self.broken), speed=0.0,
            repairs=repairs, fix=str(fix) if fix else None,
        )
        with everything_printed() as buffer:
            code = cli.cmd_boss(args)
        return code, plain(buffer.getvalue())

    def test_without_a_fix_the_fight_stops_at_the_broken_step(self):
        code, out = self.fight()
        self.assertEqual(code, 1)
        self.assertIn("KeyError", out)
        self.assertIn("the fight stops here", out)

    def test_with_a_fix_the_fight_is_completed(self):
        """Exit criterion 3: editing the paused line and resuming completes
        the fight. Since W6 that no longer means BOSS DOWN -- a repaired
        fight is cleared and the boss is left standing."""
        code, out = self.fight(self.fixed)
        self.assertEqual(code, 0)
        self.assertIn("edit applied", out)
        self.assertIn("BOSS SURVIVES", out)
        self.assertIn("every step cleared", out)

    def test_the_resume_point_is_named_rather_than_implied(self):
        _, out = self.fight(self.fixed)
        self.assertRegex(out, r"resumed at step \d+")

    def test_a_clean_fix_does_not_cry_divergence(self):
        _, out = self.fight(self.fixed)
        self.assertNotIn("diverged", out)

    def test_a_divergent_fix_is_said_out_loud(self):
        """Exit criterion 4: the engine never presents a divergent state as
        continuous."""
        _, out = self.fight(self.divergent)
        self.assertIn("replay diverged", out)
        self.assertIn("not a continuation of what you watched", out)


class TestTheFightCostsSomething(unittest.TestCase):
    """T3 W6. A repair is bounded, reduces the damage that step deals, and
    hands the boss back an amount scaled by how wrong the code was."""

    BOSS = "w1-boss-pipeline"

    def setUp(self):
        reference = get_boss(self.BOSS).reference_source()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.fixed = root / "fixed.py"
        self.fixed.write_text(reference, encoding="utf-8")
        self.broken = root / "broken.py"
        self.broken.write_text(
            reference.replace('row["price"] >= floor', 'row["prise"] >= floor'),
            encoding="utf-8",
        )

    def fight(self, fix=None, repairs=5, reference=False) -> tuple[int, str]:
        args = argparse.Namespace(
            boss_id=self.BOSS, seed=1, live=True, reference=reference,
            solution=None if reference else str(self.broken), speed=0.0,
            repairs=repairs, fix=str(fix) if fix else None,
        )
        with everything_printed() as buffer:
            code = cli.cmd_boss(args)
        return code, plain(buffer.getvalue())

    def test_a_flawless_fight_takes_the_boss_to_zero(self):
        """Exit criterion 5, in the only direction it constrains: nothing but
        clearing every step reaches zero."""
        code, out = self.fight(reference=True)
        self.assertEqual(code, 0)
        self.assertIn("BOSS DOWN", out)
        self.assertIn("flawless", out)

    def test_the_boss_starts_at_full_health_with_a_full_pool(self):
        _, out = self.fight(reference=True)
        self.assertIn("100", out.splitlines()[3])
        self.assertIn("repairs", out)

    def test_health_is_shown_before_the_fight_and_after_every_step(self):
        """Otherwise the damage numbers are arithmetic the player has to do."""
        _, out = self.fight(reference=True)
        bars = [l for l in out.splitlines() if l.strip().startswith("boss ")]
        self.assertEqual(len(bars), 4)  # opening, then one per step
        self.assertIn("100", bars[0])
        self.assertRegex(bars[-1], r"\s0\s")  # the boss is at zero

    def test_a_repair_hands_the_boss_something_back(self):
        _, out = self.fight(self.fixed)
        self.assertIn("the boss recovers", out)

    def test_the_heal_names_the_accuracy_it_was_scaled_by(self):
        """The number is the mechanic: repairing nearly-right code is cheap
        and repairing a guess is not, so the player has to be shown which
        this was."""
        _, out = self.fight(self.fixed)
        self.assertRegex(out, r"accuracy \d+%")

    def test_a_repaired_step_deals_less_damage(self):
        """33 or 34 first try; halved after one repair."""
        _, out = self.fight(self.fixed)
        self.assertIn("cleared after 1 repair", out)
        self.assertIn("-17", out)

    def test_a_repair_is_spent_from_the_pool(self):
        _, repaired = self.fight(self.fixed)
        _, clean = self.fight(reference=True)
        self.assertNotEqual(
            [l for l in repaired.splitlines() if "repairs" in l][-1],
            [l for l in clean.splitlines() if "repairs" in l][-1],
        )

    def test_running_out_of_repairs_ends_the_fight(self):
        """The pool is the constraint. A sixth repair being quietly offered
        would make it a counter."""
        code, out = self.fight(self.fixed, repairs=0)
        self.assertEqual(code, 1)
        self.assertIn("no repairs left", out)
        self.assertIn("the fight stops here", out)

    def test_running_out_does_not_hang_on_the_paused_child(self):
        """It aborts rather than breaking: draining a child nobody released
        waits forever."""
        code, out = self.fight(self.fixed, repairs=0)
        self.assertEqual(code, 1)
        self.assertNotIn("BOSS", out.split("the fight stops here")[-1])


class TestAWrongAnswerIsRepairableToo(unittest.TestCase):
    """The way a starter fails is by *answering wrongly*, not by crashing:
    `parse_rows` returns `[]`. A fight that only offered a repair on an
    exception would refuse to let anyone play it from the beginning."""

    BOSS = "w1-boss-pipeline"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.solved = Path(self.tmp.name) / "solved.py"
        self.solved.write_text(
            get_boss(self.BOSS).reference_source(), encoding="utf-8"
        )

    def fight(self, fix=None, repairs=5) -> tuple[int, str]:
        args = argparse.Namespace(
            boss_id=self.BOSS, seed=1, live=True, reference=False,
            solution=None, speed=0.0, repairs=repairs,
            fix=str(fix) if fix else None,
        )
        with everything_printed() as buffer:
            code = cli.cmd_boss(args)
        return code, plain(buffer.getvalue())

    def test_the_starter_answers_wrongly_rather_than_crashing(self):
        """The premise of everything below.

        Asserted as a property rather than as the starter's text, which is a
        level-design choice and has already changed once (Q79). What must
        hold is that it *runs* and is *wrong* — a crash would exercise the
        other repair path and prove nothing about this one.
        """
        boss = get_boss(self.BOSS)
        result = cli._check(boss.starter_source(0), boss.step(0),
                            boss.step(0).tests_for(1))
        self.assertEqual(result.error, "")
        self.assertFalse(all(o.passed for o in result.outcomes))

    def test_a_wrong_answer_says_what_was_expected(self):
        """A percentage on its own cannot be acted on."""
        _, out = self.fight()
        self.assertIn("of cases pass", out)
        self.assertIn("WHAT WENT WRONG", out)
        self.assertIn("you gave", out)

    def test_a_wrong_answer_offers_a_repair(self):
        _, out = self.fight(self.solved)
        self.assertIn("the boss recovers", out)

    def test_the_step_is_run_again_after_such_a_repair(self):
        """There is nothing to resume when the run already finished, so the
        step restarts rather than continuing."""
        _, out = self.fight(self.solved)
        self.assertIn("running the step again with your fix", out)

    def test_the_fight_can_be_won_from_the_starter(self):
        code, out = self.fight(self.solved)
        self.assertEqual(code, 0)
        self.assertIn("every step cleared", out)

    def test_running_out_still_ends_it_on_a_wrong_answer(self):
        code, out = self.fight(self.solved, repairs=0)
        self.assertEqual(code, 1)
        self.assertIn("the fight stops here", out)


class TestTheFightIsScored(unittest.TestCase):
    """T3 W7. A fight is graded on the same three axes as a level, at 40/30/30.

    Runs real children, because the thing under test is what a player sees at
    the end of a real fight -- and the one bug this waypoint produced was
    invisible to the arithmetic and obvious in the output (see
    `test_an_abandoned_fight_is_not_maximally_efficient`).
    """

    BOSS = "w1-boss-pipeline"

    def fight(self, **overrides) -> tuple[int, str]:
        args = argparse.Namespace(
            boss_id=self.BOSS, seed=1, live=False, reference=False,
            solution=None, speed=0.0, repairs=5, fix=None, elapsed=None,
        )
        for key, value in overrides.items():
            setattr(args, key, value)
        with everything_printed() as buffer:
            code = cli.cmd_boss(args)
        return code, plain(buffer.getvalue())

    def axis(self, out: str, name: str) -> float:
        for line in out.splitlines():
            if line.strip().startswith(name):
                return float(line.split()[2])
        raise AssertionError(f"no {name} axis in:\n{out}")

    def test_a_finished_fight_prints_a_scorecard(self):
        _, out = self.fight(reference=True)
        self.assertIn("FIGHT SCORE", out)
        self.assertIn("TOTAL", out)

    def test_an_abandoned_fight_is_still_scored(self):
        """A zero printed for a reason is information; a blank is not.

        The starters fail, so this is the fight a first-time player actually
        gets, and leaving it unscored would mean the only scored fight is one
        nobody has yet had.
        """
        code, out = self.fight()
        self.assertEqual(code, 1)
        self.assertIn("the fight stops here", out)
        self.assertIn("FIGHT SCORE", out)

    def test_an_abandoned_fight_is_not_maximally_efficient(self):
        """The M1 shape, found by running the front door (T3 W7).

        A fight that stops on step one never defines the later functions, so
        they execute nothing at all. Measured by pooling ops across the fight
        that reads as *less work than the reference*, which the ratio caps at
        1.0 -- and the first version of this scorecard printed a confident
        100.0 on Functional for a fight that had achieved almost nothing.
        """
        _, out = self.fight()
        self.assertLess(self.axis(out, "accuracy"), 25.0)
        self.assertLess(self.axis(out, "functional"), 50.0)

    def test_a_fight_without_a_clock_does_not_score_speed(self):
        """N5, and M1's original shape: checking a file from disk has no
        honest solve time, so the axis is dropped and the other two are
        renormalised rather than one of them being handed a free 100."""
        _, out = self.fight(reference=True)
        self.assertIn("not measured", out)
        self.assertIn("x0.57", out)  # 0.40 renormalised over 0.40 + 0.30

    def test_supplying_a_clock_makes_the_fight_ranked(self):
        _, out = self.fight(reference=True, elapsed=900.0)
        self.assertIn("x0.40", out)
        self.assertIn("x0.30", out)
        self.assertEqual(self.axis(out, "speed"), 100.0)

    def test_the_speed_caption_only_claims_a_correction_it_made(self):
        """`--elapsed` replaces the clock rather than correcting one, so the
        caption must not say the engine subtracted its own animation."""
        _, ranked = self.fight(reference=True, elapsed=900.0)
        self.assertNotIn("slow motion excluded", ranked)

    def test_a_flawless_fight_earns_every_bonus(self):
        _, out = self.fight(reference=True)
        self.assertIn("first_try", out)
        self.assertIn("elegance", out)
        self.assertIn("clean_first_run", out)

    def test_an_abandoned_fight_earns_none_of_them(self):
        _, out = self.fight()
        self.assertNotIn("first_try", out)
        self.assertNotIn("elegance", out)

    def test_the_scorecard_emits_no_escape_sequence_into_a_pipe(self):
        """The T6 invariant, asserted rather than assumed (M36)."""
        args = argparse.Namespace(
            boss_id=self.BOSS, seed=1, live=False, reference=True,
            solution=None, speed=0.0, repairs=5, fix=None, elapsed=None,
        )
        with everything_printed() as buffer:
            cli.cmd_boss(args)
        self.assertNotIn("\033", buffer.getvalue())


class TestTheSlowMotionIsNotThePlayersTime(unittest.TestCase):
    """T3 W7. The engine subtracts its own animation from the Speed axis.

    Without this the same fight, played identically, scores differently at
    `--speed 0.1` and `--speed 2.0` -- marks for a display setting, on the
    axis that is supposed to measure the human.
    """

    def test_a_pacer_records_what_it_slept(self):
        pacer = cli._Pacer(0.02)
        for _ in range(3):
            pacer.pause()
        self.assertGreaterEqual(pacer.slept, 0.05)

    def test_a_pacer_at_zero_speed_sleeps_nothing(self):
        pacer = cli._Pacer(0.0)
        pacer.pause()
        self.assertEqual(pacer.slept, 0.0)

    def test_a_negative_delay_is_clamped_rather_than_rewarded(self):
        """`--speed -5` would otherwise credit the player time never spent."""
        pacer = cli._Pacer(-5.0)
        pacer.pause()
        self.assertEqual(pacer.slept, 0.0)


class TestTheBufferGrowsWithTheFight(unittest.TestCase):
    """A boss is one shared file and each step brings a new function. Reaching
    step two holding code that never mentions `above_floor` would ask the
    player to write a signature the game never showed them."""

    def setUp(self):
        self.boss = get_boss("w1-boss-pipeline")

    def test_the_next_steps_stub_is_added(self):
        code = self.boss.starter_source(0)
        self.assertNotIn("def above_floor", code)
        grown = cli._with_starter(code, self.boss.step(1))
        self.assertIn("def above_floor", grown)

    def test_the_stub_carries_its_signature_and_docstring(self):
        grown = cli._with_starter(self.boss.starter_source(0), self.boss.step(1))
        self.assertIn("def above_floor(rows, floor):", grown)
        self.assertIn("Keep rows priced at or above", grown)

    def test_what_the_player_wrote_is_kept_exactly(self):
        mine = "def parse_rows(lines):\n    return [1, 2, 3]\n"
        grown = cli._with_starter(mine, self.boss.step(1))
        self.assertIn("return [1, 2, 3]", grown)

    def test_solving_ahead_adds_nothing(self):
        """Already defining it means they got there first."""
        ahead = self.boss.reference_source()
        self.assertEqual(cli._with_starter(ahead, self.boss.step(1)), ahead)

    def test_it_stays_valid_python(self):
        code = self.boss.starter_source(0)
        for index in range(1, self.boss.step_count):
            code = cli._with_starter(code, self.boss.step(index))
        compile(code, "<grown>", "exec")

    def test_every_step_ends_up_defined(self):
        code = self.boss.starter_source(0)
        for index in range(1, self.boss.step_count):
            code = cli._with_starter(code, self.boss.step(index))
        for step in self.boss.steps:
            self.assertIn(f"def {step.func_name}", code)


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


class TestThePanelStaysSquare(unittest.TestCase):
    """`UI.box` does not truncate -- its contract is lines of known width.

    So an over-long value breaks out through the right-hand border. A long
    enough directory has always been able to do this; profiling an archive out
    of `~/Downloads` makes it ordinary.
    """

    def test_a_short_path_is_untouched(self):
        self.assertEqual(cli._fit_path("~/code/thing"), "~/code/thing")

    def test_a_long_path_is_shortened_to_the_limit(self):
        text = cli._fit_path("/home/someone/" + "nested/" * 40 + "repo.zip")
        self.assertEqual(len(text), cli.PANEL_VALUE)

    def test_the_tail_survives_because_it_names_the_file(self):
        text = cli._fit_path("/home/someone/" + "nested/" * 40 + "repo.zip")
        self.assertTrue(text.endswith("repo.zip"))
        self.assertTrue(text.startswith("..."))

    def test_the_marker_is_ascii_so_the_width_never_depends_on_unicode(self):
        text = cli._fit_path("/" + "a" * 200)
        self.assertNotIn("\u2026", text)

    def test_the_rendered_box_has_one_width(self):
        """The failure mode itself, end to end rather than on the helper."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deep = root / ("nesting/" * 12)
            deep.mkdir(parents=True)
            (deep / "m.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
            args = argparse.Namespace(path=str(deep), json=False)
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root / "home")}):
                output = captured(cli.cmd_profile, args)

        widths = {
            len(line) for line in output.splitlines()
            if line.startswith(("\u256d", "\u2502", "\u2570", "+", "|"))
        }
        self.assertEqual(len(widths), 1, f"box lines differ in width: {widths}")


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
