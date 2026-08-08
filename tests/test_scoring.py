"""Scoring is the part players will argue about, so it is pinned down hard."""

import unittest

from vibecoder.models import RunResult, TestOutcome
from vibecoder.scoring import (
    BONUS_RATES,
    LEVEL_WEIGHTS,
    Weights,
    accuracy_score,
    functional_score,
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


class TestStreak(unittest.TestCase):
    def test_multiplier_grows_and_caps(self):
        self.assertEqual(streak_multiplier(0), 1.0)
        self.assertAlmostEqual(streak_multiplier(3), 1.3)
        self.assertEqual(streak_multiplier(50), 2.0)

    def test_negative_streak_is_treated_as_none(self):
        self.assertEqual(streak_multiplier(-5), 1.0)


if __name__ == "__main__":
    unittest.main()
