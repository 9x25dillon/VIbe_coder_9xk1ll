"""The sandbox must survive everything a learner can throw at it."""

import unittest

from vibecoder.models import TestCase as Case
from vibecoder.runner import run_code


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
