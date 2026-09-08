"""Scoring is the part players will argue about, so it is pinned down hard."""

import unittest

from vibecoder.models import RunResult, TestOutcome
from vibecoder.scoring import (
    BONUS_RATES,
    BOSS_WEIGHTS,
    LEVEL_WEIGHTS,
    StepScore,
    Weights,
    accuracy_score,
    functional_score,
    score_fight,
    score_submission,
    speed_score,
    stars_for,
    streak_multiplier,
)


def result(passed: int, total: int, *, ops: int = 100, peak: int = 1000) -> RunResult:
    outcomes = [
        TestOutcome(name=f"t{i}", passed=i < passed) for i in range(total)
    ]
    return RunResult(outcomes=outcomes, ops=ops, peak_bytes=peak)


class TestWeights(unittest.TestCase):
    def test_weights_must_sum_to_one(self):
        with self.assertRaises(ValueError):
            Weights(accuracy=0.5, speed=0.5, functional=0.5)

    def test_level_weights_match_the_design(self):
        self.assertEqual(
            (LEVEL_WEIGHTS.accuracy, LEVEL_WEIGHTS.speed, LEVEL_WEIGHTS.functional),
            (0.50, 0.25, 0.25),
        )

    def test_without_speed_renormalises(self):
        practice = LEVEL_WEIGHTS.without_speed()
        self.assertEqual(practice.speed, 0.0)
        self.assertAlmostEqual(practice.accuracy + practice.functional, 1.0)
        # The 2:1 ratio between accuracy and functional is preserved.
        self.assertAlmostEqual(practice.accuracy / practice.functional, 2.0)


class TestAxes(unittest.TestCase):
    def test_accuracy_is_the_pass_fraction(self):
        self.assertEqual(accuracy_score(result(3, 4)), 75.0)
        self.assertEqual(accuracy_score(result(0, 4)), 0.0)
        self.assertEqual(accuracy_score(result(4, 4)), 100.0)

    def test_accuracy_of_a_fatal_run_is_zero(self):
        self.assertEqual(accuracy_score(RunResult(error="boom")), 0.0)

    def test_speed_is_full_marks_at_or_under_par(self):
        self.assertEqual(speed_score(100, 180), 100.0)
        self.assertEqual(speed_score(180, 180), 100.0)

    def test_speed_halves_at_double_par(self):
        self.assertAlmostEqual(speed_score(360, 180), 50.0)
        self.assertAlmostEqual(speed_score(720, 180), 25.0)

    def test_speed_never_reaches_zero(self):
        self.assertGreater(speed_score(10_000, 180), 0.0)

    def test_speed_rejects_a_nonpositive_par(self):
        with self.assertRaises(ValueError):
            speed_score(10, 0)

    def test_functional_is_full_marks_when_matching_reference(self):
        self.assertAlmostEqual(functional_score(100, 100, 1000, 1000), 100.0)

    def test_functional_caps_at_full_marks_when_beating_reference(self):
        self.assertAlmostEqual(functional_score(10, 100, 100, 1000), 100.0)

    def test_functional_penalises_extra_work(self):
        score = functional_score(1000, 100, 1000, 1000)
        # ops share (0.7) collapses to a tenth; memory share (0.3) stays whole.
        self.assertAlmostEqual(score, 100 * (0.7 * 0.1 + 0.3 * 1.0))


class TestStars(unittest.TestCase):
    def test_thresholds(self):
        self.assertEqual(stars_for(0), 0)
        self.assertEqual(stars_for(59.9), 0)
        self.assertEqual(stars_for(60), 1)
        self.assertEqual(stars_for(80), 2)
        self.assertEqual(stars_for(95), 3)
        self.assertEqual(stars_for(120), 3)


class TestSubmission(unittest.TestCase):
    def base(self, **overrides):
        kwargs = dict(
            elapsed_seconds=180.0,
            par_seconds=180.0,
            ref_ops=100,
            ref_peak_bytes=1000,
            attempt=1,
            style_goals_met=True,
            first_run_clean=True,
        )
        kwargs.update(overrides)
        return kwargs

    def test_a_perfect_run_earns_every_bonus(self):
        score = score_submission(result(4, 4), **self.base())
        self.assertEqual(score.accuracy, 100.0)
        self.assertEqual(score.speed, 100.0)
        self.assertEqual(score.functional, 100.0)
        self.assertEqual(set(score.bonuses), set(BONUS_RATES))
        self.assertAlmostEqual(score.total, 120.0)
        self.assertEqual(score.stars, 3)

    def test_zero_accuracy_forces_zero_functional(self):
        """A stub returning None must not score well on efficiency."""
        score = score_submission(result(0, 4, ops=1), **self.base())
        self.assertEqual(score.accuracy, 0.0)
        self.assertEqual(score.functional, 0.0)
        self.assertEqual(score.total, 0.0)

    def test_speed_is_withheld_until_the_level_is_solved(self):
        score = score_submission(result(3, 4), **self.base(elapsed_seconds=1.0))
        self.assertEqual(score.speed, 0.0)

    def test_bonuses_require_a_full_pass(self):
        score = score_submission(result(3, 4), **self.base())
        self.assertEqual(score.bonuses, {})

    def test_first_try_bonus_only_on_attempt_one(self):
        score = score_submission(result(4, 4), **self.base(attempt=2))
        self.assertNotIn("first_try", score.bonuses)
        self.assertIn("elegance", score.bonuses)

    def test_missing_style_goals_drop_the_elegance_bonus(self):
        score = score_submission(result(4, 4), **self.base(style_goals_met=False))
        self.assertNotIn("elegance", score.bonuses)

    def test_subtotal_is_the_weighted_sum(self):
        score = score_submission(
            result(2, 4, ops=100), **self.base(attempt=3, first_run_clean=False)
        )
        # 50% accuracy, unsolved so 0 speed, full functional.
        self.assertAlmostEqual(score.subtotal, 0.5 * 50 + 0.25 * 0 + 0.25 * 100)


def step(passed: int, total: int = 6, *, ops: int = 100, ref_ops: int = 100,
         peak: int = 1000, ref_peak: int = 1000,
         style_met: bool = True) -> StepScore:
    return StepScore(
        passed=passed, total=total, ops=ops, ref_ops=ref_ops,
        peak_bytes=peak, ref_peak_bytes=ref_peak, style_met=style_met,
    )


class TestFightScoring(unittest.TestCase):
    """Boss scoring at 40/30/30 (T3 W7).

    A fight is scored on the same three axes as a level, so most of what is
    pinned here is that it did *not* quietly grow a second definition of any
    of them.
    """

    def base(self, **overrides):
        kwargs = dict(
            elapsed_seconds=100.0, par_seconds=900.0,
            repairs_spent=0, crashed_first_run=False,
        )
        kwargs.update(overrides)
        return kwargs

    def test_a_cleared_fight_takes_every_axis(self):
        score = score_fight([step(6), step(6), step(6)], **self.base())
        self.assertEqual(score.accuracy, 100.0)
        self.assertEqual(score.speed, 100.0)
        self.assertEqual(score.functional, 100.0)

    def test_accuracy_is_pooled_across_every_case(self):
        """One definition of the axis, not one per level shape.

        Three steps at 6/6, 3/6 and 0/6 is 9 of 18 cases, not the mean of
        100%, 50% and 0%. The two happen to agree here only because the steps
        are the same size; the assertion is on the pooled count so an unequal
        boss cannot drift.
        """
        score = score_fight([step(6), step(3), step(0)], **self.base())
        self.assertAlmostEqual(score.accuracy, 100.0 * 9 / 18)

    def test_a_step_that_passed_nothing_scores_no_efficiency(self):
        """The M1 shape, caught by playing an abandoned fight (T3 W7).

        A fight that stops on step one never defines the later functions, so
        they execute nothing. Pooled against the reference that reads as doing
        *less work*, which `functional_score` caps at 1.0 and reports as
        maximal efficiency -- 100.0 on an axis measuring work never done. Per
        step, an unpassed step scores zero.
        """
        cheap = step(0, ops=0, ref_ops=500)
        score = score_fight([step(6), cheap, cheap], **self.base())
        self.assertAlmostEqual(score.functional, 100.0 / 3, places=1)

    def test_efficiency_is_not_pooled_across_steps(self):
        """One frugal step must not pay for a wasteful one.

        Summed, 10 + 1000 ops against 500 + 500 is 1010 vs 1000 -- near
        parity. Per step the wasteful one scores its own ratio and the average
        lands well below full marks.
        """
        score = score_fight(
            [step(6, ops=10, ref_ops=500), step(6, ops=1000, ref_ops=500)],
            **self.base(),
        )
        self.assertLess(score.functional, 90.0)

    def test_speed_is_not_banked_on_an_unfinished_fight(self):
        score = score_fight([step(6), step(0)], **self.base())
        self.assertEqual(score.speed, 0.0)

    def test_no_bonus_survives_an_unfinished_fight(self):
        score = score_fight([step(6), step(5)], **self.base())
        self.assertEqual(score.bonuses, {})

    def test_first_try_needs_an_untouched_repair_pool(self):
        spent = score_fight([step(6), step(6)], **self.base(repairs_spent=1))
        self.assertNotIn("first_try", spent.bonuses)
        clean = score_fight([step(6), step(6)], **self.base(repairs_spent=0))
        self.assertEqual(clean.bonuses["first_try"], BONUS_RATES["first_try"])

    def test_one_missed_style_goal_drops_elegance_for_the_fight(self):
        score = score_fight(
            [step(6), step(6, style_met=False)], **self.base()
        )
        self.assertNotIn("elegance", score.bonuses)

    def test_a_fatal_opening_attempt_drops_clean_first_run(self):
        score = score_fight([step(6), step(6)],
                            **self.base(crashed_first_run=True))
        self.assertNotIn("clean_first_run", score.bonuses)
        self.assertIn("first_try", score.bonuses)

    def test_the_boss_weights_are_forty_thirty_thirty(self):
        """The waypoint's whole content. Pinned so a tweak has to be deliberate."""
        self.assertEqual(
            (BOSS_WEIGHTS.accuracy, BOSS_WEIGHTS.speed, BOSS_WEIGHTS.functional),
            (0.40, 0.30, 0.30),
        )

    def test_the_subtotal_is_the_weighted_sum(self):
        score = score_fight(
            [step(3, ops=100, ref_ops=100)],
            **self.base(elapsed_seconds=1800.0),
        )
        # 50% accuracy, unfinished so no speed, full functional on the step
        # that passed something.
        self.assertAlmostEqual(score.subtotal, 0.40 * 50 + 0.30 * 0 + 0.30 * 100)

    def test_dropping_speed_renormalises_rather_than_gifting_it(self):
        """Practice mode's rule (N5), applied to a fight."""
        weights = BOSS_WEIGHTS.without_speed()
        score = score_fight([step(6)], **self.base(), weights=weights)
        self.assertAlmostEqual(score.subtotal, 100.0)

    def test_a_dropped_speed_axis_reports_nothing_rather_than_a_hundred(self):
        """N5: an axis that cannot be measured honestly must not be scored.

        A zero weight keeps the value out of the total but not out of the
        breakdown, and the breakdown is what gets stored and read back. A
        practice fight that recorded `speed=100.0` would be a faked value
        sitting in a record, waiting for someone to quote it.
        """
        score = score_fight([step(6)], **self.base(),
                            weights=BOSS_WEIGHTS.without_speed())
        self.assertEqual(score.speed, 0.0)

    def test_a_fight_with_no_steps_is_refused(self):
        with self.assertRaises(ValueError):
            score_fight([], **self.base())


class TestStreak(unittest.TestCase):
    def test_multiplier_grows_and_caps(self):
        self.assertEqual(streak_multiplier(0), 1.0)
        self.assertAlmostEqual(streak_multiplier(3), 1.3)
        self.assertEqual(streak_multiplier(50), 2.0)

    def test_negative_streak_is_treated_as_none(self):
        self.assertEqual(streak_multiplier(-5), 1.0)


if __name__ == "__main__":
    unittest.main()
