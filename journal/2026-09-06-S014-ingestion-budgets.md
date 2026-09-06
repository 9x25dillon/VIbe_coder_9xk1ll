# S014 — Stopping is not refusing

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T2 (W6) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-06-S014.json`](../data/sessions/2026-09-06-S014.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A 5,000-file repository profiles without hanging | ✅ met — it *completes*, in 11.7 s |
| 2 | A codebase past its budget degrades rather than failing | ✅ met |
| 3 | A partial profile says so, and says how much it missed | ✅ met |
| 4 | The walk stops being the thing that hangs | ✅ met — 551× on a vendored tree |
| 5 | Q46 answered rather than carried forward | ✅ met |

## What was built

### Two limits that look alike and are not

W5 gave `ingest` a set of limits that **refuse** an archive. W6 needed limits
that **do not refuse** anything, and conflating the two would have been the
easy mistake. The split is now explicit:

| | Decides | On breach |
| --- | --- | --- |
| `IngestLimits` | Is this archive **hostile**? | Refuse it. Nothing is read |
| `ProfileBudget` | Have we looked at **enough**? | Keep what was profiled, flag it partial |

Refusing a monorepo would be the worse failure. 20,000 files is an ample sample
of how somebody writes, and the alternative is telling somebody their code is
too big to look at.

`ProfileBudget` bounds files, bytes, wall clock, and paths enumerated. The wall
clock spans **the walk and the analysis on one deadline**, because a slow
enumeration that spent the whole budget and left the analysis none would
technically respect every other limit.

### The walk was the hang

`iter_python_files` was `sorted(root.rglob("*.py"))` filtered by `SKIP_DIRS`
afterwards — so it descended into `.git`, `node_modules` and `.venv` in full and
*then* discarded what it found. On a real repository that is most of the walk,
and the walk is the part that has to not hang. It now walks with `os.walk` and
prunes `dirnames` in place, during traversal.

On a tree of 50 source files beside 20,000 vendored ones: **167 ms → 0.3 ms**,
a 551× improvement for a byte-identical result. Entries are sorted within each
directory, so the order stays deterministic without materialising the tree —
which matters precisely because a truncated profile must see the same files
twice, or the difference between two runs is filesystem order rather than
anything about the code. Symlinked directories are not followed, so a link loop
is not an infinite walk.

### What a partial profile is

`VibeVector` gained `partial`, `partial_reason` and `files_seen`, and a partial
profile **is banked** — both decisions taken with the user before any code was
written. It describes real code: a smaller sample, not a wrong one.

```
  files            412 of 5,183
  [PARTIAL]  stopped by file budget: 412 files; 4,771 files not read
```

`partial` means *we stopped looking*, never *something was unusable*. A
repository with one Python 2 file in it is completely profiled and simply has
one file's less signal — asserted, because the distinction is easy to lose.

### Q46, answered

S012 asked whether `ingest`'s streaming `max_source_bytes` rejection should
become a truncation. It should, and it has: by the streaming stage hostility has
already been ruled out, because every signal that an archive is an attack lives
in the central directory and was judged before a byte was decompressed. What
remains is an archive that is merely large — the same situation as a large
directory — and the honest response is a partial profile, not a refusal. The
limit is gone from `IngestLimits`; `ProfileBudget` owns size for both transports.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 727 tests — OK

$ python3.11 -m vibecoder.cli verify --seeds 3
36/36 reference runs clean

exit criterion 6, a 5,000-file / 6.56 MB repository:
  11.7 s   files=5000   partial=False        (against a 60 s budget)

the same tree under ProfileBudget(max_files=250):
  files=250  files_seen=5000  partial=True  "file budget: 250 files"

the walk, on 50 source files beside 20,000 vendored:
  rglob-then-filter  167.3 ms -> 50 files
  walk-with-pruning    0.3 ms -> 50 files      551x, identical result
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| A 5,000-file repository completes | `test_a_five_thousand_file_repository_completes`, and 11.7 s measured on realistic content | verified |
| The same repository degrades rather than hanging | `test_the_same_repository_under_a_small_budget_degrades_rather_than_hangs` | verified |
| Vendored directories are never descended into | `test_vendored_directories_are_never_descended_into`, `os.walk` spied on | verified |
| The walk order is deterministic | `test_the_order_is_deterministic` | verified |
| A symlink loop does not hang the walk | `test_a_symlink_loop_does_not_hang_the_walk` | verified |
| Each budget truncates and names itself | four tests: file, size, time, walk | verified |
| The budget is checked before the work | `test_the_budget_is_checked_before_the_work_not_after` | verified |
| A walk truncation still profiles what was found | `test_a_walk_truncation_is_carried_into_the_vector` | verified |
| A complete profile is never flagged | `test_a_complete_profile_is_never_flagged` | verified |
| An unparseable file does not make a profile partial | `test_an_unparseable_file_does_not_make_a_profile_partial` | verified |
| `files_seen` is never below `files` | `test_files_seen_is_never_below_files_profiled`, three budgets | verified |
| The new fields survive a round trip | `test_the_new_fields_survive_a_round_trip` | verified |
| An older profile without the fields still loads | `test_a_profile_written_before_these_fields_still_loads` | verified |
| A large but honest archive is truncated, not rejected | `test_a_large_but_honest_archive_is_not_rejected_for_its_size` | verified |
| The defaults suit real application repositories | sized from two synthetic trees and the standard library | `UNVERIFIED` — no third-party repository was profiled |

### T2 exit criterion 6

> *Profiling a 5,000-file repository completes within its budget or returns a
> partial profile flagged as partial. It does not hang.*

**Met, by finishing.** 11.7 s against a 60 s budget on 6.56 MB of realistic
content. Both branches of the "or" are tested: the same tree under a small
budget returns `files=250, files_seen=5000, partial=True`. The suite's own
version of the test uses small files so it costs one second rather than twelve.

## Misconceptions and corrections

### M29 — a truncated walk meant "stop", when it meant "there is more"

**Believed:** One `stopped` reason could carry both facts. The walk sets it when
it runs out of budget, the analysis loop checks it, and either way the profile
is partial. The loop began `if stopped: break`.

**Revealed by:** `test_a_walk_truncation_is_carried_into_the_vector`, written to
check the reason reached the vector, which instead reported **`files=0`**. When
the walk truncated, the analysis loop saw a reason already set on its first
iteration and stopped before profiling a single file. A budget meant to give a
partial profile was giving an empty one.

**Corrected to:** They are different claims. The transport's reason means *there
is more we did not enumerate*; the analysis's own reason means *stop now*. They
are tracked separately and merged only at the end, where the analysis's verdict
wins because it is the more immediate one. The bug was invisible in every other
test because they all truncate during analysis, where a single variable behaves
correctly.

**Cost:** ~10 minutes. Worth recording because the shared variable read as an
economy and was a conflation — the same shape as M22's naming histogram and
S012's two kinds of limit. Two facts that are both "why we stopped" are not one
fact.

## Friction

- Adding tests moved the suite count three times in one session (660 → 699 →
  706 → 727), and each time the doc-count check failed *after* a full unpinned
  run. The check is right; the habit of running it last is not. Counting before
  the final run costs nothing.
- The flight board linked to this entry before it existed, so the link checker
  failed. Writing the board entry and the journal entry in that order guarantees
  one red run.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D87 | `ProfileBudget` is a separate type from `IngestLimits` | One limits object for both | They produce opposite verdicts. Hostile is refused; enormous is truncated. One type would make the breach behaviour a per-field footnote | yes |
| D88 | Budgets truncate; they never raise | Raise and let the caller decide | The caller is a player who asked to be profiled. An exception hands them nothing where a sample would have served | yes |
| D89 | The walk prunes during traversal | Keep `rglob` and filter | The filtering version walks the directories it is about to discard, which is where the time goes on a real repository | no — this is the waypoint |
| D90 | Enumerate fully, then analyse | Stream files lazily into the analysis | Enumeration is a stat walk against seconds of parsing, and it buys an honest `files_seen`. "412 of 5,183" says the repository is twelve times the budget; "412, stopped early" says nothing | yes |
| D91 | One deadline spans the walk and the analysis | A budget for each | Two budgets can each be respected while the total is twice what was promised | yes |
| D92 | The walk's reason and the analysis's reason are tracked separately | One `stopped` variable | They are different claims, and conflating them profiled nothing at all (M29) | no |
| D93 | `partial` means "we stopped looking", not "something was unusable" | Flag any incomplete reading | Otherwise one Python 2 file makes an entire repository partial, and the flag stops meaning anything | yes |
| D94 | `ingest` lost its total-size rejection (Q46) | Keep it as a backstop | Hostility is decided from the central directory. A large honest archive is a large codebase, and two mechanisms for one concept is how they drift apart | yes |

## Handoff

- **State:** T2 W6 is landed. `vibecoder profile` bounds files, bytes, wall
  clock and enumerated paths; a codebase past its budget yields a flagged
  partial profile that is still banked. Exit criterion 6 is verified by
  finishing. 727 tests green unpinned, `verify` clean on 36 reference runs.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **T2 is not landable yet.** W4 and W7 remain, and criterion 5 stays open for
  the clone path that does not exist.
- **Next action: T2 W7** (vector versioning and migration), which W6 made more
  pressing rather than less. `VibeVector` gained three fields today; a profile
  written now and read by an older build loses more than it did when Q40 was
  raised, and `from_json` still drops unknown keys silently. The vector is
  three sessions into "the schema will change" with no version on it.
- **Blockers:** W4 remains blocked on a registered OAuth application and the
  client-versus-server profiling decision.
- **Context required:** D87 before merging the two limit types — they exist to
  produce different verdicts. M29 before simplifying the two stop reasons back
  into one. D93 before widening what `partial` means.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q44 | *(from S012, still open and now broader.)* The budgets and limits were sized against two synthetic trees and the standard library. No third-party repository has been profiled. Does 20,000 files / 64 MB / 60 s clear a real monorepo? | T2 | open |
| Q46 | *(from S012.)* Should the streaming source-budget rejection become a truncation? | T2 | **answered** — yes; D94 |
| Q53 | `max_walk_files` bounds enumeration at 200,000 paths, so a repository larger than that reports a `files_seen` that is a floor rather than a count. The display says "412 of 200,000" as though that were the total. Should a walk-truncated profile say "of at least"? | T2 | open |
| Q54 | The time budget is checked between files, so a single pathological file can overrun it. `max_file_bytes` bounds an archive member but nothing bounds a file on disk. Is a per-file read cap worth adding, or is that a shape that does not occur? | T2 | open |
| Q55 | A partial profile is banked and drives level selection exactly like a complete one. Should `recommend` weigh a 250-file sample the same as a 5,000-file one, or is a sample size worth carrying into the decision? | T4 | open |
