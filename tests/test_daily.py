"""The daily challenge. T5 W1.

Exit criterion 1: *two machines given the same date generate a byte-identical
daily challenge.* Two machines cannot be had in a unit test, so the property
is checked the two ways that can be: the selection is a pure function of
inputs a second machine would also have, and it is re-derived in **separate
interpreter processes** — which is where `hash()` would have failed, since
Python randomises it per process.
"""

import subprocess
import sys
import unittest
from pathlib import Path

from vibecoder.daily import SEED_MODULUS, Daily, choose, digest
from vibecoder.levels import all_levels

REPO = Path(__file__).resolve().parent.parent
IDS = [level.id for level in all_levels()]
DATES = [f"2026-{month:02d}-{day:02d}"
         for month in range(1, 13) for day in (1, 9, 17, 25)]


class TestTheDigestIsStable(unittest.TestCase):
    """The trap the waypoint's own wording walks into."""

    def test_the_digest_is_the_same_in_another_process(self):
        here = digest("2026-09-08").hex()
        there = subprocess.run(
            [sys.executable, "-c",
             "from vibecoder.daily import digest;"
             "print(digest('2026-09-08').hex())"],
            capture_output=True, text=True, cwd=REPO, check=True,
        ).stdout.strip()
        self.assertEqual(here, there)

    def test_builtin_hash_would_not_have_been(self):
        """Documented as a test because the waypoint says `hash(date)`, and a
        future reader deserves to see why it does not.

        Python randomises `str` hashing per process unless PYTHONHASHSEED is
        pinned, so `hash` cannot manage two invocations on one machine, let
        alone two machines.
        """
        seen = {
            subprocess.run(
                [sys.executable, "-c", "print(hash('2026-09-08'))"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            for _ in range(4)
        }
        self.assertGreater(len(seen), 1)

    def test_different_dates_digest_differently(self):
        self.assertNotEqual(digest("2026-09-08"), digest("2026-09-09"))


class TestCriterionOne(unittest.TestCase):
    """Two machines, the same date, a byte-identical challenge."""

    def test_a_second_process_derives_the_same_daily(self):
        mine = choose("2026-09-08", IDS)
        theirs = subprocess.run(
            [sys.executable, "-c",
             "from vibecoder.daily import choose;"
             "from vibecoder.levels import all_levels;"
             "d = choose('2026-09-08', [l.id for l in all_levels()]);"
             "print(f'{d.date}|{d.level_id}|{d.seed}')"],
            capture_output=True, text=True, cwd=REPO, check=True,
        ).stdout.strip()
        self.assertEqual(f"{mine.date}|{mine.level_id}|{mine.seed}", theirs)

    def test_it_is_stable_across_every_date_tried(self):
        first = [choose(day, IDS) for day in DATES]
        second = [choose(day, IDS) for day in DATES]
        self.assertEqual(first, second)

    def test_registry_order_cannot_change_what_everyone_plays(self):
        """The ids are sorted before indexing, so an ordering bug elsewhere
        cannot silently move today's challenge."""
        for day in DATES[:12]:
            with self.subTest(date=day):
                self.assertEqual(choose(day, IDS),
                                 choose(day, list(reversed(IDS))))


class TestTheSelection(unittest.TestCase):
    def test_it_picks_a_level_that_exists(self):
        for day in DATES:
            with self.subTest(date=day):
                self.assertIn(choose(day, IDS).level_id, IDS)

    def test_the_seed_is_in_range(self):
        for day in DATES:
            with self.subTest(date=day):
                seed = choose(day, IDS).seed
                self.assertGreaterEqual(seed, 0)
                self.assertLess(seed, SEED_MODULUS)

    def test_consecutive_days_usually_differ(self):
        """A daily that repeated would be a bug nobody noticed for a week."""
        picks = [choose(day, IDS) for day in DATES]
        self.assertGreater(len({(p.level_id, p.seed) for p in picks}),
                           len(picks) * 0.9)

    def test_the_level_and_the_seed_are_independent(self):
        """Two dates landing on the same level should not thereby land on the
        same variant -- they are drawn from different bytes of the digest."""
        by_level: dict[str, set] = {}
        for day in DATES:
            pick = choose(day, IDS)
            by_level.setdefault(pick.level_id, set()).add(pick.seed)
        repeated = [seeds for seeds in by_level.values() if len(seeds) > 1]
        self.assertTrue(repeated)

    def test_every_level_comes_up_eventually(self):
        """A level the daily can never pick is content nobody sees."""
        picked = {choose(day, IDS).level_id for day in DATES}
        self.assertGreater(len(picked), len(IDS) * 0.5)

    def test_an_empty_catalogue_gives_nothing_rather_than_raising(self):
        self.assertIsNone(choose("2026-09-08", []))

    def test_a_single_level_catalogue_always_picks_it(self):
        self.assertEqual(choose("2026-09-08", ["only"]).level_id, "only")

    def test_a_daily_is_frozen(self):
        with self.assertRaises(Exception):
            choose("2026-09-08", IDS).seed = 1

    def test_a_daily_carries_no_difficulty(self):
        """The same puzzle for everyone cannot be adapted to anyone. T4's
        selection policy is bypassed here on purpose, and the absence of the
        field is the enforcement."""
        self.assertNotIn("difficulty", Daily.__dataclass_fields__)


if __name__ == "__main__":
    unittest.main()
