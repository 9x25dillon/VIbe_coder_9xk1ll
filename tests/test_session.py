"""Progression state must survive crashes, corruption and hand editing."""

import json
import tempfile
import unittest
from pathlib import Path

from vibecoder.daily import Attempt
from vibecoder.mastery import TagMastery
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


class TestMasteryIsPersisted(SessionTestBase):
    """T4 W1. Mastery lives beside the Vibe Vector, never merged into it."""

    def test_a_fresh_profile_has_an_empty_mastery_model(self):
        self.assertEqual(len(self.session().mastery), 0)

    def test_mastery_survives_a_save_and_load(self):
        session = self.session()
        session.mastery.tags["recursion"] = TagMastery(
            value=0.2, observations=4, updated_at="2026-09-08T00:00:00+00:00"
        )
        session.save()

        again = Session.load(self.path)
        self.assertEqual(again.mastery.value("recursion"), 0.2)
        self.assertEqual(again.mastery["recursion"].observations, 4)
        self.assertTrue(again.mastery.confident("recursion"))

    def test_mastery_and_the_vibe_vector_are_separate_keys(self):
        """T4 exit criterion 8 forbids blending habits with mastery. Two keys
        are harder to average by accident than two entries in one dict."""
        session = self.session()
        session.vibe = VibeVector(files=3)
        session.mastery.tags["loops"] = TagMastery(value=0.8, observations=3)
        session.save()

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("mastery", raw)
        self.assertIn("vibe", raw)
        self.assertNotIn("mastery", raw["vibe"])

    def test_a_profile_written_before_mastery_existed_still_loads(self):
        self.path.write_text(json.dumps({"version": 1, "levels": {}}), encoding="utf-8")
        self.assertEqual(len(Session.load(self.path).mastery), 0)


class TestAProfileFromANewerBuild(SessionTestBase):
    """The envelope's forward compatibility, which `VibeVector` has had since
    S015 and `Session` did not (M47).

    An old build loading a new profile dropped every top-level key it had
    never heard of, then re-saved without them -- silently, on an ordinary
    `vibecoder status`. Adding `mastery` is what turned that from theoretical
    into a player losing their progress by opening the game.
    """

    def test_an_unknown_top_level_key_survives_a_round_trip(self):
        self.path.write_text(json.dumps({
            "version": 1, "levels": {}, "abilities": {"refill": 2},
        }), encoding="utf-8")

        Session.load(self.path).save()

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["abilities"], {"refill": 2})

    def test_an_unknown_key_survives_repeated_round_trips(self):
        """Once is luck; the failure being guarded is a player using two
        builds alternately for weeks."""
        self.path.write_text(json.dumps({
            "version": 1, "levels": {}, "abilities": {"refill": 2},
        }), encoding="utf-8")
        for _ in range(4):
            Session.load(self.path).save()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["abilities"], {"refill": 2})

    def test_a_known_key_is_never_overridden_by_a_preserved_one(self):
        """`unknown` is what could not be interpreted, not an override. If a
        future key ever collides with one this build owns, this build wins."""
        session = self.session()
        session.unknown = {"total_score": 999.0, "genuinely_new": 1}
        session.total_score = 12.0
        session.save()

        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["total_score"], 12.0)
        self.assertEqual(raw["genuinely_new"], 1)

    def test_preserved_keys_do_not_leak_into_mastery_or_levels(self):
        self.path.write_text(json.dumps({
            "version": 1, "levels": {}, "abilities": {"refill": 2},
        }), encoding="utf-8")
        session = Session.load(self.path)
        self.assertEqual(len(session.mastery), 0)
        self.assertEqual(session.levels, {})
        self.assertEqual(session.unknown, {"abilities": {"refill": 2}})


class TestSubmitMovesMastery(SessionTestBase):
    """T4 W3. Mastery is updated where a run is banked, and nowhere else."""

    def good(self):
        return ScoreBreakdown(
            accuracy=100.0, speed=100.0, functional=100.0,
            subtotal=100.0, total=100.0, stars=3, bonuses={"first_try": 0.1},
        )

    def bad(self):
        return ScoreBreakdown(
            accuracy=20.0, speed=0.0, functional=10.0,
            subtotal=15.0, total=15.0, stars=0, bonuses={},
        )

    def test_a_banked_clear_raises_every_tag_the_level_carries(self):
        session = self.session()
        session.submit("w2-l2-groupby", self.good(), seed=1,
                       tags=("data", "tabular"))
        self.assertGreater(session.mastery.value("data"), 0.5)
        self.assertGreater(session.mastery.value("tabular"), 0.5)

    def test_a_banked_failure_lowers_it(self):
        session = self.session()
        session.submit("x", self.bad(), seed=1, tags=("data",))
        self.assertLess(session.mastery.value("data"), 0.5)

    def test_submitting_without_tags_moves_nothing(self):
        session = self.session()
        session.submit("x", self.good(), seed=1)
        self.assertEqual(len(session.mastery), 0)

    def test_the_outcome_reports_what_moved(self):
        session = self.session()
        outcome = session.submit("x", self.good(), seed=1, tags=("data",))
        self.assertIn("mastery_moved", outcome)
        self.assertIn("data", outcome["mastery_moved"])

    def test_the_update_is_stamped_with_a_time(self):
        session = self.session()
        session.submit("x", self.good(), seed=1, tags=("data",))
        self.assertTrue(session.mastery["data"].updated_at)

    def test_mastery_survives_being_saved_after_a_submit(self):
        session = self.session()
        session.submit("x", self.good(), seed=1, tags=("data",))
        session.save()
        self.assertGreater(Session.load(self.path).mastery.value("data"), 0.5)


class TestPracticeCannotMoveMastery(SessionTestBase):
    """T4 exit criterion 5, enforced structurally rather than by a flag.

    `cmd_play` skips `submit` entirely when there is no honest solve time --
    the same decision that drops the Speed axis (M1 in S001). Mastery is
    updated inside `submit`, so "practice does not move mastery" is a
    consequence of that one branch rather than a second rule somebody has to
    remember. These tests pin the property the branch relies on.
    """

    def test_nothing_but_submit_writes_mastery(self):
        """If another method learns to move mastery, criterion 5 stops being
        structural and this test is where that gets noticed."""
        import inspect

        from vibecoder import session as session_module

        source = inspect.getsource(session_module.Session)
        writers = [
            line.strip() for line in source.splitlines()
            if "self.mastery.observe" in line
        ]
        self.assertEqual(len(writers), 1, writers)

    def test_the_only_writer_is_inside_submit(self):
        import inspect

        from vibecoder import session as session_module

        self.assertIn(
            "self.mastery.observe",
            inspect.getsource(session_module.Session.submit),
        )

    def test_a_session_that_never_submits_has_untouched_mastery(self):
        session = self.session()
        session.record("x")
        session.next_seed("x")
        session.recompute_total()
        session.save()
        self.assertEqual(len(Session.load(self.path).mastery), 0)


class TestDailyHistory(SessionTestBase):
    """T5 W2. What was played is recorded, and the first run is the ranked one."""

    def score(self, total: float, stars: int = 3) -> ScoreBreakdown:
        return ScoreBreakdown(total=total, stars=stars)

    def test_a_fresh_profile_has_no_dailies(self):
        self.assertEqual(self.session().dailies, [])

    def test_the_first_run_of_a_date_is_ranked(self):
        session = self.session()
        entry = session.record_daily("2026-09-08", "w1-l2-bigger", 431691,
                                     self.score(88.0))
        self.assertTrue(entry.ranked)

    def test_a_replay_is_recorded_but_not_ranked(self):
        """A daily is one shot at the same problem as everyone else. The
        replay happened, so it is kept; it just does not count."""
        session = self.session()
        session.record_daily("2026-09-08", "w1-l2-bigger", 431691, self.score(88.0))
        replay = session.record_daily("2026-09-08", "w1-l2-bigger", 431691,
                                      self.score(99.0))
        self.assertFalse(replay.ranked)
        self.assertEqual(len(session.dailies), 2)

    def test_a_better_replay_does_not_replace_the_ranked_score(self):
        session = self.session()
        session.record_daily("2026-09-08", "w1-l2-bigger", 431691, self.score(88.0))
        session.record_daily("2026-09-08", "w1-l2-bigger", 431691, self.score(99.0))
        self.assertEqual(session.daily_played("2026-09-08").total, 88.0)

    def test_a_different_date_is_ranked_again(self):
        session = self.session()
        session.record_daily("2026-09-08", "a", 1, self.score(88.0))
        self.assertTrue(session.record_daily("2026-09-09", "b", 2,
                                             self.score(70.0)).ranked)

    def test_dailies_survive_a_save_and_load(self):
        session = self.session()
        session.record_daily("2026-09-08", "w1-l2-bigger", 431691, self.score(88.0))
        session.save()

        again = Session.load(self.path)
        self.assertEqual(len(again.dailies), 1)
        self.assertEqual(again.dailies[0].level_id, "w1-l2-bigger")
        self.assertEqual(again.dailies[0].seed, 431691)

    def test_an_unrecognised_field_in_a_stored_daily_is_dropped(self):
        self.path.write_text(json.dumps({
            "version": 1, "levels": {},
            "dailies": [{"date": "2026-09-08", "level_id": "a", "seed": 1,
                         "total": 5.0, "stars": 1, "from_the_future": 9}],
        }), encoding="utf-8")
        self.assertEqual(len(Session.load(self.path).dailies), 1)

    def test_a_malformed_daily_entry_is_skipped_rather_than_fatal(self):
        self.path.write_text(json.dumps({
            "version": 1, "levels": {},
            "dailies": ["not a dict", {"no_date": True},
                        {"date": "2026-09-08", "level_id": "a", "seed": 1,
                         "total": 5.0, "stars": 1}],
        }), encoding="utf-8")
        self.assertEqual(len(Session.load(self.path).dailies), 1)

    def test_a_profile_written_before_dailies_existed_still_loads(self):
        self.path.write_text(json.dumps({"version": 1, "levels": {}}),
                             encoding="utf-8")
        self.assertEqual(Session.load(self.path).dailies, [])

    def test_dailies_are_a_top_level_key_the_envelope_knows(self):
        """M47: an unknown key is preserved, but a known one must not be
        treated as unknown and duplicated."""
        session = self.session()
        session.record_daily("2026-09-08", "a", 1, self.score(5.0))
        session.save()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIn("dailies", raw)
        self.assertEqual(Session.load(self.path).unknown, {})


if __name__ == "__main__":
    unittest.main()
