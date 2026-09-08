"""The three-axis scoring model.

Accuracy, Speed and Functional Execution are each computed on an independent
0..100 scale, combined with weights that differ between ordinary levels and
boss fights, then multiplied by any earned bonuses.

The three axes deliberately measure different things and must not be conflated:

* **Accuracy**  - fraction of hidden tests passed. Pure correctness.
* **Speed**     - *human* wall-clock time from opening the level to the first
  fully-passing submission, compared against the level's par time. This is not
  the runtime of the submitted code.
* **Functional** - how efficiently the submitted code executes, measured as
  user-code line executions ("ops") and peak allocated memory, both benchmarked
  against the level's reference solution running under identical
  instrumentation.

See docs/SCORING.md for the reasoning behind each curve.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .models import RunResult, ScoreBreakdown


@dataclass(frozen=True)
class Weights:
    accuracy: float
    speed: float
    functional: float

    def __post_init__(self) -> None:
        total = self.accuracy + self.speed + self.functional
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"weights must sum to 1.0, got {total}")

    def without_speed(self) -> "Weights":
        """Redistribute the speed weight across the two measurable axes.

        Used when there is no honest solve time to measure -- scoring a file
        from disk, or replaying in CI. Dropping the axis entirely would hand
        out a free 100; renormalising keeps the remaining axes meaningful.
        """
        remaining = self.accuracy + self.functional
        return Weights(
            accuracy=self.accuracy / remaining,
            speed=0.0,
            functional=self.functional / remaining,
        )


LEVEL_WEIGHTS = Weights(accuracy=0.50, speed=0.25, functional=0.25)
BOSS_WEIGHTS = Weights(accuracy=0.40, speed=0.30, functional=0.30)

BONUS_RATES = {
    "first_try": 0.10,        # all tests passed on submission #1
    "elegance": 0.05,         # every declared style goal satisfied
    "clean_first_run": 0.05,  # submission #1 had no syntax error / crash
}

STAR_THRESHOLDS = (60.0, 80.0, 95.0)

# Ops are weighted above memory: line-execution count is the more stable signal,
# while tracemalloc peak is noisy for very small workloads.
OPS_SHARE = 0.7
MEM_SHARE = 0.3


def accuracy_score(result: RunResult) -> float:
    """Percentage of hidden tests passed."""
    if result.fatal or result.total_count == 0:
        return 0.0
    return 100.0 * result.passed_count / result.total_count


def speed_score(elapsed_seconds: float, par_seconds: float) -> float:
    """Hyperbolic decay past par: par -> 100, 2x par -> 50, 4x par -> 25.

    A hyperbola is used rather than a linear ramp so that a slow solve is
    always worth something. Nothing is gained by beating par, which keeps the
    axis from rewarding reckless speed over the other two.
    """
    if par_seconds <= 0:
        raise ValueError("par_seconds must be positive")
    if elapsed_seconds <= par_seconds:
        return 100.0
    return 100.0 * par_seconds / elapsed_seconds


def functional_score(
    user_ops: int,
    ref_ops: int,
    user_peak_bytes: int,
    ref_peak_bytes: int,
) -> float:
    """Efficiency of the submission relative to the reference solution.

    Each component is a ratio capped at 1.0, so matching the reference is full
    marks and beating it is not extra credit (that is what bonuses are for).
    Beating the reference still protects the score against a reference that
    happens to be slightly suboptimal.
    """
    ops = min(1.0, max(ref_ops, 1) / max(user_ops, 1))
    mem = min(1.0, max(ref_peak_bytes, 1) / max(user_peak_bytes, 1))
    return 100.0 * (OPS_SHARE * ops + MEM_SHARE * mem)


def stars_for(total: float) -> int:
    return sum(1 for threshold in STAR_THRESHOLDS if total >= threshold)


def score_submission(
    result: RunResult,
    *,
    elapsed_seconds: float,
    par_seconds: float,
    ref_ops: int,
    ref_peak_bytes: int,
    attempt: int,
    style_goals_met: bool,
    first_run_clean: bool,
    weights: Weights = LEVEL_WEIGHTS,
) -> ScoreBreakdown:
    """Combine the three axes and any bonuses into a final breakdown.

    ``attempt`` is 1-based. ``first_run_clean`` refers to whether attempt #1
    executed without a fatal error, so it is tracked by the caller across the
    whole level session rather than derived from this single result.
    """
    accuracy = accuracy_score(result)

    # A submission that passes nothing has no meaningful efficiency signal:
    # a function that instantly returns None would otherwise score full marks
    # on the functional axis.
    if accuracy == 0.0:
        functional = 0.0
    else:
        functional = functional_score(
            result.ops, ref_ops, result.peak_bytes, ref_peak_bytes
        )

    # Speed is only banked once the level is actually solved; an unsolved level
    # should not accrue credit for having been opened recently.
    speed = speed_score(elapsed_seconds, par_seconds) if result.all_passed else 0.0

    subtotal = (
        weights.accuracy * accuracy
        + weights.speed * speed
        + weights.functional * functional
    )

    bonuses: dict[str, float] = {}
    if result.all_passed and attempt == 1:
        bonuses["first_try"] = BONUS_RATES["first_try"]
    if result.all_passed and style_goals_met:
        bonuses["elegance"] = BONUS_RATES["elegance"]
    if result.all_passed and first_run_clean:
        bonuses["clean_first_run"] = BONUS_RATES["clean_first_run"]

    total = subtotal * (1.0 + sum(bonuses.values()))
    return ScoreBreakdown(
        accuracy=round(accuracy, 2),
        speed=round(speed, 2),
        functional=round(functional, 2),
        subtotal=round(subtotal, 2),
        bonuses=bonuses,
        total=round(total, 2),
        stars=stars_for(total),
    )


# --------------------------------------------------------------------------
# Boss fights (T3 W7)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class StepScore:
    """One boss step's measurements, as the fight left it.

    Every field is measured against the source the player **ended up with**,
    not against the attempt that happened to be running when the step cleared.
    A fight carries one buffer forward, so a fix typed at step two is part of
    what step one is judged on too -- which is the same rule an ordinary level
    follows when it scores the submission rather than the draft.
    """

    passed: int
    total: int
    ops: int
    ref_ops: int
    peak_bytes: int
    ref_peak_bytes: int
    #: Every style goal this step declared, satisfied. A step declaring none is
    #: vacuously met, which is why the default is True rather than False.
    style_met: bool = True


def score_fight(
    steps: Sequence[StepScore],
    *,
    elapsed_seconds: float,
    par_seconds: float,
    repairs_spent: int,
    crashed_first_run: bool,
    weights: Weights = BOSS_WEIGHTS,
) -> ScoreBreakdown:
    """Score a whole boss fight on the same three axes as a level.

    The weights differ (40/30/30 rather than 50/25/25) because a boss is a
    sequence the player has already been shown how to pass: correctness is
    less of the challenge and getting through it efficiently is more.

    **This does not score hit points.** HP and repairs are the fight's
    *outcome* and they already price how wrong the code was, via the heal
    curve in `fight.py`. Feeding them into the score as well would score one
    property twice, which is the mistake the three axes exist to avoid. The
    repair pool reaches the score once, through the `first_try` bonus, and
    the bar is reported beside the score rather than folded into it.

    ``crashed_first_run`` is the fight-wide analogue of a level's
    ``first_run_clean``: whether *any* step's opening attempt died with a
    fatal error rather than merely answering wrongly. The caller tracks it,
    because a single step's result cannot see the ones before it.
    """
    if not steps:
        raise ValueError("a fight needs at least one step to score")

    total_cases = sum(step.total for step in steps)
    passed_cases = sum(step.passed for step in steps)
    accuracy = 100.0 * passed_cases / total_cases if total_cases else 0.0

    # Pooled across every case rather than averaged per step, so the axis
    # keeps the one definition it has everywhere else: the fraction of hidden
    # tests passed. Averaging percentages would make a step with four cases
    # weigh as much as one with forty, which is a second definition of
    # Accuracy wearing the same name.
    cleared = total_cases > 0 and passed_cases == total_cases

    # Functional is computed **per step and then averaged**, not by pooling ops
    # across the fight, and the difference is not cosmetic. Pooling compares a
    # sum against a sum, so a step the fight never reached contributes zero ops
    # and drags the ratio *down* -- which `functional_score` caps at 1.0 and
    # reads as maximal efficiency. A fight abandoned on step one measured 100.0
    # on this axis that way: free points for work never done, which is M1's
    # shape a fifth time.
    #
    # Per step, a step that passed nothing scores zero rather than scoring the
    # ratio of the work it skipped. That also stops one hyper-efficient step
    # from subsidising a wasteful one, which pooling allows and the axis is not
    # supposed to.
    functional = sum(
        0.0 if step.passed == 0 else functional_score(
            step.ops, step.ref_ops, step.peak_bytes, step.ref_peak_bytes
        )
        for step in steps
    ) / len(steps)

    # Zeroed when the axis carries no weight, not merely un-weighted. A
    # dropped Speed is dropped because there is no honest solve time to
    # measure, and N5 says an axis that cannot be measured honestly must not
    # be scored -- so the breakdown must not report a value for it either.
    # Leaving it computed would put a confident `speed=100.0` into a stored
    # run whose clock started moments before it was read; the weight hides it
    # from the total, not from anyone reading the record afterwards.
    if not cleared or not weights.speed:
        speed = 0.0
    else:
        speed = speed_score(elapsed_seconds, par_seconds)

    subtotal = (
        weights.accuracy * accuracy
        + weights.speed * speed
        + weights.functional * functional
    )

    bonuses: dict[str, float] = {}
    if cleared and repairs_spent == 0:
        # The fight's reading of "first try": every step passed without a
        # repair being spent on it. It is the same condition `BOSS DOWN`
        # rests on, and since a starter must fail its own tests it is
        # reachable only by bringing your own solution (Q80).
        bonuses["first_try"] = BONUS_RATES["first_try"]
    if cleared and all(step.style_met for step in steps):
        bonuses["elegance"] = BONUS_RATES["elegance"]
    if cleared and not crashed_first_run:
        bonuses["clean_first_run"] = BONUS_RATES["clean_first_run"]

    total = subtotal * (1.0 + sum(bonuses.values()))
    return ScoreBreakdown(
        accuracy=round(accuracy, 2),
        speed=round(speed, 2),
        functional=round(functional, 2),
        subtotal=round(subtotal, 2),
        bonuses=bonuses,
        total=round(total, 2),
        stars=stars_for(total),
    )


def streak_multiplier(streak: int) -> float:
    """Consecutive 3-star clears compound the global score, capped at 2.0x."""
    return min(2.0, 1.0 + 0.1 * max(0, streak))
