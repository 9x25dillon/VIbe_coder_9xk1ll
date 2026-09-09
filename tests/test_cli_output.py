"""The beginner-facing output: what a player is told when they get it wrong.

The architecture rule is that nothing in the package imports `cli`. A test
importing it is not that rule being broken -- it creates no cycle, because
nothing imports the test.

Everything here asserts on escape-stripped text, so the assertions hold at
every colour depth (the T6 rule).
"""

import argparse
import io
import json
from datetime import datetime, timedelta, timezone
import os
import re
import tempfile
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest import mock

from vibecoder import abilities as ability_model
from vibecoder import cli
from vibecoder import fight as fight_model
from vibecoder.levels import all_bosses, get_boss, get_level
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


class TestABossCanBeFound(unittest.TestCase):
    """T3 W8. A boss appeared in no listing, so it could only be reached by
    already knowing its id -- which criterion 6 ("fully playable from the
    CLI") does not survive if the player cannot get to it.
    """

    def listing(self, **overrides) -> str:
        args = argparse.Namespace(map=False, campaign=False)
        for key, value in overrides.items():
            setattr(args, key, value)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": tmp}):
                return captured(cli.cmd_levels, args)

    def test_the_listing_names_every_boss_and_its_id(self):
        out = self.listing()
        for boss in all_bosses():
            with self.subTest(boss=boss.id):
                self.assertIn(boss.id, out)
                self.assertIn(boss.title, out)

    def test_the_map_names_every_boss_and_its_id(self):
        out = self.listing(map=True)
        for boss in all_bosses():
            with self.subTest(boss=boss.id):
                self.assertIn(boss.id, out)

    def test_the_listing_says_how_to_run_one(self):
        """An id the player has to assemble a command around is half a way in."""
        self.assertIn("vibecoder boss ", self.listing())

    def test_neither_listing_leaks_an_escape_sequence(self):
        """The T6 rule, on the two commands this waypoint touched."""
        for use_map in (False, True):
            with self.subTest(map=use_map):
                args = argparse.Namespace(map=use_map, campaign=False)
                with tempfile.TemporaryDirectory() as tmp:
                    with mock.patch.dict(os.environ, {"VIBECODER_HOME": tmp}):
                        with everything_printed() as buffer:
                            cli.cmd_levels(args)
                self.assertNotIn("\033", buffer.getvalue())


class TestTheWhySurface(unittest.TestCase):
    """T4 W7. `status --why` -- non-negotiable, per the waypoint.

    Nothing on this screen is computed for display: every sentence is the
    `reason` the decision was actually made with, which is what exit criterion
    4's "no hidden state" amounts to in practice.
    """

    PROFILE = {
        "version": 1, "levels": {}, "total_score": 0.0,
        "mastery": {
            "algorithms": {"value": 0.2, "observations": 6, "updated_at": ""},
            "data": {"value": 0.85, "observations": 6, "updated_at": ""},
            "tabular": {"value": 0.6, "observations": 1, "updated_at": ""},
        },
    }

    def why(self, profile=None) -> str:
        args = argparse.Namespace(why=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(
                json.dumps(self.PROFILE if profile is None else profile),
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                return captured(cli.cmd_status, args)

    def test_it_shows_what_has_been_measured(self):
        out = self.why()
        self.assertIn("what has been measured", out)
        self.assertIn("algorithms", out)

    def test_a_tag_without_enough_runs_is_shown_as_not_counting(self):
        """"We have a number and are ignoring it" is information, and hiding
        it would make the drill's choice look arbitrary."""
        self.assertIn("not enough yet", self.why())

    def test_it_explains_every_level(self):
        out = self.why()
        for level in get_level("w2-l1-revenue"), get_level("w3-l1-flatten"):
            with self.subTest(level=level.id):
                self.assertIn(level.id, out)

    def test_the_sentence_shown_is_the_one_the_decision_carries(self):
        """The screen cannot drift from the behaviour, because it is not a
        second rendering of it."""
        from vibecoder.mastery import Mastery
        from vibecoder.policy import choose_difficulty

        mastery = Mastery.from_json(self.PROFILE["mastery"])
        expected = choose_difficulty(get_level("w3-l2-window").tags, mastery).reason
        self.assertIn(expected, self.why())

    def test_it_states_what_it_does_not_know(self):
        out = self.why()
        self.assertIn("what this does not know", out)
        self.assertIn("move together", out)

    def test_an_empty_profile_says_so_rather_than_showing_a_blank(self):
        out = self.why({"version": 1, "levels": {}})
        self.assertIn("nothing measured yet", out)

    def test_an_empty_profile_still_explains_every_level(self):
        self.assertIn("w2-l1-revenue", self.why({"version": 1, "levels": {}}))

    def test_plain_status_does_not_print_the_why_surface(self):
        args = argparse.Namespace(why=False)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": tmp}):
                out = captured(cli.cmd_status, args)
        self.assertNotIn("WHY YOU GET WHAT YOU GET", out)

    def test_the_surface_emits_no_escape_sequence_into_a_pipe(self):
        args = argparse.Namespace(why=True)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": tmp}):
                with everything_printed() as buffer:
                    cli.cmd_status(args)
        self.assertNotIn("\033", buffer.getvalue())


class TestTheClassOnScreen(unittest.TestCase):
    """T4 W8. `status` shows the class and the patterns that earned it."""

    COMPREHENSIONIST = {
        "files": 20, "functions": 100,
        "patterns": {"comprehension": 0.8, "generator_expr": 0.5,
                     "builtin_aggregate": 0.7},
    }

    def status(self, vibe=None, mastery=None) -> str:
        profile = {"version": 1, "levels": {}, "total_score": 0.0}
        if vibe is not None:
            profile["vibe"] = vibe
            profile["vibe_source"] = "somewhere"
        if mastery is not None:
            profile["mastery"] = mastery
        args = argparse.Namespace(why=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                return captured(cli.cmd_status, args)

    def test_the_class_is_named(self):
        self.assertIn("Comprehensionist", self.status(self.COMPREHENSIONIST))

    def test_the_measurements_are_on_screen_beside_it(self):
        """The hazard: a class is flattery unless the numbers that earned it
        are visible, where the player can disagree with them."""
        out = self.status(self.COMPREHENSIONIST)
        self.assertIn("what earned it", out)
        self.assertIn("80%", out)
        self.assertIn("at least 45%", out)

    def test_a_player_who_has_not_profiled_sees_no_class_section(self):
        self.assertNotIn("FUNCTION CLASS", self.status())

    def test_a_codebase_that_does_not_lean_is_told_so(self):
        """Rather than being given a label it did not earn."""
        out = self.status({"files": 5, "functions": 10, "patterns": {}})
        self.assertIn("no pronounced habit", out)
        self.assertIn("not a gap", out)

    def test_equally_good_fits_are_named(self):
        """Naming one of three equal fits and hiding the rest would present a
        coin toss as a reading."""
        out = self.status({
            "files": 20, "functions": 100,
            "patterns": {"comprehension": 0.8, "generator_expr": 0.5,
                         "builtin_aggregate": 0.7, "class": 0.9,
                         "dataclass": 0.9, "property": 0.9},
        })
        self.assertIn("fits you equally well", out)
        self.assertIn("Architect", out)

    def test_scores_do_not_change_what_the_class_section_says(self):
        """Exit criterion 6, end to end through the CLI rather than on the
        function alone."""
        strong = {tag: {"value": 0.95, "observations": 9, "updated_at": ""}
                  for tag in ("functional", "oop", "data")}
        weak = {tag: {"value": 0.05, "observations": 9, "updated_at": ""}
                for tag in ("functional", "oop", "data")}

        #: Everything that can follow the class section. Listed rather than
        #: assumed: this test has twice been broken by a new block appearing
        #: below the class and being swallowed by the slice, both times
        #: reporting a criterion-6 failure that was not one. Anything below
        #: the class *should* vary with mastery -- that is the rest of the
        #: model working -- so the boundary has to be explicit.
        AFTER_THE_CLASS = ("ATTRIBUTES", "[DRILL]", "profile:")

        def class_block(mastery):
            out = self.status(self.COMPREHENSIONIST, mastery)
            start = out.index("FUNCTION CLASS")
            ends = [out.index(marker, start) for marker in AFTER_THE_CLASS
                    if marker in out[start:]]
            # Stripped: what follows the section indents differently, and
            # that whitespace belongs to the next block rather than this one.
            return out[start:min(ends)].rstrip()

        self.assertEqual(class_block(strong), class_block(weak))

    def test_habits_and_mastery_are_separate_sections(self):
        """Exit criterion 8: no screen presents a single number blending what
        you write with what you score."""
        out = self.status(self.COMPREHENSIONIST, {
            "algorithms": {"value": 0.2, "observations": 6, "updated_at": ""},
        })
        self.assertIn("FUNCTION CLASS", out)
        self.assertIn("DRILL", out)
        self.assertLess(out.index("FUNCTION CLASS"), out.index("DRILL"))

    def test_the_class_section_emits_no_escape_sequence_into_a_pipe(self):
        profile = {"version": 1, "levels": {}, "vibe": self.COMPREHENSIONIST,
                   "vibe_source": "somewhere"}
        args = argparse.Namespace(why=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                with everything_printed() as buffer:
                    cli.cmd_status(args)
        self.assertNotIn("\033", buffer.getvalue())


class TestTheAttributesSheet(unittest.TestCase):
    """T4 W9. The per-tag mastery vector, made legible beside the class.

    No new model -- these are W1's numbers. What is under test is that they
    read honestly: the evidence beside each one, the aged-out ones not
    described as never played, and the same rows on both screens.
    """

    def sheet(self, mastery=None, why=False, vibe=None) -> str:
        profile = {"version": 1, "levels": {}, "total_score": 0.0,
                   "mastery": mastery or {}}
        if vibe is not None:
            profile["vibe"] = vibe
            profile["vibe_source"] = "somewhere"
        args = argparse.Namespace(why=why)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                return captured(cli.cmd_status, args)

    def ago(self, days: float) -> str:
        return (datetime.now(timezone.utc)
                - timedelta(days=days)).isoformat(timespec="seconds")

    def fresh(self, **tags) -> dict:
        return {tag: {"value": value, "observations": 6,
                      "updated_at": self.ago(0)}
                for tag, value in tags.items()}

    def test_the_sheet_has_its_own_section(self):
        self.assertIn("ATTRIBUTES", self.sheet(self.fresh(data=0.8)))

    def test_each_attribute_shows_its_evidence(self):
        """An attribute the player cannot see the evidence for is a
        horoscope -- the trajectory's words, about this waypoint."""
        out = self.sheet(self.fresh(data=0.8))
        self.assertIn("data", out)
        self.assertIn("6 runs", out)

    def test_an_attribute_below_the_threshold_says_it_does_not_count(self):
        out = self.sheet({"data": {"value": 0.8, "observations": 1,
                                   "updated_at": self.ago(0)}})
        self.assertIn("not enough yet", out)

    def test_an_old_reading_says_how_old(self):
        """Since W6 the number shown has already had age taken off it, so
        "52%" means something different measured in June."""
        out = self.sheet({"recursion": {"value": 0.55, "observations": 6,
                                        "updated_at": self.ago(25)}})
        self.assertIn("w ago", out)

    def test_a_fresh_reading_is_not_annotated(self):
        self.assertNotIn("w ago", self.sheet(self.fresh(data=0.8)))

    def test_a_tag_played_once_yesterday_is_still_on_the_sheet(self):
        """M55: truncation used to delete it overnight."""
        out = self.sheet({"tabular": {"value": 0.6, "observations": 1,
                                      "updated_at": self.ago(1)}})
        self.assertIn("tabular", out)
        self.assertNotIn("not measured yet: tabular", out)

    def test_an_aged_out_tag_is_not_called_never_measured(self):
        """Q91's mistake on a second screen: telling a player their own
        history did not happen."""
        out = self.sheet({"strings": {"value": 0.7, "observations": 4,
                                      "updated_at": self.ago(200)}})
        self.assertIn("aged out of counting", out)
        self.assertIn("strings", out.split("aged out of counting")[1][:40])

    def test_tags_never_played_are_counted(self):
        """"What could I be measured on" is a question a character sheet
        should answer."""
        out = self.sheet(self.fresh(data=0.8))
        self.assertIn("not measured yet", out)
        self.assertIn("recursion", out)

    def test_an_empty_profile_says_so(self):
        self.assertIn("nothing measured yet", self.sheet())

    def test_both_screens_render_the_same_rows(self):
        """One renderer, deliberately. Two screens describing the same
        numbers in two places is two things that can disagree, and the one
        the player happens to open is the one they would believe."""
        mastery = self.fresh(data=0.8, algorithms=0.3)
        sheet = self.sheet(mastery)
        why = self.sheet(mastery, why=True)
        for tag in ("data", "algorithms"):
            with self.subTest(tag=tag):
                row = [l for l in sheet.splitlines() if l.strip().startswith(tag)]
                self.assertTrue(row)
                self.assertIn(row[0], why)

    def test_the_sheet_says_the_two_measurements_are_not_combined(self):
        """Exit criterion 8, said out loud on the screen it applies to."""
        out = self.sheet(self.fresh(data=0.8), vibe={
            "files": 20, "functions": 100,
            "patterns": {"comprehension": 0.8, "generator_expr": 0.5,
                         "builtin_aggregate": 0.7},
        })
        self.assertIn("never combined", out)
        self.assertLess(out.index("FUNCTION CLASS"), out.index("ATTRIBUTES"))

    def test_the_sheet_emits_no_escape_sequence_into_a_pipe(self):
        profile = {"version": 1, "levels": {},
                   "mastery": self.fresh(data=0.8, recursion=0.2)}
        args = argparse.Namespace(why=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                with everything_printed() as buffer:
                    cli.cmd_status(args)
        self.assertNotIn("\033", buffer.getvalue())


class TestAbilitiesInAFight(unittest.TestCase):
    """T4 W10, at the CLI. `--ability` equips one for a fight.

    `_spend_ability` is exercised directly rather than through a played
    fight: it only fires when a repair *mechanism* is available and the pool
    is empty, and the mechanism needs a real terminal on both streams. That
    is the same gap Q85 already names -- nothing drives the repair pane
    through a pty -- rather than a new one, and the arithmetic it performs is
    covered exhaustively in `tests/test_abilities.py`.
    """

    BOSS = "w1-boss-pipeline"

    def fight_with(self, ability=None) -> str:
        reference = get_boss(self.BOSS).reference_source()
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "broken.py"
            broken.write_text(
                reference.replace('row["price"] >= floor', 'row["prise"] >= floor'),
                encoding="utf-8",
            )
            args = argparse.Namespace(
                boss_id=self.BOSS, seed=1, live=True, reference=False,
                solution=str(broken), fix=None, speed=0.0, repairs=1,
                elapsed=None, ability=ability,
            )
            with everything_printed() as buffer:
                cli.cmd_boss(args)
            return plain(buffer.getvalue())

    def test_an_equipped_ability_is_announced_with_its_cost(self):
        """Criterion 7's first half, where the player actually reads it."""
        out = self.fight_with(["refactor"])
        self.assertIn("REFACTOR", out)
        self.assertIn("cost:", out)
        self.assertIn("the boss recovers", out)

    def test_every_ability_can_be_equipped_and_states_its_cost(self):
        for key, ability in ability_model.ALL.items():
            with self.subTest(ability=key):
                out = self.fight_with([key])
                self.assertIn(ability.name.upper(), out)
                self.assertIn(ability.cost, out)

    def test_no_banner_when_nothing_is_equipped(self):
        out = self.fight_with(None)
        self.assertNotIn("REFACTOR", out)

    def test_an_unequipped_fight_still_plays(self):
        self.assertIn("the fight stops here", self.fight_with(None))


class TestSpendingAnAbilityToSurvive(unittest.TestCase):
    """The wiring at the moment a fight would end (T4 W10).

    Driven directly, because reaching it through `cmd_boss` needs a terminal.
    """

    def spent_fight(self, cleared: int = 2, repairs: int = 1):
        fight = fight_model.Fight(steps=3, repairs=repairs)
        for index in range(cleared):
            fight.clear(index)
        fight.repair(0.5)
        return fight

    def test_it_buys_another_attempt_when_the_fight_could_pay(self):
        fight = self.spent_fight()
        self.assertFalse(fight.can_repair)
        self.assertTrue(captured(cli._spend_ability, fight, ("refactor",)))
        self.assertTrue(fight.can_repair)

    def test_it_says_what_the_purchase_cost(self):
        out = captured(cli._spend_ability, self.spent_fight(), ("refactor",))
        self.assertIn("REFACTOR", out)
        self.assertIn("cost:", out)

    def test_nothing_equipped_buys_nothing(self):
        fight = self.spent_fight()
        self.assertFalse(cli._spend_ability(fight, ()))
        self.assertFalse(fight.can_repair)

    def test_a_fight_with_no_progress_cannot_pay(self):
        """The anti-creep rule reaching the CLI: a player who has achieved
        nothing is offered nothing, which is exactly the player who would
        otherwise never lose."""
        fight = self.spent_fight(cleared=0)
        self.assertFalse(captured(cli._spend_ability, fight, ("refactor",)))
        self.assertFalse(fight.can_repair)

    def test_an_ability_that_cannot_refill_the_pool_does_not_pretend_to(self):
        """Only `refactor` returns a repair. Equipping the others must not
        revive a fight."""
        fight = self.spent_fight()
        self.assertFalse(
            captured(cli._spend_ability, fight, ("steady", "overclock"))
        )


class TestTheAbilitySheet(unittest.TestCase):
    """T4 W11 on screen: the one place both layers appear, as two sentences.

    Exit criterion 8 forbids a single number blending habits with mastery.
    None is computed anywhere -- `earned` is a set intersection -- and this
    class checks the screen keeps them as separate statements.
    """

    COMPREHENSIONIST = {
        "files": 20, "functions": 100,
        "patterns": {"comprehension": 0.8, "generator_expr": 0.5,
                     "builtin_aggregate": 0.7},
    }

    def strong(self, *tags) -> dict:
        return {tag: {"value": 0.9, "observations": 9,
                      "updated_at": datetime.now(timezone.utc).isoformat(
                          timespec="seconds")}
                for tag in tags}

    def sheet(self, vibe=None, mastery=None) -> str:
        profile = {"version": 1, "levels": {}, "mastery": mastery or {}}
        if vibe is not None:
            profile["vibe"] = vibe
            profile["vibe_source"] = "somewhere"
        args = argparse.Namespace(why=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                return captured(cli.cmd_status, args)

    def test_an_earned_ability_is_shown_with_its_cost(self):
        out = self.sheet(self.COMPREHENSIONIST, self.strong("data"))
        self.assertIn("ABILITIES", out)
        self.assertIn("Refactor", out)
        self.assertIn("cost:", out)

    def test_a_locked_ability_is_shown_with_its_gate(self):
        """An ability you cannot see is not a goal."""
        out = self.sheet(self.COMPREHENSIONIST, self.strong("data"))
        self.assertIn("Overclock", out)
        self.assertIn("needs", out)
        self.assertIn("75%", out)

    def test_more_mastery_unlocks_more(self):
        one = self.sheet(self.COMPREHENSIONIST, self.strong("data"))
        two = self.sheet(self.COMPREHENSIONIST, self.strong("data", "algorithms"))
        self.assertIn("needs", one)
        self.assertNotIn("needs", two.split("ABILITIES")[1].split("DRILL")[0])

    def test_the_screen_names_both_sources_separately(self):
        """Criterion 8 where it is most at risk: class picks which, scores
        decide when, and no figure combines them."""
        out = self.sheet(self.COMPREHENSIONIST, self.strong("data"))
        self.assertIn("your class picks which two; your scores decide when",
                      out)

    def test_without_a_profile_it_invites_rather_than_penalises(self):
        """No class is not a punishment -- abilities are flavoured by how you
        write, and that is simply not known yet."""
        out = self.sheet(None, self.strong("data", "algorithms"))
        self.assertIn("flavoured by how you write", out)
        self.assertIn("vibecoder profile", out)

    def test_a_profile_with_no_mastery_shows_everything_locked(self):
        out = self.sheet(self.COMPREHENSIONIST, {})
        self.assertIn("needs", out)

    def test_the_ability_section_emits_no_escape_sequence_into_a_pipe(self):
        profile = {"version": 1, "levels": {}, "vibe": self.COMPREHENSIONIST,
                   "vibe_source": "somewhere", "mastery": self.strong("data")}
        args = argparse.Namespace(why=False)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                with everything_printed() as buffer:
                    cli.cmd_status(args)
        self.assertNotIn("\033", buffer.getvalue())


class TestTheDailyCommand(unittest.TestCase):
    """T5 W1 at the CLI. The same challenge for everyone, named as such."""

    def show(self, when="2026-09-08") -> str:
        args = argparse.Namespace(
            date=when, show=True, solution=None, elapsed=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": tmp}):
                return captured(cli.cmd_daily, args)

    def test_it_names_the_level_and_the_variant(self):
        from vibecoder.daily import choose
        from vibecoder.levels import all_levels

        expected = choose("2026-09-08", [l.id for l in all_levels()])
        out = self.show()
        self.assertIn(expected.level_id, out)
        self.assertIn(str(expected.seed), out)

    def test_it_says_the_challenge_is_shared(self):
        out = self.show()
        self.assertIn("same level and the same variant for everyone", out)

    def test_it_says_it_is_not_adapted(self):
        """The interaction with T4 that would otherwise be invisible: a daily
        adapted to the player is a different puzzle per player."""
        self.assertIn("not adapted to you", self.show())

    def test_the_same_date_shows_the_same_thing(self):
        self.assertEqual(self.show(), self.show())

    def test_a_different_date_shows_something_else(self):
        self.assertNotEqual(self.show("2026-09-08"), self.show("2026-09-09"))

    def test_it_emits_no_escape_sequence_into_a_pipe(self):
        args = argparse.Namespace(
            date="2026-09-08", show=True, solution=None, elapsed=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": tmp}):
                with everything_printed() as buffer:
                    cli.cmd_daily(args)
        self.assertNotIn("\033", buffer.getvalue())


class TestADailyIsNotAdapted(unittest.TestCase):
    """T5 exit criterion 1 through the play path, not just the selection.

    A daily that ran at the player's adaptive difficulty would hand two
    players different data for the same challenge, and the leaderboard T5 is
    building toward would be comparing different puzzles.
    """

    LEVEL = "w2-l2-groupby"      # the one level that opts in to difficulty

    def played(self, mastery) -> str:
        from vibecoder.levels import get_level

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(
                json.dumps({"version": 1, "levels": {}, "mastery": mastery}),
                encoding="utf-8",
            )
            solution = root / "solution.py"
            solution.write_text(get_level(self.LEVEL).reference, encoding="utf-8")
            args = argparse.Namespace(
                level_id=self.LEVEL, seed=7, solution=str(solution),
                elapsed=120.0, no_vision=True,
                difficulty=0.5,
            )
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                return captured(cli.cmd_play, args)

    def strong(self) -> dict:
        return {tag: {"value": 0.95, "observations": 9, "updated_at": ""}
                for tag in ("data", "tabular", "datastructures")}

    def weak(self) -> dict:
        return {tag: {"value": 0.05, "observations": 9, "updated_at": ""}
                for tag in ("data", "tabular", "datastructures")}

    def ops(self, out: str) -> str:
        row = [l for l in out.splitlines() if "reference)" in l]
        self.assertTrue(row, out)
        return row[0].split("(")[1]

    def test_two_opposite_players_get_the_same_variant(self):
        self.assertEqual(self.ops(self.played(self.strong())),
                         self.ops(self.played(self.weak())))

    def test_the_screen_says_why_it_was_not_adapted(self):
        self.assertIn("same for everyone", self.played(self.strong()))

    def test_without_the_override_the_two_would_differ(self):
        """The paired negative. Without it, the test above would also pass for
        a difficulty dial that had stopped working."""
        from vibecoder.mastery import Mastery
        from vibecoder.models import Difficulty
        from vibecoder.policy import choose_difficulty
        from vibecoder.levels import get_level

        level = get_level(self.LEVEL)
        strong = Mastery.from_json(self.strong())
        weak = Mastery.from_json(self.weak())
        self.assertNotEqual(
            choose_difficulty(level.tags, strong).difficulty.level,
            choose_difficulty(level.tags, weak).difficulty.level,
        )


class TestTheDailyHistoryScreen(unittest.TestCase):
    """T5 W2. Your dailies and your local board, complete without a server."""

    def history(self, dailies=None) -> str:
        profile = {"version": 1, "levels": {}, "dailies": dailies or []}
        args = argparse.Namespace(
            date=None, show=False, history=True, solution=None, elapsed=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                return captured(cli.cmd_daily, args)

    def played(self, date, total, ranked=True) -> dict:
        return {"date": date, "level_id": "w1-l2-bigger", "seed": 431691,
                "total": total, "stars": 3, "ranked": ranked, "at": ""}

    def test_an_empty_history_says_so(self):
        out = self.history()
        self.assertIn("no dailies played yet", out)

    def test_it_lists_what_was_played(self):
        out = self.history([self.played("2026-09-08", 88.0)])
        self.assertIn("2026-09-08", out)
        self.assertIn("w1-l2-bigger", out)
        self.assertIn("88.0", out)

    def test_a_replay_is_marked_as_one(self):
        out = self.history([self.played("2026-09-08", 88.0),
                            self.played("2026-09-08", 99.0, ranked=False)])
        self.assertIn("replay", out)

    def test_a_replay_stays_off_the_board(self):
        """It is shown in the history because it happened, and kept off the
        board because a board of replays measures persistence."""
        out = self.history([self.played("2026-09-08", 88.0),
                            self.played("2026-09-08", 99.0, ranked=False)])
        best = out.split("your best")[1]
        self.assertIn("88.0", best)
        self.assertNotIn("99.0", best)

    def test_it_says_the_board_is_local(self):
        """Criterion 5, said out loud rather than implied by there being no
        network code yet."""
        out = self.history([self.played("2026-09-08", 88.0)])
        self.assertIn("local only", out)

    def test_it_shows_a_streak(self):
        out = self.history([self.played("2026-09-06", 80.0),
                            self.played("2026-09-07", 85.0)])
        self.assertIn("streak", out)

    def test_it_emits_no_escape_sequence_into_a_pipe(self):
        profile = {"version": 1, "levels": {},
                   "dailies": [self.played("2026-09-08", 88.0)]}
        args = argparse.Namespace(
            date=None, show=False, history=True, solution=None, elapsed=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
            with mock.patch.dict(os.environ, {"VIBECODER_HOME": str(root)}):
                with everything_printed() as buffer:
                    cli.cmd_daily(args)
        self.assertNotIn("\033", buffer.getvalue())


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
