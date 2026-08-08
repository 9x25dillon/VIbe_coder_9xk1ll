"""Style checkers gate a bonus and tips gate the player's trust.

A tip that fires on correct code is worse than no tip at all, so the negative
cases here matter as much as the positive ones.
"""

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
