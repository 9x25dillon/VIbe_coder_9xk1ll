"""Per-tag mastery: what the player scores, kept apart from what they write.

T4 W1. The model is arithmetic over a small amount of state, so it is testable
without a sandbox, a level or a profile on disk -- which is the same argument
`fight.py` makes and for the same reason.

The update rule is W3 and is deliberately absent here: W1 is the container and
what can be honestly read out of it.
"""

import unittest

from vibecoder.mastery import (
    ALPHA,
    MIN_OBSERVATIONS,
    UNSEEN,
    Mastery,
    TagMastery,
    observation,
)


class TestAnEstimateCarriesItsEvidence(unittest.TestCase):
    """`value` on its own cannot be read honestly, so nothing exposes it alone."""

    def test_an_untouched_tag_sits_in_the_middle(self):
        """Not at zero. An unplayed tag is unknown, not bad, and starting at
        zero would tell a new player they are weak at everything on the
        evidence of nothing."""
        self.assertEqual(TagMastery().value, UNSEEN)

    def test_an_untouched_tag_is_not_seen(self):
        """The distinction the whole type exists for: 0.5 after four runs is a
        measurement, 0.5 after none is the absence of one."""
        self.assertFalse(TagMastery().seen)
        self.assertTrue(TagMastery(value=UNSEEN, observations=1).seen)

    def test_confidence_needs_the_minimum_observation_count(self):
        """T4's tag-sparsity hazard: several tags have exactly one level, so a
        single lucky run must not be allowed to steer content."""
        self.assertFalse(TagMastery(observations=MIN_OBSERVATIONS - 1).confident)
        self.assertTrue(TagMastery(observations=MIN_OBSERVATIONS).confident)

    def test_a_hand_edited_value_is_clamped(self):
        """The profile is a JSON file the player is invited to inspect, so an
        out-of-range value is an input, not an impossibility."""
        self.assertEqual(TagMastery(value=7.0).value, 1.0)
        self.assertEqual(TagMastery(value=-7.0).value, 0.0)

    def test_a_negative_observation_count_is_clamped(self):
        self.assertEqual(TagMastery(observations=-4).observations, 0)

    def test_a_tag_round_trips_through_json(self):
        entry = TagMastery(value=0.25, observations=6, updated_at="2026-09-08T00:00:00+00:00")
        self.assertEqual(TagMastery.from_json(entry.to_json()), entry)

    def test_an_unrecognised_field_is_dropped_rather_than_raising(self):
        entry = TagMastery.from_json({"value": 0.3, "from_the_future": 1})
        self.assertEqual(entry.value, 0.3)


class TestReadingIsTotal(unittest.TestCase):
    """Asking about a tag never invents an entry, so "have I seen this tag"
    stays answerable."""

    def setUp(self):
        self.mastery = Mastery.from_json({
            "recursion": {"value": 0.2, "observations": 5},
            "data": {"value": 0.9, "observations": 1},
            "loops": {"value": 0.6, "observations": 4},
        })

    def test_an_absent_tag_reads_as_unseen(self):
        self.assertEqual(self.mastery.value("nothing_here"), UNSEEN)
        self.assertFalse(self.mastery["nothing_here"].seen)

    def test_reading_an_absent_tag_does_not_store_it(self):
        before = len(self.mastery)
        self.mastery.value("nothing_here")
        self.mastery["nothing_here"]
        self.assertEqual(len(self.mastery), before)

    def test_known_tags_are_weakest_first(self):
        self.assertEqual(self.mastery.known_tags(), ["recursion", "loops", "data"])

    def test_confident_tags_exclude_the_thinly_evidenced(self):
        """`data` sits at 0.9 on one run. It is the strongest number present
        and must not be acted on."""
        self.assertIn("data", self.mastery.known_tags())
        self.assertNotIn("data", self.mastery.confident_tags())

    def test_ties_break_on_the_tag_name_so_the_order_is_stable(self):
        mastery = Mastery.from_json({
            "zebra": {"value": 0.5, "observations": 3},
            "alpha": {"value": 0.5, "observations": 3},
        })
        self.assertEqual(mastery.known_tags(), ["alpha", "zebra"])

    def test_an_empty_model_reads_cleanly(self):
        empty = Mastery()
        self.assertEqual(empty.known_tags(), [])
        self.assertEqual(empty.confident_tags(), [])
        self.assertEqual(empty.value("anything"), UNSEEN)


class TestSerialisation(unittest.TestCase):
    def test_a_model_round_trips(self):
        mastery = Mastery.from_json({"loops": {"value": 0.4, "observations": 2}})
        again = Mastery.from_json(mastery.to_json())
        self.assertEqual(again.value("loops"), 0.4)
        self.assertEqual(again["loops"].observations, 2)

    def test_junk_in_the_profile_does_not_raise(self):
        """A hand-edited profile is an input. Losing the tag is acceptable;
        refusing to start the game is not."""
        self.assertEqual(len(Mastery.from_json({"loops": "not a dict"})), 0)
        self.assertEqual(len(Mastery.from_json("not a dict")), 0)
        self.assertEqual(len(Mastery.from_json({})), 0)

    def test_tags_are_written_in_a_stable_order(self):
        """The profile is meant to be diffable by hand."""
        mastery = Mastery.from_json({
            "zebra": {"value": 0.5}, "alpha": {"value": 0.5},
        })
        self.assertEqual(list(mastery.to_json()), ["alpha", "zebra"])


class TestTheObservation(unittest.TestCase):
    """One run reduced to a 0..1 competence signal. T4 W3."""

    def test_a_perfect_first_try_run_observes_as_one(self):
        self.assertEqual(observation(100.0, 100.0, True), 1.0)

    def test_a_run_that_did_nothing_right_observes_as_zero(self):
        self.assertEqual(observation(0.0, 0.0, False), 0.0)

    def test_accuracy_carries_the_most_weight(self):
        """A wrong answer is not competence, whatever else it did well."""
        accurate = observation(100.0, 0.0, False)
        efficient = observation(0.0, 100.0, False)
        self.assertGreater(accurate, efficient)

    def test_first_try_is_a_bonus_rather_than_a_third_of_the_score(self):
        """It is the noisiest of the three and the easiest to game."""
        self.assertAlmostEqual(
            observation(100.0, 100.0, True) - observation(100.0, 100.0, False),
            0.2,
        )

    def test_speed_is_not_an_input(self):
        """Deliberate: solve time measures a session, not a competence. A
        player interrupted by a phone call is not worse at recursion. The
        signature is the assertion -- there is nowhere to pass it."""
        import inspect

        self.assertNotIn("speed", inspect.signature(observation).parameters)

    def test_an_out_of_range_axis_is_clamped(self):
        self.assertEqual(observation(1000.0, 1000.0, True), 1.0)
        self.assertEqual(observation(-50.0, -50.0, False), 0.0)


class TestTheUpdateRule(unittest.TestCase):
    """T4 W3, and exit criterion 2: mastery rises after clears and falls
    after failures."""

    def test_a_good_run_raises_every_tag_on_the_level(self):
        mastery = Mastery()
        mastery.observe(("data", "loops"), 1.0)
        self.assertGreater(mastery.value("data"), UNSEEN)
        self.assertGreater(mastery.value("loops"), UNSEEN)

    def test_a_bad_run_lowers_it(self):
        mastery = Mastery()
        mastery.observe(("data",), 0.0)
        self.assertLess(mastery.value("data"), UNSEEN)

    def test_the_move_is_a_fraction_of_the_gap(self):
        """Exponentially weighted, so recent evidence dominates without one
        run erasing history."""
        mastery = Mastery()
        moved = mastery.observe(("data",), 1.0)
        self.assertAlmostEqual(moved["data"], ALPHA * (1.0 - UNSEEN))

    def test_a_single_run_cannot_reach_either_extreme(self):
        """The first hazard is a death spiral in either direction, and a
        bounded step is what makes one unreachable in a single level."""
        high, low = Mastery(), Mastery()
        high.observe(("t",), 1.0)
        low.observe(("t",), 0.0)
        self.assertLess(high.value("t"), 1.0)
        self.assertGreater(low.value("t"), 0.0)

    def test_repeated_good_runs_converge_upward_monotonically(self):
        """Criterion 2: monotone in the absence of contrary evidence."""
        mastery = Mastery()
        values = []
        for _ in range(20):
            mastery.observe(("t",), 1.0)
            values.append(mastery.value("t"))
        self.assertEqual(values, sorted(values))
        self.assertGreater(values[-1], 0.99)

    def test_repeated_bad_runs_converge_downward_monotonically(self):
        mastery = Mastery()
        values = []
        for _ in range(20):
            mastery.observe(("t",), 0.0)
            values.append(mastery.value("t"))
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertLess(values[-1], 0.01)

    def test_an_observation_counts_even_when_the_value_does_not_move(self):
        """A run that lands exactly on the estimate is still evidence, and
        `confident` is counting evidence rather than movement."""
        mastery = Mastery()
        mastery.observe(("t",), UNSEEN)
        self.assertEqual(mastery.value("t"), UNSEEN)
        self.assertEqual(mastery["t"].observations, 1)

    def test_enough_runs_make_a_tag_confident(self):
        mastery = Mastery()
        for _ in range(MIN_OBSERVATIONS):
            mastery.observe(("t",), 0.7)
        self.assertTrue(mastery.confident("t"))

    def test_the_timestamp_is_recorded_when_given(self):
        """W6's decay needs to know when the evidence was gathered."""
        mastery = Mastery()
        mastery.observe(("t",), 0.7, at="2026-09-08T00:00:00+00:00")
        self.assertEqual(mastery["t"].updated_at, "2026-09-08T00:00:00+00:00")

    def test_observing_no_tags_changes_nothing(self):
        """An untagged level is a level-authoring gap, not a crash."""
        mastery = Mastery()
        self.assertEqual(mastery.observe((), 1.0), {})
        self.assertEqual(len(mastery), 0)

    def test_an_out_of_range_observation_is_clamped(self):
        mastery = Mastery()
        mastery.observe(("t",), 40.0)
        self.assertLessEqual(mastery.value("t"), 1.0)

    def test_the_deltas_returned_match_what_actually_moved(self):
        """W7 forbids hidden state: the caller must be able to explain the
        update without recomputing it."""
        mastery = Mastery()
        before = mastery.value("t")
        moved = mastery.observe(("t",), 1.0)
        self.assertAlmostEqual(mastery.value("t") - before, moved["t"], places=5)


if __name__ == "__main__":
    unittest.main()
