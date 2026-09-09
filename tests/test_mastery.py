"""Per-tag mastery: what the player scores, kept apart from what they write.

T4 W1. The model is arithmetic over a small amount of state, so it is testable
without a sandbox, a level or a profile on disk -- which is the same argument
`fight.py` makes and for the same reason.

The update rule is W3 and is deliberately absent here: W1 is the container and
what can be honestly read out of it.
"""

import unittest
from datetime import datetime, timedelta, timezone

from vibecoder.mastery import (
    ALPHA,
    HALF_LIFE_DAYS,
    MIN_OBSERVATIONS,
    UNSEEN,
    Mastery,
    TagMastery,
    observation,
    remaining_force,
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


BASE = datetime(2026, 6, 1, tzinfo=timezone.utc)


def stamp(days: float = 0.0) -> str:
    return (BASE + timedelta(days=days)).isoformat(timespec="seconds")


class TestRemainingForce(unittest.TestCase):
    """T4 W6. How much of an estimate survives being old."""

    def test_nothing_has_aged_at_zero_days(self):
        self.assertEqual(remaining_force(0.0), 1.0)

    def test_half_is_gone_after_one_half_life(self):
        self.assertAlmostEqual(remaining_force(HALF_LIFE_DAYS), 0.5)

    def test_a_quarter_survives_two_half_lives(self):
        self.assertAlmostEqual(remaining_force(2 * HALF_LIFE_DAYS), 0.25)

    def test_it_never_reaches_zero(self):
        """A half-life rather than a ramp, because there is no age at which
        evidence becomes worthless and a linear decay has to invent one."""
        self.assertGreater(remaining_force(3650.0), 0.0)

    def test_a_negative_age_decays_nothing(self):
        """A clock that went backwards is not a reason to forget anything."""
        self.assertEqual(remaining_force(-30.0), 1.0)

    def test_it_is_monotone(self):
        forces = [remaining_force(days) for days in range(0, 120, 7)]
        self.assertEqual(forces, sorted(forces, reverse=True))


class TestDecayingAnEstimate(unittest.TestCase):
    def entry(self, value: float, observations: int = 6) -> TagMastery:
        return TagMastery(value=value, observations=observations,
                          updated_at=stamp(0))

    def test_a_strong_estimate_drifts_down_toward_the_middle(self):
        aged = self.entry(0.9).as_of(stamp(HALF_LIFE_DAYS))
        self.assertLess(aged.value, 0.9)
        self.assertGreater(aged.value, UNSEEN)

    def test_a_weak_estimate_drifts_up_toward_the_middle(self):
        """Toward the middle, not toward zero. Age makes a rating unknown,
        not bad."""
        aged = self.entry(0.1).as_of(stamp(HALF_LIFE_DAYS))
        self.assertGreater(aged.value, 0.1)
        self.assertLess(aged.value, UNSEEN)

    def test_an_estimate_at_the_middle_does_not_move(self):
        self.assertEqual(self.entry(UNSEEN).as_of(stamp(365)).value, UNSEEN)

    def test_the_observation_count_erodes_too(self):
        """The half that matters: staleness has to reach `confident`, or a
        returning player reads as measured-and-mediocre rather than
        unmeasured (Q90)."""
        aged = self.entry(0.9, observations=6).as_of(stamp(2 * HALF_LIFE_DAYS))
        self.assertLess(aged.observations, 6)

    def test_a_long_absence_costs_confidence(self):
        fresh = self.entry(0.2, observations=6)
        self.assertTrue(fresh.confident)
        self.assertFalse(fresh.as_of(stamp(60)).confident)

    def test_decay_does_not_mutate_the_stored_estimate(self):
        """The profile is a record of what was measured, not one that rots on
        disk. Decay is how it is read."""
        entry = self.entry(0.9)
        entry.as_of(stamp(365))
        self.assertEqual(entry.value, 0.9)
        self.assertEqual(entry.observations, 6)

    def test_reading_at_the_same_moment_changes_nothing(self):
        entry = self.entry(0.9)
        self.assertEqual(entry.as_of(stamp(0)), entry)

    def test_an_entry_never_updated_does_not_decay(self):
        """No timestamp means nothing is known about when, and guessing
        "ancient" would silently erase a profile written before W1."""
        entry = TagMastery(value=0.9, observations=6, updated_at="")
        self.assertEqual(entry.as_of(stamp(365)), entry)

    def test_an_unparseable_timestamp_decays_nothing(self):
        """The profile is a file the player may edit. A mangled stamp should
        cost a re-assessment, not the ability to start the game."""
        entry = TagMastery(value=0.9, observations=6, updated_at="last tuesday")
        self.assertEqual(entry.as_of(stamp(365)), entry)
        self.assertEqual(self.entry(0.9).as_of("whenever"), self.entry(0.9))

    def test_a_naive_timestamp_decays_nothing(self):
        """Comparing an aware stamp with a naive one raises; refusing to
        decay is the recoverable answer."""
        entry = TagMastery(value=0.9, observations=6,
                           updated_at="2026-06-01T00:00:00")
        self.assertEqual(entry.as_of(stamp(365)), entry)

    def test_a_single_observation_survives_a_day(self):
        """M55. `int()` truncation sent one run to zero after half a day --
        1 x 0.97 truncates to 0 -- so a tag played once stopped existing
        overnight and reappeared in the player's "never measured" list."""
        entry = TagMastery(value=0.6, observations=1, updated_at=stamp(0))
        self.assertTrue(entry.as_of(stamp(1)).seen)
        self.assertTrue(entry.as_of(stamp(10)).seen)

    def test_a_single_observation_does_expire_eventually(self):
        """The paired negative: rounding must not make one run immortal."""
        entry = TagMastery(value=0.6, observations=1, updated_at=stamp(0))
        self.assertFalse(entry.as_of(stamp(2 * HALF_LIFE_DAYS)).seen)

    def test_a_confident_tag_still_loses_confidence_on_schedule(self):
        """Rounding must not have moved W6's documented behaviour: six weeks
        away and the game stops assuming."""
        entry = TagMastery(value=0.9, observations=6, updated_at=stamp(0))
        self.assertTrue(entry.as_of(stamp(HALF_LIFE_DAYS)).confident)
        self.assertFalse(entry.as_of(stamp(2 * HALF_LIFE_DAYS)).confident)

    def test_more_time_means_more_decay(self):
        values = [self.entry(0.9).as_of(stamp(days)).value
                  for days in range(0, 200, 10)]
        self.assertEqual(values, sorted(values, reverse=True))


class TestDecayingTheWholeModel(unittest.TestCase):
    def model(self) -> Mastery:
        return Mastery(tags={
            "fresh": TagMastery(value=0.9, observations=6, updated_at=stamp(60)),
            "stale": TagMastery(value=0.9, observations=6, updated_at=stamp(0)),
        })

    def test_only_the_stale_tag_moves(self):
        aged = self.model().as_of(stamp(60))
        self.assertEqual(aged.value("fresh"), 0.9)
        self.assertLess(aged.value("stale"), 0.9)

    def test_the_view_does_not_mutate_the_model(self):
        model = self.model()
        model.as_of(stamp(365))
        self.assertEqual(model.value("stale"), 0.9)

    def test_an_empty_now_is_the_identity(self):
        """Every existing caller passes nothing and must be unaffected."""
        model = self.model()
        self.assertIs(model.as_of(""), model)

    def test_decay_can_reorder_which_tag_is_weakest(self):
        """The point of the view: decisions are made against it, so it has to
        be able to change one."""
        model = Mastery(tags={
            "old_weak": TagMastery(value=0.2, observations=9, updated_at=stamp(0)),
            "new_mid": TagMastery(value=0.4, observations=9, updated_at=stamp(90)),
        })
        self.assertEqual(model.known_tags()[0], "old_weak")
        self.assertEqual(model.as_of(stamp(90)).known_tags()[0], "new_mid")


class TestObservingAfterAnAbsence(unittest.TestCase):
    def test_a_returning_player_moves_from_where_they_decayed_to(self):
        """Not from the rating they left behind two months ago."""
        mastery = Mastery(tags={
            "t": TagMastery(value=0.95, observations=9, updated_at=stamp(0))
        })
        mastery.observe(("t",), 0.5, at=stamp(90))
        # Had decay been skipped the value would still be near 0.95 - alpha
        # times the gap, which is about 0.81.
        self.assertLess(mastery.value("t"), 0.7)

    def test_the_decay_is_written_back_when_a_run_supersedes_it(self):
        mastery = Mastery(tags={
            "t": TagMastery(value=0.95, observations=9, updated_at=stamp(0))
        })
        mastery.observe(("t",), 0.5, at=stamp(90))
        self.assertLess(mastery["t"].observations, 10)

    def test_observing_without_a_timestamp_does_not_decay(self):
        mastery = Mastery(tags={
            "t": TagMastery(value=0.95, observations=9, updated_at=stamp(0))
        })
        mastery.observe(("t",), 0.95)
        self.assertEqual(mastery["t"].observations, 10)


if __name__ == "__main__":
    unittest.main()
