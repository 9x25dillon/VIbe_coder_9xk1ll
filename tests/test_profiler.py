"""The Vibe Profiler drives every personalisation decision, so its extraction
has to be right on small, hand-checkable inputs."""

import tempfile
import unittest
from pathlib import Path

from vibecoder.models import VibeVector
from vibecoder.profiler import derive_tags, profile_path, recommend

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


if __name__ == "__main__":
    unittest.main()
