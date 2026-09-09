"""The selection policy, and the simulated players that measure it. T4 W4.

The instrument check T4 asks for is four simulated players -- always-correct,
always-naive, improving, plateaued -- run against the policy, with the success
band asserted for each.

**The simulation is built so it cannot trivially agree with the policy.** A
simulated player has a *latent* correctness and efficiency that the policy
never sees; the policy sees only the scores that come out, feeds them through
the real `observation` and the real `Mastery.observe`, and picks the next
difficulty. Only the player is fake. A simulator that consulted the policy's
own reasoning would confirm whatever the policy believed, which is M1's shape
pointed at a feedback loop.
"""

import random
import unittest

from vibecoder.levels import all_levels, get_level
from vibecoder.mastery import MIN_OBSERVATIONS, Mastery, observation
from vibecoder.models import Difficulty, VibeVector
from vibecoder.runner import reference_benchmark
from vibecoder.policy import (
    DRILL_BELOW,
    DRILL_LENGTH,
    HABIT_NUDGE,
    STRETCH,
    TARGET_SUCCESS,
    choose_difficulty,
    choose_drill,
)

TAGS = ("data", "tabular")
RUN_LENGTH = 50


class Player:
    """A simulated player, described by what they can do rather than by score.

    Two latents, because this project's whole thesis is that correct is not
    the same as good: `correctness` decides whether the tests pass and
    `efficiency` decides what the Functional axis says about how they passed.
    "Naive" in this codebase means O(n^2) and *right* -- see M1 in S001, where
    a naive solution scored 95.8 -- so the two have to move independently or
    the always-naive player cannot be expressed at all.
    """

    def __init__(self, correctness: float, efficiency: float, gain: float = 0.0):
        self.correctness = correctness
        self.efficiency = efficiency
        self.gain = gain

    def advance(self) -> None:
        self.correctness = min(1.0, self.correctness + self.gain)
        self.efficiency = min(1.0, self.efficiency + self.gain)

    def play(self, difficulty: Difficulty, rng: random.Random
             ) -> tuple[bool, float, float]:
        """One run. Returns (cleared, accuracy, functional).

        Both axes use ``latent ** (1 + difficulty)``, which gives each the
        property its real counterpart has:

        * **A fully correct solution passes at every difficulty.** W2's dial
          scales how much work an input demands, not whether the answer is
          right. A partially correct one meets more edge cases as density
          rises and trips over them more often.
        * **A perfectly efficient solution scores 100 at every difficulty**,
          because the Functional axis is measured against the reference
          running the *same* variant. An inefficient one falls further behind
          as the input grows, which is the gap `w2-l3-join` exists to teach.

        Clearing is sampled rather than thresholded. A step function would
        turn "70% likely to pass" into "always passes", which is precisely the
        signal the band is trying to measure; the `rng` is seeded by the
        caller so the run stays reproducible without being deterministic per
        level.
        """
        reach = self.correctness ** (1 + difficulty.level)
        cleared = rng.random() < reach
        accuracy = 100.0 * reach
        functional = 100.0 * self.efficiency ** (1 + difficulty.level)
        return cleared, accuracy, functional


def always_correct() -> Player:
    return Player(correctness=1.0, efficiency=1.0)


def always_naive() -> Player:
    """Right every time, and doing far too much work to get there."""
    return Player(correctness=1.0, efficiency=0.15)


def improving() -> Player:
    return Player(correctness=0.55, efficiency=0.4, gain=0.01)


def plateaued() -> Player:
    return Player(correctness=0.8, efficiency=0.5)


def simulate(player: Player, runs: int = RUN_LENGTH, seed: int = 7) -> dict:
    """Play ``runs`` levels through the real mastery loop. Returns the record.

    Only the player is simulated: the observation, the update rule and the
    policy are all the shipped code, so what is being measured is the loop
    rather than a sketch of it.
    """
    rng = random.Random(seed)
    mastery = Mastery()
    cleared = 0
    difficulties = []
    for index in range(runs):
        decision = choose_difficulty(TAGS, mastery)
        difficulties.append(decision.difficulty.level)
        won, accuracy, functional = player.play(decision.difficulty, rng)
        cleared += bool(won)
        mastery.observe(
            TAGS,
            observation(accuracy, functional, first_try=won and index > 0),
        )
        player.advance()
    return {
        "success_rate": cleared / runs,
        "final_mastery": mastery.value(TAGS[0]),
        "final_difficulty": difficulties[-1],
        "difficulties": difficulties,
    }


class TestTheDecisionNamesItsSource(unittest.TestCase):
    """Exit criterion 4: explainable in one sentence, with no hidden state."""

    def test_a_cold_profile_falls_back_to_the_standard_variant(self):
        decision = choose_difficulty(TAGS, Mastery())
        self.assertEqual(decision.source, "default")
        self.assertEqual(decision.difficulty.level, 0.5)

    def test_habits_are_used_only_when_nothing_is_measured(self):
        decision = choose_difficulty(TAGS, Mastery(), VibeVector(tags=["data"]))
        self.assertEqual(decision.source, "habits")

    def test_mastery_wins_the_moment_there_is_evidence(self):
        """Habits are what we guess with before measuring, not a term averaged
        in forever."""
        mastery = Mastery()
        for _ in range(MIN_OBSERVATIONS):
            mastery.observe(TAGS, 0.9)
        decision = choose_difficulty(TAGS, mastery, VibeVector(tags=["data"]))
        self.assertEqual(decision.source, "mastery")

    def test_every_decision_carries_a_sentence(self):
        for decision in (
            choose_difficulty(TAGS, Mastery()),
            choose_difficulty(TAGS, Mastery(), VibeVector(tags=["data"])),
        ):
            with self.subTest(source=decision.source):
                self.assertTrue(decision.reason)
                self.assertTrue(decision.reason[0].islower())
                self.assertLess(len(decision.reason), 200)

    def test_the_evidence_shows_the_working(self):
        mastery = Mastery()
        for _ in range(MIN_OBSERVATIONS):
            mastery.observe(TAGS, 0.9)
        decision = choose_difficulty(TAGS, mastery)
        self.assertEqual(decision.evidence["tags_used"], sorted(TAGS))
        self.assertIn("mean_mastery", decision.evidence)

    def test_a_habits_decision_says_it_came_from_code_not_scores(self):
        """Criterion 8's spirit: the player is never shown a blend, they are
        shown which source was used."""
        decision = choose_difficulty(TAGS, Mastery(), VibeVector(tags=["data"]))
        self.assertIn("codebase", decision.reason)
        self.assertIn("not what you have scored", decision.evidence["note"])

    def test_a_thinly_evidenced_tag_is_named_as_ignored(self):
        mastery = Mastery()
        for _ in range(MIN_OBSERVATIONS):
            mastery.observe(("data",), 0.9)
        mastery.observe(("tabular",), 0.9)
        decision = choose_difficulty(TAGS, mastery)
        self.assertEqual(decision.evidence["tags_used"], ["data"])
        self.assertEqual(decision.evidence["tags_ignored"], ["tabular"])


class TestTheDialResponds(unittest.TestCase):
    def confident(self, value: float) -> Mastery:
        mastery = Mastery()
        for _ in range(30):
            mastery.observe(TAGS, value)
        return mastery

    def test_a_stronger_player_gets_a_harder_variant(self):
        weak = choose_difficulty(TAGS, self.confident(0.2)).difficulty.level
        strong = choose_difficulty(TAGS, self.confident(0.9)).difficulty.level
        self.assertLess(weak, strong)

    def test_difficulty_sits_below_mastery_so_most_runs_go_well(self):
        """Matching difficulty to mastery exactly is a coin flip, not the 75%
        the band asks for."""
        mastery = self.confident(0.8)
        decision = choose_difficulty(TAGS, mastery)
        self.assertAlmostEqual(
            decision.difficulty.level, mastery.value("data") - STRETCH, places=3
        )

    def test_habits_can_never_reach_an_extreme(self):
        """A prior is a guess. The worst a wrong one may do is hand someone a
        slightly roomier or tighter first run."""
        for tags in (["data", "tabular"], []):
            with self.subTest(tags=tags):
                decision = choose_difficulty(TAGS, Mastery(), VibeVector(tags=tags))
                # Compared against the bounds rather than an absolute
                # difference: `0.65 - 0.5` is 0.15000000000000002 in binary
                # floating point, which would fail a bound the policy honours.
                self.assertGreaterEqual(decision.difficulty.level, 0.5 - HABIT_NUDGE)
                self.assertLessEqual(decision.difficulty.level, 0.5 + HABIT_NUDGE)

    def test_only_the_levels_own_tags_are_read(self):
        """Being strong at `data` earns no credit on a `recursion` level --
        the whole reason mastery is per tag."""
        mastery = self.confident(0.95)
        decision = choose_difficulty(("recursion",), mastery)
        self.assertEqual(decision.source, "default")


#: Pooling many runs rather than trusting one. A single 50-level run has a
#: standard error of about 6 points, so a seed-dependent assertion would sit
#: two points from the band edge and fail on a Tuesday. Twenty runs of fifty
#: is a tight enough estimate to assert against.
BAND_SEEDS = range(1, 21)


def pooled(make_player) -> float:
    rates = [simulate(make_player(), seed=seed)["success_rate"]
             for seed in BAND_SEEDS]
    return sum(rates) / len(rates)


class TestTheSuccessBand(unittest.TestCase):
    """Exit criterion 3, measured over simulated 50-level runs.

    Read `TestWhatTheBandCannotHold` before trusting a green result here: two
    of the four players the instrument check names cannot be held inside the
    band by any policy built on W2's dial, and that is a property of the
    criterion rather than of this code.
    """

    def test_an_improving_player_stays_in_the_band(self):
        rate = pooled(improving)
        self.assertGreaterEqual(rate, 0.60)
        self.assertLessEqual(rate, 0.90)

    def test_a_plateaued_player_stays_in_the_band(self):
        rate = pooled(plateaued)
        self.assertGreaterEqual(rate, 0.60)
        self.assertLessEqual(rate, 0.90)

    def test_both_land_near_the_target_rather_than_merely_inside_the_band(self):
        """60-90% is the criterion; ~75% is the point. A policy scraping the
        edge would pass the criterion and still be a bad game."""
        for name, make in (("improving", improving), ("plateaued", plateaued)):
            with self.subTest(player=name):
                self.assertAlmostEqual(pooled(make), TARGET_SUCCESS, delta=0.08)

    def test_an_improving_player_is_given_harder_work_as_they_improve(self):
        record = simulate(improving())
        early = record["difficulties"][:10]
        late = record["difficulties"][-10:]
        self.assertGreater(sum(late) / 10, sum(early) / 10)

    def test_a_plateaued_player_settles_rather_than_oscillating(self):
        """The instrument check asks for oscillation to be looked for.

        A stochastic player makes the estimate wobble, and a wobble is not an
        oscillation: what would matter is a spread that *grows*, or a limit
        cycle. Measured over 30 seeds the last-ten span averages 0.084 and the
        runs-20-to-30 span averages the same, so it is stationary noise around
        an equilibrium. Asserted as "bounded and not growing" rather than
        against a threshold picked by eye.
        """
        spans_mid, spans_late = [], []
        for seed in range(1, 21):
            difficulties = simulate(plateaued(), seed=seed)["difficulties"]
            mid, late = difficulties[20:30], difficulties[-10:]
            spans_mid.append(max(mid) - min(mid))
            spans_late.append(max(late) - min(late))

        self.assertLess(max(spans_late), 0.2)
        # Not growing: the late spread is no wider than the middle one.
        self.assertLess(
            sum(spans_late) / len(spans_late),
            sum(spans_mid) / len(spans_mid) + 0.02,
        )

    def test_a_plateaued_player_stops_drifting(self):
        """Settled means the *level* stops moving too, not only that the
        spread stays bounded."""
        drifts = []
        for seed in range(1, 21):
            difficulties = simulate(plateaued(), seed=seed)["difficulties"]
            mid, late = difficulties[20:30], difficulties[-10:]
            drifts.append(abs(sum(late) / 10 - sum(mid) / 10))
        self.assertLess(sum(drifts) / len(drifts), 0.05)

    def test_an_improving_player_by_contrast_keeps_drifting_upward(self):
        """The paired negative. Without it, "stops drifting" would also pass
        for a policy that had stopped responding to anything."""
        drifts = []
        for seed in range(1, 21):
            difficulties = simulate(improving(), seed=seed)["difficulties"]
            mid, late = difficulties[20:30], difficulties[-10:]
            drifts.append(sum(late) / 10 - sum(mid) / 10)
        self.assertGreater(sum(drifts) / len(drifts), 0.1)

    def test_nobody_is_driven_to_an_extreme(self):
        """The first hazard, in both directions: a good player who never gets
        a win, and a struggling one who is patronised."""
        for name, make in (("improving", improving), ("plateaued", plateaued),
                           ("naive", always_naive)):
            with self.subTest(player=name):
                record = simulate(make())
                self.assertLess(record["final_difficulty"], 1.0)
                self.assertGreater(record["final_difficulty"], 0.0)


class TestTheOffsetIsNotTheDial(unittest.TestCase):
    """`STRETCH` barely moves the band, and pretending otherwise would be a
    lie about which knob matters (M49).

    The loop is self-correcting: lowering difficulty raises the observed
    result, which raises mastery, which raises difficulty back. The
    equilibrium success rate is set by the *observation weights*, not by the
    policy's offset -- measured at 70% with no offset at all and 74% at three
    times the shipped value.
    """

    def rate_at(self, stretch: float) -> float:
        from vibecoder import policy

        original = policy.STRETCH
        try:
            policy.STRETCH = stretch
            return sum(
                simulate(improving(), seed=seed)["success_rate"]
                for seed in range(1, 11)
            ) / 10
        finally:
            policy.STRETCH = original

    def test_removing_the_offset_entirely_keeps_the_band(self):
        self.assertGreaterEqual(self.rate_at(0.0), 0.60)
        self.assertLessEqual(self.rate_at(0.0), 0.90)

    def test_tripling_the_offset_keeps_the_band(self):
        self.assertGreaterEqual(self.rate_at(0.3), 0.60)
        self.assertLessEqual(self.rate_at(0.3), 0.90)

    def test_the_offset_moves_the_rate_only_slightly(self):
        self.assertLess(abs(self.rate_at(0.3) - self.rate_at(0.0)), 0.10)


class TestWhatTheBandCannotHold(unittest.TestCase):
    """A finding about exit criterion 3, recorded rather than worked around.

    T4's instrument check asks that the 60-90% band hold for all four
    simulated players. **It cannot**, and no policy built on W2's difficulty
    dial can make it, because that dial scales how much work an input demands
    rather than whether the answer is right. A player who always writes a
    correct solution always clears -- 100%, above the band, by construction
    and at every seed tried.

    N7 forbids editing an exit criterion to match what was built. The
    criterion stands as written and this is the finding against it (Q89).
    """

    def test_an_always_correct_player_succeeds_every_time(self):
        for seed in BAND_SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(
                    simulate(always_correct(), seed=seed)["success_rate"], 1.0
                )

    def test_an_always_naive_player_also_succeeds_every_time(self):
        """"Naive" here means O(n^2) and *right* -- see M1 in S001, where a
        naive solution scored 95.8. Difficulty punishes them on the Functional
        axis, which is what that axis is for, and never on whether they
        cleared."""
        for seed in BAND_SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(
                    simulate(always_naive(), seed=seed)["success_rate"], 1.0
                )

    def test_the_naive_player_is_still_held_below_the_ace(self):
        """The policy is not idle for them. A low Functional score drags
        mastery down, so they sit at a gentler variant than a player who is
        both correct and efficient -- it just cannot drag them below the floor
        that being correct first time already earns."""
        naive = simulate(always_naive())["final_difficulty"]
        ace = simulate(always_correct())["final_difficulty"]
        self.assertLess(naive, ace - 0.2)

    def test_being_correct_every_time_sets_a_mastery_floor(self):
        """Accuracy weighs 0.5 and first-try 0.2, so a player who is always
        right first time cannot be scored below 0.7 however inefficient they
        are. That is the mechanism behind the limit above."""
        self.assertGreater(simulate(always_naive())["final_mastery"], 0.7)

    def test_the_always_correct_player_is_pushed_to_the_hardest_variant(self):
        self.assertGreater(simulate(always_correct())["final_difficulty"], 0.85)


class TestTwoPlayersGetDifferentVariants(unittest.TestCase):
    """Exit criterion 1, on a real level rather than on the policy alone.

    "Two players with opposite profiles receive measurably different variant
    parameters on the same level id" -- so this goes through `tests_for` and
    counts the rows that actually come out, not the number the policy chose.
    """

    LEVEL = "w2-l2-groupby"

    def profile(self, value: float) -> Mastery:
        mastery = Mastery()
        for _ in range(30):
            mastery.observe(get_level(self.LEVEL).tags, value)
        return mastery

    def rows_for(self, value: float) -> int:
        level = get_level(self.LEVEL)
        decision = choose_difficulty(level.tags, self.profile(value))
        cases = level.tests_for(1, decision.difficulty)
        return sum(
            len(case.args[0]) for case in cases if case.name.startswith("random_")
        )

    def test_opposite_profiles_get_measurably_different_variants(self):
        weak, strong = self.rows_for(0.15), self.rows_for(0.95)
        self.assertLess(weak, strong)
        # "Measurably" rather than "detectably": a handful of rows would
        # satisfy the letter of the criterion and change nothing a player
        # could feel.
        self.assertGreater(strong - weak, 100)

    def test_the_same_profile_gets_the_same_variant(self):
        self.assertEqual(self.rows_for(0.6), self.rows_for(0.6))

    def test_a_cold_profile_lands_between_the_two(self):
        cold = get_level(self.LEVEL)
        decision = choose_difficulty(cold.tags, Mastery())
        rows = sum(
            len(case.args[0])
            for case in cold.tests_for(1, decision.difficulty)
            if case.name.startswith("random_")
        )
        self.assertLess(self.rows_for(0.15), rows)
        self.assertLess(rows, self.rows_for(0.95))

    def test_the_reference_is_benchmarked_on_the_same_variant(self):
        """Otherwise the Functional axis divides a player's ops by a
        denominator measured on a smaller input, and punishes them for a size
        the game chose."""
        level = get_level(self.LEVEL)
        gentle = choose_difficulty(level.tags, self.profile(0.15)).difficulty
        hard = choose_difficulty(level.tags, self.profile(0.95)).difficulty
        gentle_ops, _ = reference_benchmark(level, 1, gentle)
        hard_ops, _ = reference_benchmark(level, 1, hard)
        self.assertGreater(hard_ops, gentle_ops)

    def test_the_benchmark_cache_is_keyed_by_difficulty(self):
        """The bug this guards: a cache keyed only by (level, seed) would
        serve the first difficulty's numbers to every later one."""
        level = get_level(self.LEVEL)
        first = reference_benchmark(level, 3, Difficulty(0.0))
        second = reference_benchmark(level, 3, Difficulty(1.0))
        self.assertNotEqual(first, second)
        self.assertEqual(first, reference_benchmark(level, 3, Difficulty(0.0)))


class TestDrills(unittest.TestCase):
    """T4 W5. Repeated practice on the one tag the player is weakest at."""

    def setUp(self):
        self.levels = list(all_levels())

    def profile(self, **tags) -> Mastery:
        """A profile with each tag at a given value and enough observations."""
        mastery = Mastery()
        for tag, value in tags.items():
            for _ in range(MIN_OBSERVATIONS + 1):
                mastery.observe((tag,), value)
        return mastery

    # -- when there is no drill ------------------------------------------

    def test_a_cold_profile_gets_no_drill(self):
        """Nothing measured is not the same as measured badly."""
        self.assertIsNone(choose_drill(self.levels, Mastery()))

    def test_a_strong_player_gets_no_drill(self):
        """A drill offered to someone who does not need one is noise, and it
        teaches them to ignore the next one."""
        self.assertIsNone(
            choose_drill(self.levels, self.profile(algorithms=0.9, data=0.85))
        )

    def test_a_tag_at_the_threshold_is_not_drilled(self):
        """`DRILL_BELOW` is 'measurably below the middle', not 'at it'."""
        self.assertIsNone(
            choose_drill(self.levels, self.profile(algorithms=DRILL_BELOW))
        )

    def test_a_thinly_evidenced_weak_tag_is_not_drilled(self):
        """Acting on one unlucky afternoon is what MIN_OBSERVATIONS exists to
        prevent, and a drill is a strong action to take on one data point."""
        mastery = Mastery()
        mastery.observe(("algorithms",), 0.05)
        self.assertFalse(mastery.confident("algorithms"))
        self.assertIsNone(choose_drill(self.levels, mastery))

    def test_a_weak_tag_no_level_carries_is_not_drilled(self):
        """A drill needs somewhere to send the player. A tag the content does
        not cover is a content gap, not a practice problem."""
        self.assertIsNone(
            choose_drill(self.levels, self.profile(underwater_basketweaving=0.1))
        )

    def test_no_levels_at_all_gives_no_drill(self):
        self.assertIsNone(choose_drill([], self.profile(algorithms=0.1)))

    # -- when there is ----------------------------------------------------

    def test_the_weakest_confident_tag_is_chosen(self):
        drill = choose_drill(
            self.levels, self.profile(algorithms=0.4, recursion=0.1, data=0.2)
        )
        self.assertEqual(drill.tag, "recursion")

    def test_a_strong_tag_is_never_chosen_over_a_weak_one(self):
        drill = choose_drill(self.levels, self.profile(data=0.95, recursion=0.2))
        self.assertEqual(drill.tag, "recursion")

    def test_the_queue_is_exactly_the_drill_length(self):
        drill = choose_drill(self.levels, self.profile(recursion=0.2))
        self.assertEqual(len(drill.levels), DRILL_LENGTH)

    def test_the_drill_is_long_enough_to_be_worth_re_reading(self):
        """`DRILL_LENGTH` is `MIN_OBSERVATIONS` on purpose: after a drill the
        tag is confident again by definition, so the game is not adapting to
        a drill whose result it cannot yet measure."""
        self.assertGreaterEqual(DRILL_LENGTH, MIN_OBSERVATIONS)

    def test_every_level_in_the_queue_carries_the_tag(self):
        drill = choose_drill(self.levels, self.profile(recursion=0.2))
        for level_id in drill.levels:
            with self.subTest(level=level_id):
                self.assertIn(drill.tag, get_level(level_id).tags)

    def test_a_well_covered_tag_varies_the_level(self):
        """Asking the same question three times drills the level, not the
        skill."""
        drill = choose_drill(self.levels, self.profile(algorithms=0.2))
        self.assertGreater(len(set(drill.levels)), 1)

    def test_a_single_level_tag_repeats_that_level(self):
        """`recursion` is carried by one level. Repeating it is the honest
        answer -- each run still draws a new seed and a fresh difficulty --
        and the evidence says how thin the coverage is."""
        drill = choose_drill(self.levels, self.profile(recursion=0.2))
        self.assertEqual(len(set(drill.levels)), 1)
        self.assertEqual(drill.evidence["distinct_levels"], 1)

    def test_the_drill_explains_itself(self):
        """Same rule as a difficulty decision: the reason travels with it.

        The percentage is derived from the model rather than written in:
        `observe` moves *toward* a target exponentially, so four runs at 0.2
        leave the estimate at 0.27, and a hard-coded figure here would be
        asserting my arithmetic rather than the sentence.
        """
        mastery = self.profile(recursion=0.2)
        drill = choose_drill(self.levels, mastery)
        self.assertIn("recursion", drill.reason)
        self.assertIn(f"{mastery.value('recursion'):.0%}", drill.reason)

    def test_the_evidence_shows_the_working(self):
        drill = choose_drill(self.levels, self.profile(recursion=0.2))
        self.assertEqual(drill.evidence["threshold"], DRILL_BELOW)
        self.assertGreaterEqual(drill.evidence["observations"], MIN_OBSERVATIONS)

    def test_the_choice_is_stable_across_calls(self):
        mastery = self.profile(algorithms=0.2, recursion=0.2)
        first = choose_drill(self.levels, mastery)
        second = choose_drill(self.levels, mastery)
        self.assertEqual(first, second)

    def test_drilling_a_tag_can_lift_it_out_of_the_drill_band(self):
        """The loop closes: a drill the player does well at stops being
        offered. A drill that recurred forever would be a punishment."""
        mastery = self.profile(recursion=0.2)
        self.assertIsNotNone(choose_drill(self.levels, mastery))
        for _ in range(8):
            mastery.observe(("recursion",), 1.0)
        self.assertIsNone(choose_drill(self.levels, mastery))


if __name__ == "__main__":
    unittest.main()
