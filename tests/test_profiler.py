"""The Vibe Profiler drives every personalisation decision, so its extraction
has to be right on small, hand-checkable inputs."""

import tempfile
import unittest
from pathlib import Path

from vibecoder.models import VibeVector
from vibecoder.profiler import (
    derive_tags,
    profile_path,
    recommend,
    style_signature,
)

SAMPLE = '''\
import pandas as pd
import requests
from collections import defaultdict


def fetch_rows(url: str) -> list:
    """Grab rows from an endpoint."""
    try:
        response = requests.get(url)
    except KeyError:
        return []
    return [r for r in response.json()]


def tally(rows):
    counts = defaultdict(int)
    for row in rows:
        counts[row] += 1
    return counts


class Report:
    def render(self):
        return f"{len(self.rows)} rows"
'''


class ProfilerTestBase(unittest.TestCase):
    def one(self, source: str) -> VibeVector:
        """Profile a codebase of exactly one module.

        Keyword arguments cannot contain a dot, so `profile(a_py=...)` writes
        a file the globber never finds and every assertion silently measures
        an empty directory.
        """
        return self.profile(**{"a.py": source})

    def profile(self, **files) -> VibeVector:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        for name, source in files.items():
            (root / name).write_text(source, encoding="utf-8")
        return profile_path(root)


class TestExtraction(ProfilerTestBase):
    def setUp(self):
        self.vibe = self.profile(**{"sample.py": SAMPLE})

    def test_counts_files_and_functions(self):
        self.assertEqual(self.vibe.files, 1)
        self.assertEqual(self.vibe.functions, 3)

    def test_collects_libraries(self):
        self.assertIn("pandas", self.vibe.libraries)
        self.assertIn("requests", self.vibe.libraries)
        self.assertIn("collections", self.vibe.libraries)

    def test_ignores_future_imports(self):
        vibe = self.profile(**{"f.py": "from __future__ import annotations\nx = 1\n"})
        self.assertNotIn("__future__", vibe.libraries)

    def test_detects_patterns(self):
        self.assertGreater(self.vibe.patterns.get("comprehension", 0), 0)
        self.assertGreater(self.vibe.patterns.get("fstring", 0), 0)
        self.assertGreater(self.vibe.patterns.get("class", 0), 0)
        self.assertGreater(self.vibe.patterns.get("try_except", 0), 0)

    def test_records_caught_exceptions(self):
        self.assertEqual(self.vibe.exceptions_caught.get("KeyError"), 1)

    def test_measures_docstring_coverage(self):
        # One of three functions is documented.
        self.assertAlmostEqual(self.vibe.docstring_ratio, 1 / 3, places=2)

    def test_type_hints_are_measured_per_function(self):
        # Only fetch_rows is annotated.
        self.assertAlmostEqual(self.vibe.patterns["type_hints"], 1 / 3, places=2)

    def test_derives_content_tags(self):
        self.assertIn("data", self.vibe.tags)
        self.assertIn("web", self.vibe.tags)


class TestNaming(ProfilerTestBase):
    def test_snake_case_dominates_a_snake_case_file(self):
        vibe = self.profile(
            **{"a.py": "def do_thing():\n    my_var = 1\n    other = 2\n"}
        )
        self.assertGreater(vibe.naming["snake_case"], 0.9)

    def test_camel_case_is_detected(self):
        vibe = self.profile(
            **{"a.py": "def doThing():\n    myVar = 1\n    otherThing = 2\n"}
        )
        self.assertGreater(vibe.naming["camelCase"], 0.9)

    def test_constants_are_classified_separately(self):
        vibe = self.profile(**{"a.py": "MAX_SIZE = 10\nTIMEOUT = 3\n"})
        self.assertEqual(vibe.naming.get("SCREAMING_SNAKE"), 1.0)


class TestRobustness(ProfilerTestBase):
    def test_an_unparseable_file_is_skipped_not_fatal(self):
        vibe = self.profile(
            **{"good.py": "def ok():\n    return 1\n", "bad.py": "def broken(:\n"}
        )
        self.assertEqual(vibe.files, 1)
        self.assertEqual(vibe.functions, 1)

    def test_an_empty_directory_profiles_cleanly(self):
        vibe = self.profile()
        self.assertEqual(vibe.files, 0)
        self.assertEqual(vibe.tags, [])

    def test_a_missing_path_raises(self):
        with self.assertRaises(FileNotFoundError):
            profile_path("/definitely/not/here")

    def test_virtualenvs_and_caches_are_skipped(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / ".venv").mkdir()
        (root / ".venv" / "junk.py").write_text("def vendored():\n    pass\n")
        (root / "mine.py").write_text("def mine():\n    pass\n")
        vibe = profile_path(root)
        self.assertEqual(vibe.files, 1)

    def test_a_single_file_can_be_profiled(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "one.py"
        path.write_text("import flask\n\ndef view():\n    return 1\n")
        vibe = profile_path(path)
        self.assertEqual(vibe.files, 1)
        self.assertIn("web", vibe.tags)


class TestTagDerivation(unittest.TestCase):
    def test_patterns_below_the_threshold_do_not_earn_a_tag(self):
        vibe = VibeVector(patterns={"comprehension": 0.05})
        self.assertNotIn("functional", derive_tags(vibe))

    def test_patterns_above_the_threshold_earn_a_tag(self):
        vibe = VibeVector(patterns={"comprehension": 0.9})
        self.assertIn("functional", derive_tags(vibe))


class FakeLevel:
    def __init__(self, level_id, tags, world=1, index=1):
        self.id = level_id
        self.tags = tags
        self.world = world
        self.index = index


class TestRecommendation(unittest.TestCase):
    def test_gaps_are_ranked_above_familiar_ground(self):
        """The Vibe Vector exists to fill gaps, not to replay strengths."""
        vibe = VibeVector(tags=["data", "tabular"])
        familiar = FakeLevel("familiar", ("data", "tabular"))
        gap = FakeLevel("gap", ("async", "concurrency"), index=2)
        ordered = recommend([familiar, gap], vibe)
        self.assertEqual(ordered[0].id, "gap")

    def test_untagged_levels_sink_to_the_bottom(self):
        vibe = VibeVector(tags=["data"])
        tagged = FakeLevel("tagged", ("async",))
        untagged = FakeLevel("untagged", ())
        self.assertEqual(recommend([untagged, tagged], vibe)[0].id, "tagged")

    def test_ordering_is_stable_without_a_profile(self):
        vibe = VibeVector(tags=[])
        first = FakeLevel("a", ("x",), world=1, index=1)
        second = FakeLevel("b", ("x",), world=1, index=2)
        self.assertEqual([lvl.id for lvl in recommend([second, first], vibe)], ["a", "b"])


class TestConventions(ProfilerTestBase):
    """PEP 8 conformance, judged per identifier kind.

    Pooling every identifier into one histogram cannot tell a correctly named
    class from a Java-style function, which is why class names used to be left
    out of `naming` altogether and reported as 0% PascalCase in a codebase
    made of classes.
    """

    def test_a_pascal_case_class_is_conforming(self):
        self.assertEqual(self.one("class OrderBook:\n    pass\n").conventions["class"], 1.0)

    def test_a_snake_case_class_is_not(self):
        self.assertEqual(self.one("class order_book:\n    pass\n").conventions["class"], 0.0)

    def test_class_names_do_not_pollute_the_naming_histogram(self):
        """The regression this split exists to prevent."""
        vibe = self.one("class OrderBook:\n    def total_value(self):\n        return 1\n")
        self.assertEqual(vibe.naming.get("PascalCase", 0), 0)
        self.assertEqual(vibe.conventions["class"], 1.0)

    def test_a_camel_case_function_is_not_conforming(self):
        self.assertEqual(self.one("def totalValue():\n    return 1\n").conventions["function"], 0.0)

    def test_a_kind_with_no_instances_is_absent_rather_than_zero(self):
        """Reporting 0% would read as 'you name every class wrongly'."""
        self.assertNotIn("class", self.one("def go():\n    return 1\n").conventions)

    def test_module_constants_are_judged_but_locals_are_not(self):
        vibe = self.one("LIMIT = 5\n\ndef go():\n    counter = 0\n    return counter\n")
        self.assertEqual(vibe.conventions["constant"], 1.0)


class TestNestingDepth(ProfilerTestBase):
    def depth(self, source: str) -> int:
        return self.one(source).max_nesting

    def test_a_flat_function_has_no_nesting(self):
        self.assertEqual(self.depth("def f():\n    return 1\n"), 0)

    def test_one_branch_is_one_level(self):
        self.assertEqual(self.depth("def f(x):\n    if x:\n        return 1\n"), 1)

    def test_an_elif_chain_stays_flat(self):
        """It is nested in the AST and flat on the screen; the screen wins."""
        source = (
            "def f(x):\n"
            "    if x == 1:\n        pass\n"
            "    elif x == 2:\n        pass\n"
            "    elif x == 3:\n        pass\n"
            "    elif x == 4:\n        pass\n"
        )
        self.assertEqual(self.depth(source), 1)

    def test_a_real_else_block_is_still_one_level(self):
        source = "def f(x):\n    if x:\n        pass\n    else:\n        pass\n"
        self.assertEqual(self.depth(source), 1)

    def test_nesting_accumulates(self):
        source = (
            "def f(rows):\n"
            "    for row in rows:\n"
            "        for cell in row:\n"
            "            if cell:\n"
            "                return cell\n"
        )
        self.assertEqual(self.depth(source), 3)

    def test_a_nested_function_keeps_its_own_budget(self):
        """Its body is not the enclosing function's indentation."""
        source = (
            "def outer():\n"
            "    def inner(x):\n"
            "        if x:\n"
            "            if x > 1:\n"
            "                return 1\n"
            "    return inner\n"
        )
        self.assertEqual(self.depth(source), 2)

    def test_a_try_block_nests(self):
        source = "def f():\n    try:\n        pass\n    except ValueError:\n        pass\n"
        self.assertEqual(self.depth(source), 1)


class TestComplexityDistribution(ProfilerTestBase):
    SOURCE = (
        "def simple():\n    return 1\n\n"
        "def also_simple():\n    return 2\n\n"
        "def branchy(x):\n"
        + "".join(f"    if x == {n}:\n        return {n}\n" for n in range(12))
    )

    def test_the_median_describes_the_usual_function(self):
        self.assertEqual(self.one(self.SOURCE).median_complexity, 1.0)

    def test_the_max_still_reports_the_outlier(self):
        self.assertGreater(self.one(self.SOURCE).max_complexity, 10)

    def test_the_p90_sits_between_them(self):
        vibe = self.one(self.SOURCE)
        self.assertGreaterEqual(vibe.p90_complexity, vibe.median_complexity)
        self.assertLessEqual(vibe.p90_complexity, vibe.max_complexity)

    def test_a_codebase_with_no_functions_reports_zero_rather_than_raising(self):
        vibe = self.one("x = 1\n")
        self.assertEqual(vibe.median_complexity, 0.0)
        self.assertEqual(vibe.max_nesting, 0)


class TestNewDetectors(ProfilerTestBase):
    def has(self, source: str, pattern: str) -> bool:
        return self.one(source).patterns.get(pattern, 0) > 0

    def test_walrus(self):
        self.assertTrue(self.has("def f(x):\n    if (n := len(x)):\n        return n\n", "walrus"))

    def test_match_statement(self):
        source = "def f(x):\n    match x:\n        case 1:\n            return 1\n"
        self.assertTrue(self.has(source, "match_statement"))

    def test_dataclass(self):
        source = "from dataclasses import dataclass\n\n@dataclass\nclass P:\n    x: int\n"
        self.assertTrue(self.has(source, "dataclass"))

    def test_a_qualified_decorator_counts_the_same(self):
        source = "import dataclasses\n\n@dataclasses.dataclass\nclass P:\n    x: int\n"
        self.assertTrue(self.has(source, "dataclass"))

    def test_a_called_decorator_counts_the_same(self):
        source = "from dataclasses import dataclass\n\n@dataclass(frozen=True)\nclass P:\n    x: int\n"
        self.assertTrue(self.has(source, "dataclass"))

    def test_enumerate_and_zip(self):
        source = "def f(a, b):\n    for i, x in enumerate(a):\n        pass\n    return list(zip(a, b))\n"
        self.assertTrue(self.has(source, "enumerate"))
        self.assertTrue(self.has(source, "zip"))

    def test_a_generator_function(self):
        self.assertTrue(self.has("def f(xs):\n    for x in xs:\n        yield x\n", "generator_function"))

    def test_a_yield_in_a_closure_does_not_make_the_outer_a_generator(self):
        """`_own_body` exists for exactly this."""
        source = "def outer(xs):\n    def inner():\n        yield 1\n    return inner\n"
        self.assertLess(self.one(source).patterns.get("generator_function", 0), 1.0)

    def test_percent_formatting(self):
        self.assertTrue(self.has('def f(x):\n    return "%s" % x\n', "percent_format"))

    def test_arithmetic_modulo_is_not_formatting(self):
        self.assertFalse(self.has("def f(x):\n    return x % 7\n", "percent_format"))

    def test_str_format(self):
        self.assertTrue(self.has('def f(x):\n    return "{}".format(x)\n', "str_format"))

    def test_a_format_method_on_an_object_is_not_str_format(self):
        self.assertFalse(self.has("def f(log, x):\n    return log.format(x)\n", "str_format"))

    def test_star_args(self):
        self.assertTrue(self.has("def f(*args, **kw):\n    return 1\n", "star_args"))

    def test_keyword_only_args(self):
        self.assertTrue(self.has("def f(a, *, b):\n    return 1\n", "keyword_only_args"))

    def test_property_and_static_method(self):
        source = (
            "class C:\n"
            "    @property\n    def x(self):\n        return 1\n"
            "    @staticmethod\n    def y():\n        return 2\n"
        )
        self.assertTrue(self.has(source, "property"))
        self.assertTrue(self.has(source, "static_or_class_method"))

    def test_slots(self):
        self.assertTrue(self.has('class C:\n    __slots__ = ("x",)\n', "slots"))

    def test_global_statement(self):
        self.assertTrue(self.has("def f():\n    global x\n    x = 1\n", "global_statement"))

    def test_ternary(self):
        self.assertTrue(self.has("def f(x):\n    return 1 if x else 2\n", "ternary"))

    def test_nested_function(self):
        self.assertTrue(self.has("def f():\n    def g():\n        return 1\n    return g\n", "nested_function"))

    def test_the_original_detectors_still_fire(self):
        """The dispatch-table refactor must not have dropped anything."""
        source = (
            "import json\n"
            "from collections import Counter\n\n"
            "class Thing:\n    pass\n\n"
            "def f(xs) -> list:\n"
            '    """Doc."""\n'
            "    try:\n"
            "        with open('x') as fh:\n"
            "            pass\n"
            "    except ValueError:\n"
            "        pass\n"
            "    return [x for x in xs if x]\n"
        )
        vibe = self.one(source)
        for pattern in ("class", "comprehension", "context_manager",
                        "try_except", "type_hints"):
            with self.subTest(pattern=pattern):
                self.assertGreater(vibe.patterns.get(pattern, 0), 0)
        self.assertIn("json", vibe.libraries)
        self.assertIn("collections", vibe.libraries)
        self.assertEqual(vibe.exceptions_caught.get("ValueError"), 1)


class TestCommentDensity(ProfilerTestBase):
    def test_comments_are_counted_separately_from_code(self):
        vibe = self.one("# a note\n# another\nx = 1\ny = 2\n")
        self.assertAlmostEqual(vibe.comment_density, 0.5, places=2)

    def test_a_file_with_no_comments_is_zero(self):
        self.assertEqual(self.one("x = 1\n").comment_density, 0.0)

    def test_comments_are_not_counted_as_code_lines(self):
        self.assertEqual(self.one("# only a comment\nx = 1\n").code_lines, 1)


class TestStyleSignature(ProfilerTestBase):
    """The sentence a player actually reads. It has to discriminate."""

    TYPED = (
        "def a(x: int) -> int:\n"
        '    """Doc."""\n'
        "    return [n for n in range(x)]\n\n"
        "def b(y: str) -> str:\n"
        '    """Doc."""\n'
        "    return y\n"
    )
    UNTYPED_DEEP = (
        "def a(rows):\n"
        "    for r in rows:\n"
        "        for c in r:\n"
        "            if c:\n"
        "                for d in c:\n"
        "                    return d\n"
    )

    def test_a_typed_codebase_says_so(self):
        self.assertIn("strongly typed", style_signature(self.one(self.TYPED)))

    def test_an_untyped_codebase_says_so(self):
        self.assertIn("untyped", style_signature(self.one(self.UNTYPED_DEEP)))

    def test_deep_nesting_is_reported(self):
        traits = style_signature(self.one(self.UNTYPED_DEEP), limit=99)
        self.assertIn("deeply nested", traits)

    def test_the_two_codebases_do_not_share_a_signature(self):
        self.assertNotEqual(
            style_signature(self.one(self.TYPED)),
            style_signature(self.one(self.UNTYPED_DEEP)),
        )

    def test_the_signature_is_capped(self):
        self.assertLessEqual(len(style_signature(self.one(self.TYPED), limit=2)), 2)

    def test_an_empty_codebase_does_not_raise(self):
        self.assertIsInstance(style_signature(self.one("")), list)

    def test_no_trait_contains_a_comma(self):
        """They are joined for display, so a comma would read as two traits."""
        from vibecoder.profiler import SIGNATURE_RULES

        for label, _ in SIGNATURE_RULES:
            with self.subTest(label=label):
                self.assertNotIn(",", label)


if __name__ == "__main__":
    unittest.main()
