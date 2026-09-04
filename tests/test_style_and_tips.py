"""Style checkers gate a bonus and tips gate the player's trust.

A tip that fires on correct code is worse than no tip at all, so the negative
cases here matter as much as the positive ones.
"""

import ast
import unittest

from vibecoder import style, tips
from vibecoder.models import RunResult, TestOutcome, VibeVector


def passing(ops: int = 100) -> RunResult:
    return RunResult(outcomes=[TestOutcome("t", True)], ops=ops)


class TestStyleCheckers(unittest.TestCase):
    def check(self, code: str, goal: str) -> bool:
        return style.evaluate(code, "solve", (goal,))[goal]

    def test_comprehension(self):
        self.assertTrue(self.check("def solve(x):\n    return [i for i in x]\n",
                                   "uses_comprehension"))
        self.assertFalse(self.check("def solve(x):\n    return list(x)\n",
                                    "uses_comprehension"))

    def test_generator_expression_is_not_a_list_comprehension(self):
        self.assertTrue(self.check("def solve(x):\n    return sum(i for i in x)\n",
                                   "uses_generator_expr"))
        self.assertFalse(self.check("def solve(x):\n    return sum([i for i in x])\n",
                                    "uses_generator_expr"))

    def test_no_explicit_loop_allows_comprehensions(self):
        self.assertTrue(self.check("def solve(x):\n    return [i for i in x]\n",
                                   "no_explicit_loop"))
        self.assertFalse(self.check(
            "def solve(x):\n    for i in x:\n        pass\n", "no_explicit_loop"))

    def test_recursion(self):
        self.assertTrue(self.check(
            "def solve(n):\n    return 1 if n < 2 else solve(n - 1)\n",
            "uses_recursion"))
        self.assertFalse(self.check("def solve(n):\n    return n\n", "uses_recursion"))

    def test_enumerate(self):
        self.assertTrue(self.check(
            "def solve(x):\n    return [i for i, v in enumerate(x)]\n",
            "uses_enumerate"))

    def test_type_hints_require_both_arguments_and_return(self):
        self.assertTrue(self.check("def solve(x: int) -> int:\n    return x\n",
                                   "has_type_hints"))
        self.assertFalse(self.check("def solve(x: int):\n    return x\n",
                                    "has_type_hints"))

    def test_single_return(self):
        self.assertTrue(self.check("def solve(x):\n    return x\n", "single_return"))
        self.assertFalse(self.check(
            "def solve(x):\n    if x:\n        return 1\n    return 2\n",
            "single_return"))


class TestStyleRobustness(unittest.TestCase):
    def test_unparseable_code_fails_every_goal(self):
        results = style.evaluate("def broken(:", "solve", ("uses_comprehension",))
        self.assertEqual(results, {"uses_comprehension": False})

    def test_a_missing_target_function_fails_every_goal(self):
        results = style.evaluate("x = 1", "solve", ("uses_comprehension",))
        self.assertFalse(results["uses_comprehension"])

    def test_only_the_target_function_is_inspected(self):
        """A helper elsewhere in the file must not satisfy the goal."""
        code = (
            "def helper(x):\n    return [i for i in x]\n\n"
            "def solve(x):\n    return list(x)\n"
        )
        self.assertFalse(style.evaluate(code, "solve", ("uses_comprehension",))
                         ["uses_comprehension"])

    def test_an_unknown_goal_is_a_programming_error(self):
        with self.assertRaises(KeyError):
            style.evaluate("def solve():\n    pass\n", "solve", ("nonsense",))

    def test_no_goals_means_the_bonus_is_available(self):
        self.assertTrue(style.all_met(style.evaluate("def solve():\n    pass\n",
                                                     "solve", ())))


class TestTips(unittest.TestCase):
    def tips_for(self, code: str, **kwargs) -> list[str]:
        return tips.generate(code, "solve", kwargs.pop("result", passing()), **kwargs)

    def test_append_only_loop_suggests_a_comprehension(self):
        code = (
            "def solve(xs):\n    out = []\n    for x in xs:\n"
            "        out.append(x)\n    return out\n"
        )
        self.assertTrue(any("comprehension" in t for t in self.tips_for(code)))

    def test_range_len_suggests_enumerate(self):
        code = "def solve(xs):\n    return [xs[i] for i in range(len(xs))]\n"
        self.assertTrue(any("enumerate" in t for t in self.tips_for(code)))

    def test_bare_except_is_flagged(self):
        code = (
            "def solve(x):\n    try:\n        return int(x)\n"
            "    except:\n        return 0\n"
        )
        self.assertTrue(any("bare" in t.lower() for t in self.tips_for(code)))

    def test_nested_loops_are_flagged(self):
        code = (
            "def solve(a, b):\n    for x in a:\n        for y in b:\n"
            "            pass\n    return 0\n"
        )
        self.assertTrue(any("O(n*m)" in t for t in self.tips_for(code)))

    def test_inefficiency_is_flagged_only_well_past_the_reference(self):
        clean = "def solve(xs):\n    return sum(xs)\n"
        near = self.tips_for(clean, result=passing(ops=110), ref_ops=100)
        far = self.tips_for(clean, result=passing(ops=1000), ref_ops=100)
        self.assertFalse(any("as many lines" in t for t in near))
        self.assertTrue(any("as many lines" in t for t in far))

    def test_idiomatic_code_earns_no_tips(self):
        """The most important negative case: do not nag a good solution."""
        code = "def solve(xs):\n    return sum(x for x in xs if x > 0)\n"
        self.assertEqual(self.tips_for(code, ref_ops=100), [])

    def test_type_hint_tip_only_fires_for_players_who_use_them(self):
        code = "def solve(xs):\n    return len(xs)\n"
        typed = VibeVector(patterns={"type_hints": 0.9})
        untyped = VibeVector(patterns={"type_hints": 0.1})
        self.assertTrue(any("annotat" in t for t in self.tips_for(code, vibe=typed)))
        self.assertFalse(any("annotat" in t for t in self.tips_for(code, vibe=untyped)))

    def test_missed_style_goals_are_reported(self):
        code = "def solve(xs):\n    return list(xs)\n"
        result = self.tips_for(code, style_results={"uses_comprehension": False})
        self.assertTrue(any("Style goal missed" in t for t in result))

    def test_unparseable_code_yields_no_tips(self):
        self.assertEqual(self.tips_for("def broken(:"), [])

    def test_the_tip_limit_is_respected(self):
        code = (
            "def solve(a, b):\n    out = []\n    for i in range(len(a)):\n"
            "        for y in b:\n            out.append(y)\n"
            "    try:\n        pass\n    except:\n        pass\n    return out\n"
        )
        self.assertLessEqual(len(self.tips_for(code, limit=2)), 2)


if __name__ == "__main__":
    unittest.main()


class TestTipsForABrokenProgram(unittest.TestCase):
    """A run where nothing passed gets correctness advice or silence.

    Coaching somebody about comprehensions while their program raises on every
    case reads as the game missing the point, so polish rules are held back
    until something works.
    """

    def _result(self, passed: int, total: int) -> RunResult:
        return RunResult(
            outcomes=[
                TestOutcome(name=f"t{i}", passed=i < passed, error="Boom" )
                for i in range(total)
            ],
            ops=100,
        )

    NOTHING_WORKS = (
        "def f(xs):\n"
        "    total = 0\n"
        "    for i in range(len(xs) + 1):\n"
        "        total += xs[i]\n"
        "    return total\n"
    )

    def test_a_broken_program_is_not_given_style_advice(self):
        messages = tips.generate(
            self.NOTHING_WORKS, "f", self._result(0, 5), ref_ops=10
        )
        self.assertTrue(
            all("comprehension" not in m and "sum()" not in m for m in messages),
            messages,
        )

    def test_a_broken_program_still_gets_the_off_by_one(self):
        messages = tips.generate(
            self.NOTHING_WORKS, "f", self._result(0, 5), ref_ops=10
        )
        self.assertTrue(
            any("one step past the end" in m for m in messages), messages
        )

    def test_a_working_program_still_gets_polish_advice(self):
        """The gate is on failure, not on the rules being disabled."""
        messages = tips.generate(
            self.NOTHING_WORKS, "f", self._result(5, 5), ref_ops=10
        )
        self.assertTrue(
            any("sum()" in m or "enumerate" in m for m in messages), messages
        )

    def test_silence_is_allowed_when_no_correctness_rule_matches(self):
        clean = "def f(xs):\n    return [x * 2 for x in xs]\n"
        self.assertEqual(tips.generate(clean, "f", self._result(0, 3)), [])


class TestOffByOneRule(unittest.TestCase):
    def test_range_len_plus_one_is_caught(self):
        code = "def f(xs):\n    for i in range(len(xs) + 1):\n        pass\n"
        self.assertIsNotNone(
            tips.range_len_off_by_one(
                tips.TipContext(code, "f", ast.parse(code), RunResult(), 0, None, {})
            )
        )

    def test_a_correct_range_len_is_not_flagged_as_off_by_one(self):
        code = "def f(xs):\n    for i in range(len(xs)):\n        pass\n"
        self.assertIsNone(
            tips.range_len_off_by_one(
                tips.TipContext(code, "f", ast.parse(code), RunResult(), 0, None, {})
            )
        )

    def test_adding_something_other_than_one_is_not_flagged(self):
        code = "def f(xs, n):\n    for i in range(len(xs) + n):\n        pass\n"
        self.assertIsNone(
            tips.range_len_off_by_one(
                tips.TipContext(code, "f", ast.parse(code), RunResult(), 0, None, {})
            )
        )


class TestTheEfficiencyTipClaimsOnlyWhatItChecked(unittest.TestCase):
    """Q33: the tip used to diagnose a cause it had never looked for."""

    def test_it_does_not_assert_loop_invariant_work(self):
        code = "def f(xs):\n    out = []\n    for x in xs:\n        out.append(x)\n    return out\n"
        result = RunResult(
            outcomes=[TestOutcome(name="t", passed=True)], ops=500
        )
        messages = tips.generate(code, "f", result, ref_ops=100)
        efficiency = [m for m in messages if "as many" in m]
        self.assertTrue(efficiency)
        self.assertNotIn("Look for work being repeated", efficiency[0])
        self.assertIn("usually", efficiency[0])
