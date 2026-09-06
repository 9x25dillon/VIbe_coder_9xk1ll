"""Ingestion budgets: what a huge codebase costs before we stop looking.

The distinction under test is between two verdicts that look similar and are
not. An archive that is *hostile* is refused, and that is `test_ingest`'s
subject. A codebase that is merely *enormous* is profiled as far as the budget
goes and the result says so — refusing it would be the worse failure, because
20,000 files is an ample sample of how somebody writes and the alternative is
telling them their code is too big to look at.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from vibecoder.models import VibeVector
from vibecoder.profiler import (
    DEFAULT_BUDGET,
    ProfileBudget,
    iter_python_files,
    profile_path,
    profile_sources,
    walk_python_files,
)

MODULE = "def f(x: int) -> int:\n    return x + 1\n"


class TreeTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, relative: str, text: str = MODULE) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def tree(self, count: int, *, prefix: str = "pkg") -> None:
        for i in range(count):
            self.write(f"{prefix}{i // 200}/mod{i}.py")


# --------------------------------------------------------------------------
# The walk
# --------------------------------------------------------------------------

class TestTheWalkPrunes(TreeTestBase):
    def test_vendored_directories_are_never_descended_into(self):
        """Not "found and then filtered" -- never entered.

        `rglob("*.py")` walks all of `node_modules` and discards what it
        found, which on a real repository is most of the walk. The walk is the
        part that has to not hang, so this asserts the directory is never
        visited at all rather than merely absent from the result.
        """
        self.write("src/real.py")
        self.write("node_modules/pkg/vendored.py")
        self.write(".git/hooks/hook.py")

        visited = []
        real_walk = os.walk

        def spy(top, *args, **kwargs):
            for entry in real_walk(top, *args, **kwargs):
                visited.append(entry[0])
                yield entry

        with mock.patch("vibecoder.profiler.os.walk", spy):
            found = list(iter_python_files(self.root))

        self.assertEqual([p.name for p in found], ["real.py"])
        self.assertFalse([v for v in visited if "node_modules" in v], visited)
        self.assertFalse([v for v in visited if ".git" in v], visited)

    def test_the_order_is_deterministic(self):
        """A truncated profile must see the same files on every run.

        Otherwise the same repository profiles differently twice, and the
        difference is filesystem order rather than anything about the code.
        """
        self.tree(40)
        self.assertEqual(list(iter_python_files(self.root)),
                         list(iter_python_files(self.root)))

    def test_a_symlink_loop_does_not_hang_the_walk(self):
        self.write("src/real.py")
        try:
            (self.root / "src" / "loop").symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable here")
        found, stopped = walk_python_files(self.root)
        self.assertEqual([p.name for p in found], ["real.py"])
        self.assertEqual(stopped, "")

    def test_a_walk_past_its_path_budget_stops_and_says_so(self):
        self.tree(30)
        found, stopped = walk_python_files(
            self.root, budget=ProfileBudget(max_walk_files=10)
        )
        self.assertEqual(len(found), 10)
        self.assertIn("walk budget", stopped)

    def test_a_walk_past_its_deadline_stops_and_says_so(self):
        self.tree(30)
        found, stopped = walk_python_files(
            self.root, budget=ProfileBudget(max_seconds=5.0),
            deadline=time.monotonic() - 1,
        )
        self.assertIn("time budget", stopped)
        self.assertLess(len(found), 30)

    def test_a_walk_within_budget_reports_no_reason(self):
        self.tree(10)
        found, stopped = walk_python_files(self.root)
        self.assertEqual(len(found), 10)
        self.assertEqual(stopped, "")


# --------------------------------------------------------------------------
# The budget
# --------------------------------------------------------------------------

class TestTheBudgetTruncates(TreeTestBase):
    def test_a_file_budget_stops_the_profile_and_flags_it(self):
        self.tree(30)
        vibe = profile_path(self.root, budget=ProfileBudget(max_files=10))
        self.assertTrue(vibe.partial)
        self.assertIn("file budget", vibe.partial_reason)
        self.assertEqual(vibe.files, 10)
        self.assertEqual(vibe.files_seen, 30)

    def test_a_size_budget_stops_the_profile_and_flags_it(self):
        self.tree(30)
        vibe = profile_path(self.root, budget=ProfileBudget(max_total_bytes=100))
        self.assertTrue(vibe.partial)
        self.assertIn("size budget", vibe.partial_reason)
        self.assertLess(vibe.files, 30)

    def test_a_time_budget_stops_the_profile_and_flags_it(self):
        self.tree(30)
        vibe = profile_path(self.root, budget=ProfileBudget(max_seconds=-1.0))
        self.assertTrue(vibe.partial)
        self.assertIn("time budget", vibe.partial_reason)

    def test_the_budget_is_checked_before_the_work_not_after(self):
        """A budget that notices it was exceeded has already spent what it was
        meant to save."""
        self.tree(30)
        vibe = profile_path(self.root, budget=ProfileBudget(max_files=10))
        self.assertEqual(vibe.files, 10)

    def test_a_complete_profile_is_never_flagged(self):
        self.tree(10)
        vibe = profile_path(self.root)
        self.assertFalse(vibe.partial)
        self.assertEqual(vibe.partial_reason, "")
        self.assertEqual(vibe.files_seen, vibe.files)

    def test_no_budget_means_no_truncation(self):
        pairs = [(f"m{i}.py", MODULE) for i in range(100)]
        vibe = profile_sources(pairs)
        self.assertEqual(vibe.files, 100)
        self.assertFalse(vibe.partial)

    def test_a_partial_vector_still_describes_real_code(self):
        """The point of banking it: a smaller sample, not a wrong one."""
        self.tree(30)
        vibe = profile_path(self.root, budget=ProfileBudget(max_files=5))
        self.assertTrue(vibe.partial)
        self.assertEqual(vibe.functions, 5)
        self.assertGreater(vibe.patterns.get("type_hints", 0), 0)

    def test_a_walk_truncation_is_carried_into_the_vector(self):
        """The walk stopping and the analysis stopping are the same verdict to
        a reader, and both have to reach the result."""
        self.tree(30)
        vibe = profile_path(self.root, budget=ProfileBudget(max_walk_files=8))
        self.assertTrue(vibe.partial)
        self.assertIn("walk budget", vibe.partial_reason)
        self.assertEqual(vibe.files, 8)

    def test_files_seen_is_never_below_files_profiled(self):
        self.tree(30)
        for budget in (ProfileBudget(max_files=7), ProfileBudget(max_walk_files=7),
                       DEFAULT_BUDGET):
            with self.subTest(budget=budget):
                vibe = profile_path(self.root, budget=budget)
                self.assertGreaterEqual(vibe.files_seen, vibe.files)

    def test_an_unparseable_file_does_not_make_a_profile_partial(self):
        """Partial means "we stopped looking", not "something was unusable".

        A repository with one Python 2 file in it is completely profiled; it
        just has one file's less signal.
        """
        self.tree(5)
        self.write("broken.py", "def (:\n")
        vibe = profile_path(self.root)
        self.assertFalse(vibe.partial)
        self.assertEqual(vibe.files, 5)


# --------------------------------------------------------------------------
# T2 exit criterion 6
# --------------------------------------------------------------------------

class TestExitCriterionSix(TreeTestBase):
    """"Profiling a 5,000-file repository completes within its budget or
    returns a partial profile flagged as partial. It does not hang."

    It completes. The realistic-content measurement is in S014: a 5,000-file,
    6.6 MB tree profiles in 11.7 seconds against a 60 second budget. This test
    uses small files so the suite does not pay twelve seconds to assert it.
    """

    def test_a_five_thousand_file_repository_completes(self):
        self.tree(5000)
        started = time.monotonic()
        vibe = profile_path(self.root)
        elapsed = time.monotonic() - started

        self.assertFalse(vibe.partial, vibe.partial_reason)
        self.assertEqual(vibe.files, 5000)
        self.assertLess(elapsed, DEFAULT_BUDGET.max_seconds)

    def test_the_same_repository_under_a_small_budget_degrades_rather_than_hangs(self):
        self.tree(5000)
        vibe = profile_path(self.root, budget=ProfileBudget(max_files=250))
        self.assertTrue(vibe.partial)
        self.assertEqual(vibe.files, 250)
        self.assertEqual(vibe.files_seen, 5000)


# --------------------------------------------------------------------------
# What gets stored
# --------------------------------------------------------------------------

class TestTheStoredVector(unittest.TestCase):
    def test_the_new_fields_survive_a_round_trip(self):
        vibe = VibeVector(files=12, partial=True, partial_reason="time budget: 60s",
                          files_seen=900)
        again = VibeVector.from_json(vibe.to_json())
        self.assertTrue(again.partial)
        self.assertEqual(again.partial_reason, "time budget: 60s")
        self.assertEqual(again.files_seen, 900)

    def test_a_profile_written_before_these_fields_still_loads(self):
        """Old profiles predate the fields and are always complete, so the
        defaults are the truth for them rather than a guess."""
        old = {"files": 40, "functions": 100, "code_lines": 900}
        vibe = VibeVector.from_json(old)
        self.assertFalse(vibe.partial)
        self.assertEqual(vibe.partial_reason, "")
        self.assertEqual(vibe.files_seen, 0)

    def test_the_reason_is_empty_exactly_when_the_profile_is_complete(self):
        self.assertEqual(VibeVector().partial_reason, "")
        self.assertFalse(VibeVector().partial)


if __name__ == "__main__":
    unittest.main()
