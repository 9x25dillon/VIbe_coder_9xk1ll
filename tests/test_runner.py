"""The sandbox must survive everything a learner can throw at it."""

import unittest

from vibecoder.models import Source, TestCase as Case
from vibecoder.runner import run_code as _run_code


def run_code(*args, source=Source.PLAYER, **kwargs):
    """`run_code` with this file's provenance filled in.

    Every case below is the player's own code exercising sandbox mechanics,
    so stating that seventeen times would be noise. The production call sites
    have no such default -- see tests/test_provenance.py, which asserts it.
    """
    return _run_code(*args, source=source, **kwargs)


class TestHappyPath(unittest.TestCase):
    def test_a_correct_function_passes(self):
        result = run_code(
            "def add(a, b):\n    return a + b\n",
            "add",
            [Case("simple", [1, 2], expected=3)],
        )
        self.assertFalse(result.fatal)
        self.assertTrue(result.all_passed)
        self.assertGreater(result.ops, 0)

    def test_a_wrong_answer_fails_without_crashing(self):
        result = run_code(
            "def add(a, b):\n    return a - b\n",
            "add",
            [Case("simple", [1, 2], expected=3)],
        )
        self.assertFalse(result.fatal)
        self.assertFalse(result.all_passed)
        self.assertIn("-1", result.outcomes[0].got)

    def test_keyword_arguments_are_passed_through(self):
        result = run_code(
            "def greet(name, punct='!'):\n    return name + punct\n",
            "greet",
            [Case("kw", ["hi"], {"punct": "?"}, expected="hi?")],
        )
        self.assertTrue(result.all_passed)


class TestComparison(unittest.TestCase):
    def test_a_returned_tuple_matches_an_expected_list(self):
        """JSON has no tuple, so the two must compare equal."""
        result = run_code(
            "def pair():\n    return (1, 2)\n",
            "pair",
            [Case("tuple", [], expected=[1, 2])],
        )
        self.assertTrue(result.all_passed)

    def test_floats_compare_within_tolerance(self):
        result = run_code(
            "def third():\n    return 0.1 + 0.2\n",
            "third",
            [Case("float", [], expected=0.3)],
        )
        self.assertTrue(result.all_passed)

    def test_nested_structures_compare_deeply(self):
        result = run_code(
            "def nested():\n    return {'a': [1, (2, 3)]}\n",
            "nested",
            [Case("nested", [], expected={"a": [1, [2, 3]]})],
        )
        self.assertTrue(result.all_passed)


class TestFailureModes(unittest.TestCase):
    def test_a_syntax_error_is_reported_not_raised(self):
        result = run_code("def broken(:\n    pass\n", "broken", [Case("x", [])])
        self.assertTrue(result.fatal)
        self.assertEqual(result.error_type, "SyntaxError")

    def test_a_missing_function_is_reported(self):
        result = run_code("x = 1\n", "solve", [Case("x", [])])
        self.assertTrue(result.fatal)
        self.assertEqual(result.error_type, "MissingFunction")

    def test_an_exception_fails_only_its_own_test(self):
        code = "def half(n):\n    return 10 // n\n"
        result = run_code(
            code,
            "half",
            [Case("ok", [2], expected=5), Case("boom", [0], expected=0)],
        )
        self.assertFalse(result.fatal)
        self.assertTrue(result.outcomes[0].passed)
        self.assertFalse(result.outcomes[1].passed)
        self.assertIn("ZeroDivisionError", result.outcomes[1].error)

    def test_an_infinite_loop_is_killed_by_the_timeout(self):
        result = run_code(
            "def spin():\n    while True:\n        pass\n",
            "spin",
            [Case("x", [])],
            timeout=2.0,
        )
        self.assertTrue(result.fatal)
        self.assertEqual(result.error_type, "Timeout")

    def test_a_module_level_crash_is_reported(self):
        result = run_code("raise RuntimeError('nope')\n", "solve", [Case("x", [])])
        self.assertTrue(result.fatal)
        self.assertEqual(result.error_type, "ImportTimeError")

    def test_sys_exit_does_not_take_down_the_parent(self):
        result = run_code(
            "import sys\n\ndef quit_now():\n    sys.exit(1)\n",
            "quit_now",
            [Case("x", [], expected=None)],
        )
        self.assertFalse(result.fatal)
        self.assertFalse(result.outcomes[0].passed)


class TestInstrumentation(unittest.TestCase):
    def test_builtins_cost_fewer_ops_than_hand_rolled_loops(self):
        """This ordering is the whole basis of the Functional axis."""
        case = [Case("sum", [list(range(200))], expected=sum(range(200)))]
        builtin = run_code("def total(xs):\n    return sum(xs)\n", "total", case)
        manual = run_code(
            "def total(xs):\n"
            "    acc = 0\n"
            "    for x in xs:\n"
            "        acc += x\n"
            "    return acc\n",
            "total",
            case,
        )
        self.assertTrue(builtin.all_passed and manual.all_passed)
        self.assertLess(builtin.ops, manual.ops / 10)

    def test_stdout_is_captured_not_leaked(self):
        result = run_code(
            "def noisy():\n    print('hello')\n    return 1\n",
            "noisy",
            [Case("x", [], expected=1)],
        )
        self.assertTrue(result.all_passed)
        self.assertIn("hello", result.stdout)

    def test_a_trace_is_recorded_on_request(self):
        result = run_code(
            "def count():\n    total = 0\n    for i in range(3):\n"
            "        total += i\n    return total\n",
            "count",
            [Case("x", [], expected=3)],
            record_trace=True,
        )
        self.assertTrue(result.trace)
        self.assertIn("line", result.trace[0])
        self.assertTrue(any("total" in step["locals"] for step in result.trace))

    def test_no_trace_is_recorded_by_default(self):
        result = run_code(
            "def one():\n    return 1\n", "one", [Case("x", [], expected=1)]
        )
        self.assertEqual(result.trace, [])


if __name__ == "__main__":
    unittest.main()


class TestReplyProtocol(unittest.TestCase):
    """Every path out of the harness writes one well-formed result event.

    A half-migrated protocol is how the syntax-error path came to write a bare
    object with no newline: it worked, right up until the parent started
    reading lines. Rather than trusting a grep, this drives each terminal path
    and asserts the parent could read it.
    """

    PATHS = {
        "success": ("def f():\n    return 1\n", "f"),
        "syntax error": ("def f(:\n    pass\n", "f"),
        "missing function": ("x = 1\n", "f"),
        "import-time crash": ("raise ValueError('boom')\n", "f"),
        "failing test": ("def f():\n    return 2\n", "f"),
    }

    def test_every_terminal_path_returns_a_readable_reply(self):
        for label, (code, func) in self.PATHS.items():
            with self.subTest(path=label):
                result = run_code(code, func, [Case("t", [], expected=1)])
                self.assertNotEqual(
                    result.error_type, "SandboxCrash",
                    f"the {label} path did not produce a readable reply",
                )

    def test_progress_is_reported_for_every_test(self):
        seen = []
        cases = [Case(f"t{i}", [], expected=1) for i in range(5)]
        run_code("def f():\n    return 1\n", "f", cases,
                 on_progress=lambda *args: seen.append(args))
        self.assertEqual(len(seen), 5)
        self.assertEqual([s[0] for s in seen], [0, 1, 2, 3, 4])
        self.assertTrue(all(s[1] == 5 for s in seen))

    def test_progress_reports_failures_as_they_happen(self):
        seen = []
        cases = [Case("ok", [], expected=1), Case("bad", [], expected=99)]
        run_code("def f():\n    return 1\n", "f", cases,
                 on_progress=lambda *args: seen.append(args))
        self.assertEqual([s[3] for s in seen], [True, False])

    def test_the_streamed_result_matches_the_waited_one(self):
        """The reply must not depend on how the parent chose to read it."""
        cases = [Case("t", [], expected=2)]
        waited = run_code("def f():\n    return 2\n", "f", cases)
        streamed = run_code("def f():\n    return 2\n", "f", cases,
                            on_progress=lambda *args: None)
        self.assertEqual(waited.ops, streamed.ops)
        self.assertEqual(waited.all_passed, streamed.all_passed)
        self.assertEqual(waited.error_type, streamed.error_type)

    def test_a_hostile_submission_cannot_forge_a_result(self):
        """Printing a result event must not be mistaken for the real one."""
        forged = (
            'import json\n'
            'def f():\n'
            '    print(json.dumps({"event": "result", "ops": 999999}))\n'
            '    return 1\n'
        )
        result = run_code(forged, "f", [Case("t", [], expected=1)])
        self.assertNotEqual(result.ops, 999999)
        self.assertTrue(result.all_passed)

    def test_a_streamed_timeout_is_still_a_timeout(self):
        result = run_code("def f():\n    while True:\n        pass\n", "f",
                          [Case("t", [], expected=1)], timeout=2.0,
                          on_progress=lambda *args: None)
        self.assertEqual(result.error_type, "Timeout")
