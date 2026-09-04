"""Contract tests every level must satisfy.

These run against the whole registry, so a newly added level is covered the
moment its file lands. The expensive one is
``test_every_reference_solves_every_variant`` -- it is also the one that stops
a broken level from shipping.
"""

import unittest

from vibecoder import style
from vibecoder.levels import all_levels, get_level, worlds
from vibecoder.models import Source
from vibecoder.runner import run_code

VARIANT_SEEDS = (1, 2, 3, 7)


class TestRegistry(unittest.TestCase):
    def test_levels_are_discovered(self):
        self.assertGreaterEqual(len(all_levels()), 6)

    def test_ids_are_unique(self):
        ids = [level.id for level in all_levels()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_levels_sort_into_campaign_order(self):
        ordered = [(lvl.world, lvl.index) for lvl in all_levels()]
        self.assertEqual(ordered, sorted(ordered))

    def test_lookup_by_id(self):
        level = get_level("w1-l1-greet")
        self.assertEqual(level.func_name, "greet")

    def test_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            get_level("no-such-level")

    def test_worlds_group_their_levels(self):
        grouped = worlds()
        self.assertIn(1, grouped)
        self.assertTrue(all(lvl.world == 1 for lvl in grouped[1]))

    def test_multiplier_grows_with_world(self):
        """World 1 is the beginner on-ramp, so it sits at the 1.0 baseline.

        An easier level must never be worth *less* than a harder one, which is
        why the beginner world was numbered 1 and the existing worlds moved up
        rather than a world 0 being added below the multiplier's floor.
        """
        self.assertAlmostEqual(get_level("w1-l1-greet").multiplier, 1.0)
        self.assertAlmostEqual(get_level("w2-l1-revenue").multiplier, 1.1)
        self.assertAlmostEqual(get_level("w3-l1-flatten").multiplier, 1.2)


class TestLevelMetadata(unittest.TestCase):
    def test_every_level_is_well_formed(self):
        for level in all_levels():
            with self.subTest(level=level.id):
                self.assertTrue(level.title)
                self.assertGreater(len(level.brief), 40, "brief must explain the task")
                self.assertGreater(level.par_seconds, 0)
                self.assertTrue(level.tags, "tags drive vibe recommendation")
                self.assertIn(f"def {level.func_name}", level.starter)
                self.assertIn(f"def {level.func_name}", level.reference)

    def test_declared_style_goals_exist(self):
        for level in all_levels():
            for goal in level.style_goals:
                with self.subTest(level=level.id, goal=goal):
                    self.assertIn(goal, style.CHECKERS)
                    self.assertIn(goal, style.DESCRIPTIONS)

    def test_the_starter_is_not_already_the_answer(self):
        """A starter that passes would hand out a free three stars."""
        for level in all_levels():
            with self.subTest(level=level.id):
                result = run_code(
                    level.starter, level.func_name, level.tests_for(1),
                    source=Source.BUNDLED,
                )
                self.assertFalse(
                    result.all_passed,
                    f"{level.id}: the starter template passes its own tests",
                )


class TestVariants(unittest.TestCase):
    def test_a_seed_reproduces_its_variant_exactly(self):
        for level in all_levels():
            with self.subTest(level=level.id):
                first = [t.to_json() for t in level.tests_for(5)]
                second = [t.to_json() for t in level.tests_for(5)]
                self.assertEqual(first, second)

    def test_different_seeds_give_different_data(self):
        """Otherwise replaying a level is not a new challenge."""
        for level in all_levels():
            with self.subTest(level=level.id):
                one = [t.to_json() for t in level.tests_for(1)]
                two = [t.to_json() for t in level.tests_for(2)]
                self.assertNotEqual(one, two, f"{level.id}: variants are identical")

    def test_every_variant_has_edge_cases(self):
        for level in all_levels():
            with self.subTest(level=level.id):
                self.assertGreaterEqual(len(level.tests_for(1)), 4)


class TestReferenceSolutions(unittest.TestCase):
    def test_every_reference_solves_every_variant(self):
        for level in all_levels():
            for seed in VARIANT_SEEDS:
                with self.subTest(level=level.id, seed=seed):
                    result = run_code(
                        level.reference, level.func_name,
                        level.tests_for(seed), source=Source.BUNDLED,
                    )
                    self.assertFalse(result.fatal, result.error)
                    failed = [o.name for o in result.outcomes if not o.passed]
                    self.assertTrue(
                        result.all_passed,
                        f"{level.id} seed {seed} failed: {failed}",
                    )

    def test_every_reference_meets_its_own_style_goals(self):
        """A goal the reference cannot satisfy is a goal no player can."""
        for level in all_levels():
            with self.subTest(level=level.id):
                results = style.evaluate(
                    level.reference, level.func_name, level.style_goals
                )
                unmet = [goal for goal, met in results.items() if not met]
                self.assertFalse(unmet, f"{level.id}: reference misses {unmet}")


if __name__ == "__main__":
    unittest.main()


class TestHints(unittest.TestCase):
    """The hint ladder is the beginner's substitute for a person to ask."""

    def beginners(self):
        return [lvl for lvl in all_levels() if lvl.world == 1]

    def test_every_beginner_level_offers_hints(self):
        for level in self.beginners():
            with self.subTest(level=level.id):
                self.assertTrue(level.hints, "a beginner level needs hints")

    def test_the_first_attempt_earns_nothing(self):
        """Being stuck briefly is the part of the exercise that teaches."""
        for level in self.beginners():
            with self.subTest(level=level.id):
                self.assertEqual(level.hints_after(0), [])
                self.assertEqual(level.hints_after(1), [])

    def test_hints_arrive_one_per_failure(self):
        level = get_level("w1-l6-tally")
        self.assertEqual(len(level.hints_after(2)), 1)
        self.assertEqual(len(level.hints_after(3)), 2)
        self.assertEqual(len(level.hints_after(4)), 3)

    def test_the_ladder_never_exceeds_what_the_level_wrote(self):
        for level in self.beginners():
            with self.subTest(level=level.id):
                self.assertEqual(
                    len(level.hints_after(500)), len(level.hints)
                )

    def test_earlier_hints_are_kept_as_later_ones_arrive(self):
        """The sequence is the teaching, so it is reprinted whole."""
        level = get_level("w1-l3-count")
        self.assertEqual(level.hints_after(3)[0], level.hints_after(2)[0])

    def test_a_level_without_hints_is_still_valid(self):
        """Hints are optional; the later worlds declare none."""
        later = [lvl for lvl in all_levels() if lvl.world > 1]
        self.assertTrue(later)
        for level in later:
            with self.subTest(level=level.id):
                self.assertEqual(level.hints_after(9), [])

    def test_no_hint_simply_hands_over_the_reference(self):
        """A hint may show the shape of the answer, not paste the solution."""
        for level in self.beginners():
            body = [
                line.strip()
                for line in level.reference.splitlines()
                if line.strip() and not line.strip().startswith("def ")
            ]
            for hint in level.hints:
                with self.subTest(level=level.id, hint=hint[:40]):
                    self.assertFalse(
                        any(line == hint.strip() for line in body),
                        "a hint is the whole reference line verbatim",
                    )
