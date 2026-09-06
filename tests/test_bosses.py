"""The boss contract (T3 W1).

Mirrors `test_levels` for the multi-step shape, plus the things only a boss can
get wrong: steps that do not link, a step whose function name collides with an
earlier one, and a "linked" step whose reference does not actually use what it
claims to build on.

Contract tests prove a boss is well-formed. Only playing it says whether it is
any good.
"""

import ast
import unittest

from vibecoder.levels import all_bosses, get_boss
from vibecoder.models import BossLevel, BossStep, Source, TestCase
from vibecoder.runner import run_code

SEEDS = (1, 2, 3)


def _step(**overrides) -> BossStep:
    base = dict(
        id="one", title="One", brief="b", func_name="f",
        starter="def f():\n    return 0\n",
        reference="def f():\n    return 1\n",
        make_tests=lambda rng: [TestCase("t", [], expected=1)],
    )
    base.update(overrides)
    return BossStep(**base)


def _boss(**overrides) -> BossLevel:
    base = dict(
        id="b", world=1, world_title="W", index=1, title="T", brief="b",
        steps=(_step(), _step(id="two", func_name="g")),
    )
    base.update(overrides)
    return BossLevel(**base)


class TestRegistry(unittest.TestCase):
    def test_bosses_are_discovered(self):
        self.assertTrue(all_bosses())

    def test_ids_are_unique(self):
        ids = [boss.id for boss in all_bosses()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_lookup_by_id(self):
        boss = all_bosses()[0]
        self.assertIs(get_boss(boss.id), boss)

    def test_unknown_id_raises(self):
        with self.assertRaises(KeyError):
            get_boss("no-such-boss")

    def test_a_boss_is_not_returned_as_an_ordinary_level(self):
        """The two shapes are kept apart so no caller has to ask which it has."""
        from vibecoder.levels import all_levels

        boss_ids = {boss.id for boss in all_bosses()}
        self.assertFalse(boss_ids & {level.id for level in all_levels()})


class TestTheShapeIsEnforced(unittest.TestCase):
    def test_a_boss_needs_at_least_two_steps(self):
        """One step is a level. The format exists for the linking."""
        with self.assertRaises(ValueError):
            _boss(steps=(_step(),))

    def test_duplicate_step_ids_are_refused(self):
        with self.assertRaises(ValueError):
            _boss(steps=(_step(), _step(func_name="g")))

    def test_two_steps_may_not_share_a_function_name(self):
        """The later definition would silently replace the earlier one in the
        shared file, so the first step's tests would grade code written for
        the second."""
        with self.assertRaises(ValueError) as caught:
            _boss(steps=(_step(), _step(id="two")))
        self.assertIn("function name", str(caught.exception))

    def test_index_of_finds_a_step(self):
        boss = _boss()
        self.assertEqual(boss.index_of("two"), 1)

    def test_index_of_rejects_an_unknown_step(self):
        with self.assertRaises(KeyError):
            _boss().index_of("nope")


class TestMetadata(unittest.TestCase):
    def test_every_boss_is_well_formed(self):
        for boss in all_bosses():
            with self.subTest(boss=boss.id):
                self.assertTrue(boss.id and boss.title and boss.brief)
                self.assertGreaterEqual(boss.step_count, 2)
                self.assertGreater(boss.par_seconds, 0)
                self.assertIs(boss.source, Source.BUNDLED)

    def test_every_step_is_well_formed(self):
        for boss in all_bosses():
            for step in boss.steps:
                with self.subTest(boss=boss.id, step=step.id):
                    self.assertTrue(step.id and step.title and step.brief)
                    self.assertTrue(step.func_name.isidentifier())
                    self.assertIn(f"def {step.func_name}", step.starter)
                    self.assertIn(f"def {step.func_name}", step.reference)

    def test_every_step_has_enough_test_cases(self):
        """Four is the level minimum and a boss step is no easier to grade."""
        for boss in all_bosses():
            for step in boss.steps:
                with self.subTest(boss=boss.id, step=step.id):
                    self.assertGreaterEqual(len(step.tests_for(1)), 4)

    def test_every_step_has_a_hand_written_edge_case(self):
        for boss in all_bosses():
            for step in boss.steps:
                with self.subTest(boss=boss.id, step=step.id):
                    names = {case.name for case in step.tests_for(1)}
                    self.assertTrue(
                        names & {"empty_input", "single_row", "nothing_qualifies",
                                 "boundary_is_kept", "worked_example"},
                        names,
                    )

    def test_declared_style_goals_exist(self):
        from vibecoder import style

        for boss in all_bosses():
            for step in boss.steps:
                for goal in step.style_goals:
                    with self.subTest(boss=boss.id, step=step.id, goal=goal):
                        self.assertIn(goal, style.CHECKERS)
                        self.assertIn(goal, style.DESCRIPTIONS)


class TestVariants(unittest.TestCase):
    def test_a_seed_reproduces_its_step_exactly(self):
        for boss in all_bosses():
            for step in boss.steps:
                with self.subTest(boss=boss.id, step=step.id):
                    self.assertEqual(
                        [t.to_json() for t in step.tests_for(7)],
                        [t.to_json() for t in step.tests_for(7)],
                    )

    def test_different_seeds_give_different_data(self):
        for boss in all_bosses():
            for step in boss.steps:
                with self.subTest(boss=boss.id, step=step.id):
                    self.assertNotEqual(
                        [t.to_json() for t in step.tests_for(1)],
                        [t.to_json() for t in step.tests_for(2)],
                    )


class TestTheStepsLink(unittest.TestCase):
    """What makes this a boss rather than three levels in a row."""

    def test_a_step_that_declares_uses_actually_calls_them(self):
        for boss in all_bosses():
            for step in boss.steps:
                if not step.uses:
                    continue
                tree = ast.parse(step.reference)
                called = {
                    node.func.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                }
                for name in step.uses:
                    with self.subTest(boss=boss.id, step=step.id, uses=name):
                        self.assertIn(name, called)

    def test_a_declared_dependency_names_an_earlier_step(self):
        """Depending on a later step is a cycle the unlock order cannot serve."""
        for boss in all_bosses():
            earlier: set[str] = set()
            for step in boss.steps:
                with self.subTest(boss=boss.id, step=step.id):
                    for name in step.uses:
                        self.assertIn(name, earlier)
                earlier.add(step.func_name)

    def test_a_linked_step_fails_without_the_steps_it_builds_on(self):
        """The linking has to be real: if a step's reference passes in
        isolation, it never needed the earlier ones and the boss is three
        unrelated levels wearing one name."""
        for boss in all_bosses():
            for index, step in enumerate(boss.steps):
                if not step.uses:
                    continue
                with self.subTest(boss=boss.id, step=step.id):
                    result = run_code(
                        step.reference, step.func_name, step.tests_for(1),
                        source=Source.BUNDLED,
                    )
                    self.assertFalse(
                        all(o.passed for o in result.outcomes),
                        "reference passed without its dependencies",
                    )


class TestReferencesAndStarters(unittest.TestCase):
    def test_every_reference_solves_every_step_on_every_seed(self):
        for boss in all_bosses():
            for index, step in enumerate(boss.steps):
                source = boss.reference_source(index)
                for seed in SEEDS:
                    with self.subTest(boss=boss.id, step=step.id, seed=seed):
                        result = run_code(
                            source, step.func_name, step.tests_for(seed),
                            source=Source.BUNDLED,
                        )
                        failed = [o.name for o in result.outcomes if not o.passed]
                        self.assertEqual(failed, [], result.error)

    def test_no_starter_already_passes_its_own_step(self):
        """A starter that passes hands out a free step."""
        for boss in all_bosses():
            for index, step in enumerate(boss.steps):
                with self.subTest(boss=boss.id, step=step.id):
                    result = run_code(
                        boss.starter_source(index), step.func_name,
                        step.tests_for(1), source=Source.BUNDLED,
                    )
                    self.assertFalse(all(o.passed for o in result.outcomes))


class TestTheSharedBuffer(unittest.TestCase):
    def test_the_first_step_starts_with_only_its_own_starter(self):
        boss = get_boss("w1-boss-pipeline")
        buffer = boss.starter_source(0)
        self.assertIn(boss.steps[0].func_name, buffer)
        self.assertNotIn(f"def {boss.steps[1].func_name}", buffer)

    def test_a_later_step_carries_what_the_player_wrote(self):
        boss = get_boss("w1-boss-pipeline")
        mine = "def parse_rows(lines):\n    return ['mine']\n"
        buffer = boss.starter_source(1, solved=[mine])
        self.assertIn("return ['mine']", buffer)
        self.assertIn(f"def {boss.steps[1].func_name}", buffer)

    def test_an_unsolved_earlier_step_falls_back_to_its_starter(self):
        """Never to the reference: that would hand out the answer."""
        boss = get_boss("w1-boss-pipeline")
        buffer = boss.starter_source(1, solved=[""])
        self.assertIn(boss.steps[0].starter.strip(), buffer)
        self.assertNotIn(boss.steps[0].reference.strip(), buffer)

    def test_the_buffer_is_valid_python_at_every_step(self):
        for boss in all_bosses():
            for index in range(boss.step_count):
                with self.subTest(boss=boss.id, step=index):
                    ast.parse(boss.starter_source(index))

    def test_the_reference_source_grows_with_the_steps(self):
        boss = get_boss("w1-boss-pipeline")
        for index in range(boss.step_count):
            with self.subTest(step=index):
                source = boss.reference_source(index)
                for earlier in boss.steps[: index + 1]:
                    self.assertIn(f"def {earlier.func_name}", source)
                for later in boss.steps[index + 1:]:
                    self.assertNotIn(f"def {later.func_name}", source)

    def test_the_full_reference_defines_every_function(self):
        for boss in all_bosses():
            with self.subTest(boss=boss.id):
                tree = ast.parse(boss.reference_source())
                defined = {
                    node.name for node in tree.body
                    if isinstance(node, ast.FunctionDef)
                }
                self.assertEqual(
                    defined, {step.func_name for step in boss.steps}
                )


if __name__ == "__main__":
    unittest.main()
