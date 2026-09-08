"""Variant difficulty: the dial, and the promise that the default did not move.

T4 W2. Difficulty selects variant *parameters* -- input size, edge-case
density -- never a different problem. Level authors opt in one at a time and
the old one-argument `make_tests` keeps working, so most of what is pinned
here is that opting in changed nothing for anyone who did not.
"""

import unittest

from vibecoder.levels import all_bosses, all_levels, get_level
from vibecoder.models import (
    DEFAULT_DIFFICULTY,
    Difficulty,
    accepts_difficulty,
    generate_tests,
)

#: The level the trajectory names as the worked example, and the first to opt in.
OPTED_IN = "w2-l2-groupby"
SEEDS = (1, 2, 3)


class TestTheDial(unittest.TestCase):
    def test_the_default_is_the_middle(self):
        self.assertEqual(DEFAULT_DIFFICULTY.level, 0.5)

    def test_a_value_out_of_range_is_clamped(self):
        """Difficulty is derived from a mastery estimate a player can
        hand-edit, and a generator asked for a negative row count crashes."""
        self.assertEqual(Difficulty(9.0).level, 1.0)
        self.assertEqual(Difficulty(-9.0).level, 0.0)

    def test_scale_hits_both_ends_and_the_middle(self):
        self.assertEqual(Difficulty(0.0).scale(12, 28), 12)
        self.assertEqual(Difficulty(0.5).scale(12, 28), 20)
        self.assertEqual(Difficulty(1.0).scale(12, 28), 28)

    def test_integer_ends_give_an_integer_back(self):
        """Row counts drive `rng` draw sequences; a float would round
        differently somewhere else and desynchronise a variant."""
        self.assertIsInstance(Difficulty(0.37).scale(10, 90), int)

    def test_float_ends_give_a_float_back(self):
        self.assertIsInstance(Difficulty(0.37).scale(0.1, 0.9), float)

    def test_scale_is_monotonic(self):
        values = [Difficulty(i / 10).scale(5, 500) for i in range(11)]
        self.assertEqual(values, sorted(values))

    def test_a_reversed_range_still_interpolates(self):
        """An author may want *fewer* of something as difficulty rises."""
        self.assertEqual(Difficulty(0.0).scale(100, 10), 100)
        self.assertEqual(Difficulty(1.0).scale(100, 10), 10)

    def test_the_band_names_the_dial_rather_than_numbering_it(self):
        """W7 has to explain a decision in a sentence, and "you are on 0.62"
        explains nothing."""
        self.assertEqual(Difficulty(0.0).band, "gentle")
        self.assertEqual(Difficulty(0.5).band, "standard")
        self.assertEqual(Difficulty(1.0).band, "hard")

    def test_difficulty_is_frozen(self):
        with self.assertRaises(Exception):
            Difficulty(0.5).level = 0.9


class TestOptingIn(unittest.TestCase):
    def test_a_one_argument_generator_has_not_opted_in(self):
        self.assertFalse(accepts_difficulty(lambda rng: []))

    def test_a_two_argument_generator_has(self):
        self.assertTrue(accepts_difficulty(lambda rng, difficulty: []))

    def test_a_var_positional_generator_has(self):
        self.assertTrue(accepts_difficulty(lambda rng, *rest: []))

    def test_a_keyword_only_second_parameter_has_not(self):
        """Positional is the contract. A keyword-only parameter named
        `difficulty` is the author's own business."""
        self.assertFalse(accepts_difficulty(lambda rng, *, difficulty=None: []))

    def test_an_uninspectable_callable_is_treated_as_not_opted_in(self):
        """Better a level that ignores difficulty than one that will not load."""
        self.assertFalse(accepts_difficulty(len))

    def test_a_generator_that_did_not_opt_in_is_called_the_old_way(self):
        seen = []
        generate_tests(lambda rng: seen.append("one arg") or [], 1, Difficulty(1.0))
        self.assertEqual(seen, ["one arg"])

    def test_a_generator_that_opted_in_gets_the_default_when_none_is_given(self):
        seen = []
        generate_tests(lambda rng, d: seen.append(d) or [], 1, None)
        self.assertEqual(seen, [DEFAULT_DIFFICULTY])


class TestTheDefaultDidNotMove(unittest.TestCase):
    """The baseline guarantee, and the reason it is a test rather than a note.

    Every op count in `data/baselines/` was measured with no difficulty
    parameter at all. A level that shifted under the default would turn those
    files from evidence into decoration, silently, and `test_records` would
    only notice for levels whose reference ops happened to change.
    """

    def cases(self, level_id, difficulty=None):
        level = get_level(level_id)
        return [
            [case.to_json() for case in level.tests_for(seed, difficulty)]
            for seed in SEEDS
        ]

    def test_the_opted_in_level_is_identical_at_the_default(self):
        self.assertEqual(self.cases(OPTED_IN), self.cases(OPTED_IN, DEFAULT_DIFFICULTY))

    def test_every_level_is_identical_at_the_default(self):
        for level in all_levels():
            with self.subTest(level=level.id):
                self.assertEqual(
                    self.cases(level.id), self.cases(level.id, DEFAULT_DIFFICULTY)
                )

    def test_a_level_that_did_not_opt_in_ignores_difficulty_entirely(self):
        for level in all_levels():
            if accepts_difficulty(level.make_tests):
                continue
            with self.subTest(level=level.id):
                self.assertEqual(
                    self.cases(level.id, Difficulty(0.0)),
                    self.cases(level.id, Difficulty(1.0)),
                )

    def test_every_boss_step_is_identical_at_the_default(self):
        for boss in all_bosses():
            for step in boss.steps:
                with self.subTest(boss=boss.id, step=step.id):
                    plain = [c.to_json() for c in step.tests_for(1)]
                    defaulted = [
                        c.to_json() for c in step.tests_for(1, DEFAULT_DIFFICULTY)
                    ]
                    self.assertEqual(plain, defaulted)


class TestTheDialActuallyMovesTheVariant(unittest.TestCase):
    """Exit criterion 1's precursor: opting in has to change something."""

    def rows(self, level_of_difficulty):
        cases = get_level(OPTED_IN).tests_for(1, Difficulty(level_of_difficulty))
        generated = [c for c in cases if c.name.startswith("random_")]
        rows = [row for case in generated for row in case.args[0]]
        return rows

    def test_a_harder_variant_has_more_rows(self):
        self.assertLess(len(self.rows(0.0)), len(self.rows(1.0)))

    def test_a_harder_variant_has_a_denser_edge_case(self):
        """More `None` amounts, proportionally -- not merely more rows."""
        def density(level):
            rows = self.rows(level)
            return sum(1 for r in rows if r["amount"] is None) / len(rows)

        self.assertLess(density(0.0), density(1.0))

    def test_row_count_never_decreases_as_difficulty_rises(self):
        counts = [len(self.rows(i / 10)) for i in range(11)]
        self.assertEqual(counts, sorted(counts))

    def test_the_hand_written_edge_cases_are_present_at_every_difficulty(self):
        """Difficulty tunes the generated variants. It must not be able to
        remove the cases an author wrote by hand -- those are the level's
        actual contract."""
        for level_of_difficulty in (0.0, 0.5, 1.0):
            with self.subTest(difficulty=level_of_difficulty):
                names = {
                    c.name for c in
                    get_level(OPTED_IN).tests_for(1, Difficulty(level_of_difficulty))
                }
                self.assertLessEqual(
                    {"empty", "single_region", "all_amounts_missing"}, names
                )

    def test_a_seed_still_reproduces_its_variant_at_a_given_difficulty(self):
        for level_of_difficulty in (0.0, 0.5, 1.0):
            with self.subTest(difficulty=level_of_difficulty):
                difficulty = Difficulty(level_of_difficulty)
                first = [c.to_json() for c in get_level(OPTED_IN).tests_for(2, difficulty)]
                again = [c.to_json() for c in get_level(OPTED_IN).tests_for(2, difficulty)]
                self.assertEqual(first, again)


if __name__ == "__main__":
    unittest.main()
