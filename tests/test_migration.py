"""Vibe Vector versioning: profiles have to survive the schema changing.

The vector has gained fields in three separate sessions and will gain more.
Two directions of failure matter, and only one of them is the obvious one.

*Backward* — an old profile read by this build — was already survivable by
accident, because every field has a default. *Forward* — a profile written by
a **newer** build and read by this one — was silently destructive: unknown keys
were dropped on load, so an ordinary `vibecoder status` would load, re-save,
and permanently delete whatever the newer build had recorded.
"""

import unittest

from vibecoder.models import (
    VECTOR_MIGRATIONS,
    VECTOR_VERSION,
    VibeVector,
    migrate_vector,
)

#: A version 1 profile: what the vector looked like before any of the style
#: fields, the partial fields, or the version field existed.
VERSION_ONE = {
    "files": 40,
    "functions": 210,
    "code_lines": 3100,
    "libraries": {"requests": 9},
    "patterns": {"comprehension": 0.62},
    "exceptions_caught": {"KeyError": 3},
    "avg_function_lines": 14.2,
    "max_complexity": 19,
    "docstring_ratio": 0.41,
    "naming": {"snake_case": 0.93},
    "tags": ["web"],
}


class TestTheChainIsComplete(unittest.TestCase):
    """A gap at version *n* is indistinguishable from nobody thinking about it."""

    def test_every_version_below_the_current_one_has_a_migration(self):
        missing = [
            v for v in range(1, VECTOR_VERSION) if v not in VECTOR_MIGRATIONS
        ]
        self.assertEqual(missing, [], f"no migration from version(s) {missing}")

    def test_no_migration_points_past_the_current_version(self):
        """A step from the current version means VECTOR_VERSION was not bumped."""
        stray = [v for v in VECTOR_MIGRATIONS if v >= VECTOR_VERSION]
        self.assertEqual(stray, [], f"migrations from {stray} lead nowhere")

    def test_a_missing_step_fails_loudly_rather_than_guessing(self):
        with self.assertRaises(ValueError) as caught:
            migrate_vector({}, VECTOR_VERSION - 100)
        self.assertIn("no migration", str(caught.exception))


class TestReadingAnOlderProfile(unittest.TestCase):
    def test_a_version_one_profile_loads(self):
        vibe = VibeVector.from_json(VERSION_ONE)
        self.assertEqual(vibe.files, 40)
        self.assertEqual(vibe.libraries, {"requests": 9})
        self.assertEqual(vibe.tags, ["web"])

    def test_it_is_migrated_to_the_current_version(self):
        self.assertEqual(VibeVector.from_json(VERSION_ONE).version, VECTOR_VERSION)

    def test_fields_it_never_had_take_their_defaults(self):
        vibe = VibeVector.from_json(VERSION_ONE)
        self.assertEqual(vibe.conventions, {})
        self.assertEqual(vibe.comment_density, 0.0)
        self.assertFalse(vibe.partial)
        self.assertEqual(vibe.files_seen, 0)

    def test_an_absent_version_means_version_one_rather_than_unreadable(self):
        """The field was added in version 4, so its absence dates the profile."""
        self.assertNotIn("version", VERSION_ONE)
        self.assertEqual(VibeVector.from_json(VERSION_ONE).files, 40)

    def test_a_null_version_is_treated_as_version_one(self):
        vibe = VibeVector.from_json({**VERSION_ONE, "version": None})
        self.assertEqual(vibe.version, VECTOR_VERSION)

    def test_nothing_the_old_profile_held_is_dropped(self):
        back = VibeVector.from_json(VERSION_ONE).to_json()
        for key, value in VERSION_ONE.items():
            with self.subTest(field=key):
                self.assertEqual(back[key], value)

    def test_an_upgraded_profile_is_no_longer_flagged_as_newer(self):
        self.assertFalse(VibeVector.from_json(VERSION_ONE).from_a_newer_build)


class TestReadingANewerProfile(unittest.TestCase):
    """The destructive direction, and the reason `unknown` exists.

    A migration can only be written by the build that knows what a field
    means, so this build cannot migrate a future profile. What it can do is
    refuse to destroy it.
    """

    NEWER = {
        **VERSION_ONE,
        "version": VECTOR_VERSION + 2,
        "entropy": 0.87,
        "hue": "teal",
    }

    def test_the_fields_we_understand_are_still_read(self):
        vibe = VibeVector.from_json(self.NEWER)
        self.assertEqual(vibe.files, 40)
        self.assertEqual(vibe.max_complexity, 19)

    def test_fields_we_do_not_understand_are_preserved(self):
        vibe = VibeVector.from_json(self.NEWER)
        self.assertEqual(vibe.unknown, {"entropy": 0.87, "hue": "teal"})

    def test_a_round_trip_loses_nothing_at_all(self):
        """The bug this waypoint exists for: load, save, and the newer build's
        fields were gone."""
        back = VibeVector.from_json(self.NEWER).to_json()
        self.assertEqual(set(self.NEWER) - set(back), set())
        for key, value in self.NEWER.items():
            with self.subTest(field=key):
                self.assertEqual(back[key], value)

    def test_preserved_fields_come_back_flat_not_nested(self):
        """A newer build must find its fields where it left them, not in a
        quarantine bucket it would have to know to look in."""
        back = VibeVector.from_json(self.NEWER).to_json()
        self.assertEqual(back["entropy"], 0.87)
        self.assertNotIn("unknown", back.get("unknown", {}))

    def test_the_newer_version_number_is_kept(self):
        """Claiming it as ours would assert we understand fields we have never
        heard of, and re-saving would look like a downgrade."""
        vibe = VibeVector.from_json(self.NEWER)
        self.assertEqual(vibe.version, VECTOR_VERSION + 2)
        self.assertTrue(vibe.from_a_newer_build)

    def test_two_round_trips_are_still_lossless(self):
        once = VibeVector.from_json(self.NEWER).to_json()
        twice = VibeVector.from_json(once).to_json()
        self.assertEqual(once, twice)


class TestAMigrationThatActuallyChangesSomething(unittest.TestCase):
    """Every real migration so far is additive, so the machinery has never had
    to transform anything.

    That is exactly why it is worth proving now, with a synthetic step, rather
    than the first time a field genuinely moves — at which point the migration
    and the mechanism would be under test together and a failure would not say
    which one was wrong.
    """

    def setUp(self):
        self.original = dict(VECTOR_MIGRATIONS)
        self.addCleanup(lambda: VECTOR_MIGRATIONS.update(self.original))

    def test_a_transforming_step_is_applied(self):
        def rename(data):
            data["max_complexity"] = data.pop("worst_complexity", 0)
            return data

        VECTOR_MIGRATIONS[1] = rename
        vibe = VibeVector.from_json({"files": 3, "worst_complexity": 42})
        self.assertEqual(vibe.max_complexity, 42)
        self.assertNotIn("worst_complexity", vibe.unknown)

    def test_steps_are_applied_in_order_and_each_one_runs(self):
        seen = []

        def step(n):
            def run(data):
                seen.append(n)
                return data
            return run

        for version in range(1, VECTOR_VERSION):
            VECTOR_MIGRATIONS[version] = step(version)
        VibeVector.from_json(dict(VERSION_ONE))
        self.assertEqual(seen, list(range(1, VECTOR_VERSION)))

    def test_a_profile_already_current_runs_no_migration(self):
        def explode(data):
            raise AssertionError("migrated a profile that was already current")

        for version in range(1, VECTOR_VERSION):
            VECTOR_MIGRATIONS[version] = explode
        vibe = VibeVector.from_json({"files": 3, "version": VECTOR_VERSION})
        self.assertEqual(vibe.files, 3)

    def test_the_stored_profile_is_not_mutated_by_migrating_it(self):
        """Callers hold the dict they read off disk; migration must not edit it."""
        def rename(data):
            data["max_complexity"] = data.pop("worst_complexity", 0)
            return data

        VECTOR_MIGRATIONS[1] = rename
        stored = {"files": 3, "worst_complexity": 42}
        VibeVector.from_json(stored)
        self.assertEqual(stored, {"files": 3, "worst_complexity": 42})


class TestAFreshVector(unittest.TestCase):
    def test_a_new_vector_carries_the_current_version(self):
        self.assertEqual(VibeVector().version, VECTOR_VERSION)

    def test_a_new_vector_has_nothing_unknown(self):
        self.assertEqual(VibeVector().unknown, {})

    def test_a_profiled_vector_is_written_with_a_version(self):
        from vibecoder.profiler import profile_sources

        vibe = profile_sources([("m.py", "def f(x):\n    return x\n")])
        self.assertEqual(vibe.to_json()["version"], VECTOR_VERSION)


class TestItSurvivesTheSession(unittest.TestCase):
    """The round trip that actually happens: profile.json on disk."""

    def test_a_newer_profile_survives_a_session_load_and_save(self):
        import json
        import tempfile
        from pathlib import Path

        from vibecoder.session import Session

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps({
                "version": 1,
                "vibe_source": "/somewhere",
                "vibe": {"files": 40, "version": VECTOR_VERSION + 1,
                         "entropy": 0.87},
            }), encoding="utf-8")

            session = Session.load(path)
            session.save()

            stored = json.loads(path.read_text(encoding="utf-8"))["vibe"]
            self.assertEqual(stored["entropy"], 0.87)
            self.assertEqual(stored["version"], VECTOR_VERSION + 1)
            self.assertEqual(stored["files"], 40)


if __name__ == "__main__":
    unittest.main()
