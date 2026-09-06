# S015 — The direction that actually loses data

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T2 (W7) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-06-S015.json`](../data/sessions/2026-09-06-S015.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A profile written by any version loads | ✅ met |
| 2 | A profile written by a *newer* build is not destroyed by reading it | ✅ met |
| 3 | The migration chain is provably complete, not just present | ✅ met |
| 4 | The transforming path is tested before a real transform needs it | ✅ met |
| 5 | Q40 answered | ✅ met |

## What was built

### The direction that was actually broken

W7 reads as a backward-compatibility waypoint — *"the schema will change;
profiles must survive it"* — and backward compatibility turned out to already
work by accident. Every field has a default, so a version 1 profile from before
any style or budget field existed loads fine and always did.

The broken direction was the other one. `from_json` dropped unknown keys, so a
profile written by a **newer** build and read by this one lost whatever that
build had recorded — and then an ordinary `vibecoder status`, which loads and
re-saves, wrote the loss back to disk permanently. Nothing reported it:

```
wrote      : ['entropy', 'files', 'functions', 'tags']
read+saved : ['files', 'functions', 'tags']
LOST       : ['entropy']
```

A migration can only be written by the build that knows what a field means, so
this build genuinely cannot migrate a future profile. What it can do is **refuse
to destroy it**. Unknown fields are now kept verbatim in `unknown` and merged
flat again on save, so a newer build finds its fields exactly where it left them
rather than in a quarantine bucket it would have to know to look in. The profile
keeps its own higher version number too — claiming it as ours would assert we
understand fields we have never heard of, and re-saving would look like a
downgrade rather than the pass-through it is.

### The chain

`VECTOR_VERSION` is 4, and `VECTOR_MIGRATIONS` walks a stored profile forward
one step at a time rather than guessing in one leap. A profile with no `version`
**is** version 1: the field was added in version 4, so its absence dates the
profile rather than making it unreadable.

| Version | Added |
| --- | --- |
| 1 | The original vector (S001) |
| 2 | Conventions, complexity distribution, nesting, comment density (S011) |
| 3 | `partial`, `partial_reason`, `files_seen` (S014) |
| 4 | The version field, and preservation of unknown fields (this session) |

Every step so far is additive — the defaults already supply the new fields — but
each is written out rather than left implicit, because a gap at version *n* is
indistinguishable from nobody having thought about *n*. The suite checks the
chain for gaps and checks no step points past the current version. Bumping
`VECTOR_VERSION` without writing the step raises `ValueError` on load, because
failing loudly beats loading a profile whose fields mean something else.

### Testing the path nothing has taken yet

Every real migration being additive means the *transforming* path would go
untested until the first time a field genuinely moves — and at that point the
migration and the mechanism would be under test together, so a failure would not
say which was wrong. So the machinery is proved now with a synthetic renaming
step: `worst_complexity` → `max_complexity`, asserted to be applied, to run in
order, to run not at all for an already-current profile, and not to mutate the
dict the caller read off disk.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 751 tests — OK

$ python3.11 -m vibecoder.cli verify --seeds 3
36/36 reference runs clean

the bug, before:  {'entropy': 0.87} written by a newer build -> gone after a round trip
the bug, after :  round trip loses nothing; two round trips are byte-identical
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| A version 1 profile loads and migrates forward | `TestReadingAnOlderProfile`, 7 tests | verified |
| An absent version means version 1, not unreadable | `test_an_absent_version_means_version_one_rather_than_unreadable` | verified |
| Nothing an old profile held is dropped | `test_nothing_the_old_profile_held_is_dropped`, field by field | verified |
| A newer profile's unknown fields are preserved | `test_fields_we_do_not_understand_are_preserved` | verified |
| A round trip on a newer profile loses nothing | `test_a_round_trip_loses_nothing_at_all`; fails when the drop is reintroduced | verified |
| Two round trips are byte-identical | `test_two_round_trips_are_still_lossless` | verified |
| Preserved fields come back flat, not nested | `test_preserved_fields_come_back_flat_not_nested` | verified |
| A newer profile keeps its own version number | `test_the_newer_version_number_is_kept` | verified |
| The chain has no gaps | `test_every_version_below_the_current_one_has_a_migration` | verified |
| No migration points past the current version | `test_no_migration_points_past_the_current_version` | verified |
| A missing step fails loudly rather than guessing | `test_a_missing_step_fails_loudly_rather_than_guessing` | verified |
| A transforming migration is applied correctly | `TestAMigrationThatActuallyChangesSomething`, 4 tests | verified |
| Migration does not mutate the caller's dict | `test_the_stored_profile_is_not_mutated_by_migrating_it` | verified |
| A newer profile survives a real session load and save | `test_a_newer_profile_survives_a_session_load_and_save`, via `profile.json` on disk | verified |
| The preservation tests catch the regression | the drop reintroduced: 2 failures, 2 errors | verified |
| Real profiles from older VibeCoder builds load | no profile older than this session exists to test against | `UNVERIFIED` — the version 1 fixture is reconstructed, not found |

## Misconceptions and corrections

### M30 — versioning is for reading old profiles

**Believed:** W7 is backward compatibility. The vector has gained fields three
times, so the job is making sure yesterday's `profile.json` still loads, and the
version number exists to let migrations fix up old shapes.

**Revealed by:** Writing the version 1 fixture and loading it before changing
anything. It loaded perfectly — every field has a default, so the backward
direction had been safe by construction since S001, and every migration the
chain will ever contain for the history so far is an identity function.

Then trying the other direction: a profile with a field this build has never
heard of, loaded and saved, came back **without it**.

**Corrected to:** The waypoint's real content is *forward* compatibility, and
the mechanism it needs is not migration at all — it is preservation, because a
migration can only be written by the build that understands the field. The
version number is still worth having, but it earns its place by dating a
profile and by making a future non-additive change safe, not by fixing anything
that was broken.

**Cost:** ~15 minutes, and it changed what got built. Building the migration
chain alone would have satisfied the waypoint as written, passed every test I
would have thought to write, and left the actual data loss in place.

## Friction

- The doc-count check moved again (727 → 751). Counting before the final
  unpinned run, as S014's friction note said to, worked this time: the count was
  updated in the same command that started the run, and the suite was green
  first time.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D95 | Unknown fields are preserved verbatim rather than dropped | Drop them, as before; refuse to load a newer profile | A migration can only be written by the build that knows the field. Refusing to destroy it is the only honest option left to an older build | yes |
| D96 | Preserved fields are merged flat on save, not nested | Keep an `unknown` object in the JSON | A newer build must find its fields where it left them, not somewhere it would need to know to look | yes |
| D97 | A newer profile keeps its own version number | Renumber it to ours on load | Renumbering asserts we understand fields we have never heard of, and makes a re-save look like a downgrade | yes |
| D98 | An absent version means version 1 | Treat it as current | The field arrived in version 4, so its absence dates the profile. Treating it as current would skip every migration for exactly the profiles that need them | no |
| D99 | Every version gets an explicit step, even an identity one | Leave additive versions out of the table | A gap at *n* is indistinguishable from nobody having thought about *n*, and the suite checks for gaps | yes |
| D100 | A missing migration raises rather than loading | Load best-effort | A profile whose fields mean something else is worse than an error that says so | yes |
| D101 | The transforming path is tested with a synthetic migration | Wait for a real one | Otherwise the mechanism is first exercised by the first real transform, where a failure cannot say whether the migration or the machinery is wrong | yes |

## Handoff

- **State:** T2 W7 is landed. `VibeVector` carries a version, migrates forward
  through a gap-checked chain, and preserves fields from newer builds instead
  of destroying them. 751 tests green unpinned, `verify` clean on 36 reference
  runs.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **T2 is one waypoint from landing.** W1, W2, W3, W5, W6 and W7 are landed;
  **W4 is the only one left and it is externally blocked** on a registered
  OAuth application and the client-versus-server profiling decision. Exit
  criteria 1, 2, 3, 4, 6 and 7 are verified; **criterion 5 is verified only for
  the archive path** and cannot be finished until W4's clone path exists to be
  inspected. Do not mark T2 `LANDED` on six of seven waypoints.
- **Next action:** the user's call rather than the plan's. T2 cannot progress
  without the OAuth application, so the honest options are: register it and do
  W4; or start T3, whose dependency ("the execution boundary must be settled")
  is satisfied by W1–W3 and whose W1 (multi-step boss level format) needs
  nothing that is blocked.
- **Blockers:** T2 W4, on a registered OAuth application. Unchanged since S006
  and now the only thing between T2 and landing.
- **Context required:** D95 before "simplifying" the `unknown` bucket away —
  it is the whole waypoint. D98 before changing what a missing version means.
  M30 for why the obvious reading of W7 would have shipped the bug intact.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q40 | *(from S011.)* Does the vector need a version, or is defaulting enough? | T2 | **answered** — it needs one, but defaulting was never the gap: the loss was forward, not backward, and the fix is preservation (M30, D95) |
| Q56 | `Session` has its own `STATE_VERSION`, which is 1 and has no migration chain at all. The vector is now the well-behaved half of a file whose outer envelope is not. Should the session get the same treatment, and is that T2's or a new trajectory's? | T2 | open |
| Q57 | Preserved unknown fields are carried but never shown beyond a count. If a newer build recorded something a player cares about, this build silently ignores it. Is a count enough, or should `--json` surface them? | T6 | open |
| Q58 | Nothing writes version 5 yet, so the *upgrade* path across a non-additive change has only ever been exercised synthetically. The first real one should be treated as a migration to review carefully rather than a routine field addition. | T2 | open |
