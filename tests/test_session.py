"""Progression state must survive crashes, corruption and hand editing."""

import json
import tempfile
import unittest
from pathlib import Path

from vibecoder.models import ScoreBreakdown, VibeVector
from vibecoder.session import Session


def breakdown(total: float, stars: int) -> ScoreBreakdown:
    return ScoreBreakdown(
        accuracy=100.0, speed=100.0, functional=100.0,
        subtotal=total, total=total, stars=stars,
    )


class SessionTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "profile.json"

    def session(self) -> Session:
        return Session.load(self.path)


class TestPersistence(SessionTestBase):
    def test_a_missing_profile_starts_fresh(self):
        session = self.session()
        self.assertEqual(session.total_score, 0.0)
        self.assertEqual(session.levels, {})

    def test_state_round_trips(self):
        session = self.session()
        session.vibe = VibeVector(files=3, tags=["data"])
        session.vibe_source = "/somewhere"
        session.submit("lvl", breakdown(90.0, 2), seed=1)
        session.save()

        reloaded = self.session()
        self.assertEqual(reloaded.vibe.files, 3)
        self.assertEqual(reloaded.vibe.tags, ["data"])
        self.assertEqual(reloaded.vibe_source, "/somewhere")
        self.assertEqual(reloaded.levels["lvl"].best_total, 90.0)

    def test_a_corrupt_profile_is_set_aside_not_destroyed(self):
        self.path.write_text("{not json at all", encoding="utf-8")
        session = self.session()
        self.assertEqual(session.levels, {})
        salvaged = list(self.path.parent.glob("profile.corrupt-*.json"))
        self.assertEqual(len(salvaged), 1)

    def test_saving_is_atomic(self):
        session = self.session()
        session.submit("lvl", breakdown(50.0, 1), seed=1)
        session.save()
        # No stray temp file is left behind to be picked up as state.
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])
        json.loads(self.path.read_text())


class TestScoring(SessionTestBase):
    def test_only_an_improvement_replaces_the_best(self):
        session = self.session()
        session.submit("lvl", breakdown(90.0, 3), seed=1)
        outcome = session.submit("lvl", breakdown(40.0, 1), seed=2)
        self.assertFalse(outcome["improved"])
        self.assertEqual(session.levels["lvl"].best_total, 90.0)
        self.assertEqual(session.levels["lvl"].best_stars, 3)

    def test_attempts_and_clears_are_counted_separately(self):
        session = self.session()
        session.submit("lvl", breakdown(0.0, 0), seed=1)
        session.submit("lvl", breakdown(70.0, 1), seed=2)
        record = session.levels["lvl"]
        self.assertEqual(record.attempts, 2)
        self.assertEqual(record.clears, 1)

    def test_the_global_total_applies_world_multipliers(self):
        session = self.session()
        session.submit("w1", breakdown(100.0, 3), seed=1, multipliers={"w1": 1.0})
        session.submit(
            "w2", breakdown(100.0, 3), seed=1, multipliers={"w1": 1.0, "w2": 1.5}
        )
        self.assertAlmostEqual(session.total_score, 250.0)

    def test_an_unknown_level_multiplier_defaults_to_one(self):
        session = self.session()
        session.submit("lvl", breakdown(80.0, 2), seed=1, multipliers={})
        self.assertAlmostEqual(session.total_score, 80.0)

    def test_replaying_never_lowers_the_banked_total(self):
        session = self.session()
        session.submit("lvl", breakdown(100.0, 3), seed=1)
        high = session.total_score
        session.submit("lvl", breakdown(10.0, 0), seed=2)
        self.assertAlmostEqual(session.total_score, high)


class TestStreak(SessionTestBase):
    def test_perfect_clears_extend_the_streak(self):
        session = self.session()
        session.submit("a", breakdown(100.0, 3), seed=1)
        outcome = session.submit("b", breakdown(100.0, 3), seed=1)
        self.assertEqual(outcome["streak"], 2)
        self.assertAlmostEqual(outcome["streak_multiplier"], 1.2)

    def test_anything_short_of_perfect_resets_it(self):
        session = self.session()
        session.submit("a", breakdown(100.0, 3), seed=1)
        outcome = session.submit("b", breakdown(85.0, 2), seed=1)
        self.assertEqual(outcome["streak"], 0)


class TestVariants(SessionTestBase):
    def test_seeds_advance_so_replays_are_new(self):
        session = self.session()
        first = session.next_seed("lvl")
        session.submit("lvl", breakdown(50.0, 1), seed=first)
        self.assertNotEqual(session.next_seed("lvl"), first)

    def test_played_seeds_are_remembered(self):
        session = self.session()
        session.submit("lvl", breakdown(50.0, 1), seed=4)
        session.submit("lvl", breakdown(50.0, 1), seed=4)
        self.assertEqual(session.levels["lvl"].seeds_played, [4])

    def test_history_is_capped_when_saved(self):
        session = self.session()
        for i in range(30):
            session.submit("lvl", breakdown(float(i), 1), seed=i)
        session.save()
        reloaded = self.session()
        self.assertEqual(len(reloaded.levels["lvl"].history), 20)


class TestRunArtifacts(SessionTestBase):
    def test_a_run_round_trips(self):
        session = self.session()
        run_id = session.save_run("lvl", {"code": "x = 1", "seed": 3})
        self.assertEqual(session.load_run(run_id)["code"], "x = 1")
        self.assertIn(run_id, session.list_runs())

    def test_a_missing_run_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.session().load_run("nope")


if __name__ == "__main__":
    unittest.main()
