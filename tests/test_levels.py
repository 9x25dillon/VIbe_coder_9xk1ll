"""Contract tests every level must satisfy.

These run against the whole registry, so a newly added level is covered the
moment its file lands. The expensive one is
``test_every_reference_solves_every_variant`` -- it is also the one that stops
a broken level from shipping.
"""

import unittest

from vibecoder import style
from vibecoder.levels import all_levels, get_level, worlds
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
        level = get_level("w1-l1-revenue")
        self.assertEqual(level.func_name, "total_revenue")

    def test_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            get_level("no-such-level")

    def test_worlds_group_their_levels(self):
        grouped = worlds()
        self.assertIn(1, grouped)
        self.assertTrue(all(lvl.world == 1 for lvl in grouped[1]))

    def test_multiplier_grows_with_world(self):
        self.assertAlmostEqual(get_level("w1-l1-revenue").multiplier, 1.0)
        self.assertAlmostEqual(get_level("w2-l1-flatten").multiplier, 1.1)


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
                    level.starter, level.func_name, level.tests_for(1)
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
                        level.reference, level.func_name, level.tests_for(seed)
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
