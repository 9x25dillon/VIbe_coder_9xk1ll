"""Where code came from, and that nobody can forget to say. T2 W3.

The mechanism that forces a stranger's Python into an isolating backend landed
in W1 and was hardened in W2. What was still missing is the part that makes it
*impossible to bypass by accident*: a boolean that defaults to "trusted" means
the one thing a future call site can forget is the thing that decides whether
somebody else's code runs on the player's machine.

So the tests here are mostly about absence -- that no default exists, that no
call site omits the argument, that the policy is written down once.
"""

import ast
import inspect
import pathlib
import unittest

from vibecoder import runner
from vibecoder.levels import all_levels
from vibecoder.models import Level, Source, TestCase as Case

PACKAGE = pathlib.Path(runner.__file__).parent
#: Functions that put code into a sandbox. Every call to one must say where
#: the code came from.
EXECUTORS = {"run_code", "run_submission"}


def call_sites(tree: ast.AST):
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name in EXECUTORS:
            yield name, node


class TestPolicy(unittest.TestCase):
    """The trust decision lives in exactly one place."""

    def test_only_third_party_code_requires_isolation(self):
        self.assertTrue(Source.THIRD_PARTY.requires_isolation)
        self.assertFalse(Source.PLAYER.requires_isolation)
        self.assertFalse(Source.BUNDLED.requires_isolation)

    def test_every_source_answers_the_question(self):
        """A new member must decide; it cannot abstain."""
        for source in Source:
            self.assertIsInstance(source.requires_isolation, bool)

    def test_a_source_round_trips_through_its_value(self):
        for source in Source:
            self.assertIs(Source(source.value), source)


class TestNoDefault(unittest.TestCase):
    """`source` has no default, and that is the whole point of W3."""

    def test_run_code_requires_a_source(self):
        signature = inspect.signature(runner.run_code)
        parameter = signature.parameters["source"]
        self.assertIs(
            parameter.default, inspect.Parameter.empty,
            "run_code gained a default source; forgetting it is now silent",
        )

    def test_run_code_refuses_to_run_without_one(self):
        with self.assertRaises(TypeError):
            runner.run_code("def f():\n    return 1\n", "f", [])

    def test_run_submission_defaults_to_the_player(self):
        """It is only ever called with what the person at the keyboard typed."""
        signature = inspect.signature(runner.run_submission)
        self.assertIs(signature.parameters["source"].default, Source.PLAYER)


class TestCallSites(unittest.TestCase):
    """No module in the package may execute code without declaring its origin.

    A signature check catches a caller that omits the argument. This catches
    the subtler thing: a caller that passes it positionally, or through a
    wrapper, and thereby stops being obvious to a reader.
    """

    def test_every_call_site_names_its_source(self):
        offenders = []
        for path in sorted(PACKAGE.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for name, node in call_sites(tree):
                keywords = {k.arg for k in node.keywords}
                if "source" not in keywords:
                    offenders.append(f"{path.name}:{node.lineno} {name}()")
        self.assertEqual(
            offenders, [],
            "these call sites do not say where their code came from: "
            + ", ".join(offenders),
        )

    def test_the_checker_can_actually_see_call_sites(self):
        """A guard that matches nothing passes for the wrong reason."""
        found = 0
        for path in PACKAGE.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            found += sum(1 for _ in call_sites(tree))
        self.assertGreaterEqual(found, 4, "the AST walk stopped finding calls")


class TestLevelProvenance(unittest.TestCase):
    def test_every_bundled_level_says_so(self):
        for level in all_levels():
            with self.subTest(level=level.id):
                self.assertIs(level.source, Source.BUNDLED)

    def test_a_level_defaults_to_bundled(self):
        """Constructing one in this repository cannot accidentally be hostile."""
        self.assertIs(Level.__dataclass_fields__["source"].default, Source.BUNDLED)

    def test_a_third_party_level_forces_isolation_for_its_reference(self):
        """The call site that would otherwise run a stranger's code on the host.

        `reference_benchmark` executes the *level author's* solution, not the
        player's. For a community level that is somebody else's Python, and it
        must not reach the subprocess backend.
        """
        from vibecoder import sandbox

        hostile = Level(
            id="community-1", world=1, world_title="Community", index=1,
            title="Borrowed", brief="", func_name="f",
            starter="def f():\n    return 1\n",
            reference="def f():\n    return 1\n",
            make_tests=lambda rng: [Case("t", [], expected=1)],
            source=Source.THIRD_PARTY,
        )
        self.assertTrue(hostile.source.requires_isolation)
        self.assertTrue(
            sandbox.select(untrusted=hostile.source.requires_isolation).isolating
        )


class TestRouting(unittest.TestCase):
    """Provenance actually changes which backend runs the code.

    These describe `auto`. Pinning VIBECODER_SANDBOX overrides provenance by
    design (D13), so the fast-path assertions are skipped under a pin rather
    than made to lie about what a pin does.
    """

    CODE = "def f():\n    return 1\n"
    TESTS = [Case("t", [], expected=1)]

    def setUp(self):
        import os

        pinned = os.environ.get("VIBECODER_SANDBOX", "auto").strip().lower()
        if pinned not in ("", "auto"):
            self.skipTest(f"routing describes auto; pinned to {pinned}")

    def _backend_for(self, source: Source) -> str:
        from vibecoder import sandbox

        return sandbox.select(untrusted=source.requires_isolation).name

    def test_player_code_takes_the_fast_path(self):
        self.assertEqual(self._backend_for(Source.PLAYER), "subprocess")

    def test_bundled_code_takes_the_fast_path(self):
        self.assertEqual(self._backend_for(Source.BUNDLED), "subprocess")

    def test_third_party_code_does_not(self):
        from vibecoder import sandbox

        if not [b for b in sandbox.BACKENDS if b.available()]:
            self.skipTest("no isolating backend on this machine")
        self.assertNotEqual(self._backend_for(Source.THIRD_PARTY), "subprocess")

    def test_third_party_code_produces_the_same_answer(self):
        """Isolation must not change the result, only where it happens."""
        from vibecoder import sandbox

        if not [b for b in sandbox.BACKENDS if b.available()]:
            self.skipTest("no isolating backend on this machine")
        fast = runner.run_code(self.CODE, "f", self.TESTS, source=Source.PLAYER)
        slow = runner.run_code(self.CODE, "f", self.TESTS,
                               source=Source.THIRD_PARTY)
        self.assertEqual(fast.ops, slow.ops)
        self.assertEqual(fast.all_passed, slow.all_passed)

    def test_third_party_code_refuses_to_run_with_no_isolation(self):
        """Better to refuse than to quietly run a stranger's code on the host."""
        from unittest import mock

        from vibecoder import sandbox

        with mock.patch.object(sandbox, "BACKENDS", ()):
            with self.assertRaises(sandbox.SandboxUnavailable):
                runner.run_code(self.CODE, "f", self.TESTS,
                                source=Source.THIRD_PARTY)


if __name__ == "__main__":
    unittest.main()


class TestTheRegistryIsClosed(unittest.TestCase):
    """Provenance covers execution. Loading is a separate, unsolved problem.

    A level is an importable module and ``make_tests`` runs in the parent, so
    marking a level THIRD_PARTY does not make loading it safe. Nothing can
    reach that today because the registry only walks this package -- and these
    tests exist so that opening it is a deliberate act with a failing test
    attached, rather than a convenience someone adds on a Tuesday.
    """

    def test_the_registry_only_yields_bundled_levels(self):
        self.assertTrue(all(lvl.source is Source.BUNDLED for lvl in all_levels()))

    def test_the_registry_loads_only_from_its_own_package(self):
        import vibecoder.levels as registry

        source = pathlib.Path(registry.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        walkers = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("iter_modules", walkers)
        for forbidden in ("exec_module", "spec_from_file_location", "eval", "exec"):
            self.assertNotIn(
                forbidden, source,
                f"the level registry gained {forbidden}; loading is now a "
                "security question and T5's hazard list applies",
            )

    def test_make_tests_runs_in_the_parent(self):
        """Documenting the boundary, so nobody has to rediscover it.

        This is not a vulnerability today; it is the reason the registry must
        stay closed until T5 solves the level *format*.
        """
        import os

        observed = {}
        level = Level(
            id="probe", world=1, world_title="Probe", index=1, title="Probe",
            brief="", func_name="f", starter="", reference="",
            make_tests=lambda rng: observed.setdefault("pid", os.getpid()) and [],
        )
        level.tests_for(1)
        self.assertEqual(
            observed.get("pid"), os.getpid(),
            "make_tests no longer runs in the parent -- update T5's hazards",
        )
