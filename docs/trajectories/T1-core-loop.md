# T1 — Core loop: levels, sandbox, three-axis scoring

**Design phase:** 0 (Prototype) · **Status:** `LANDED` 2026-08-08 ·
**Evidence:** [journal/2026-08-08-S001-core-loop.md](../../journal/2026-08-08-S001-core-loop.md)

## Heading

Make the game's central claim testable as early as possible. That claim is not
"a Python quiz exists" — quizzes are everywhere — it is that **scoring code on
three independent axes teaches something a pass/fail harness cannot**. A player
should be able to write a correct solution, be told it is correct, and still be
shown that it does twenty times the work of the reference.

Everything else in the design (vibe adaptation, boss fights, leaderboards)
depends on that claim holding. So T1 builds the smallest system that can prove
or disprove it, with no web stack, no database and no third-party dependency
that could be blamed when something behaves oddly.

## Waypoints

| ID | Waypoint | State |
| --- | --- | --- |
| W1 | Data model: `Level`, `TestCase`, `RunResult`, `ScoreBreakdown`, `VibeVector` | done |
| W2 | Sandboxed runner: subprocess isolation, wall-clock timeout, RLIMIT caps | done |
| W3 | Instrumentation: op counting via `sys.settrace`, peak memory via `tracemalloc` | done |
| W4 | Three-axis scoring with bonuses, star thresholds, streak multiplier | done |
| W5 | Six levels across two worlds, each with a verified reference solution | done |
| W6 | Seeded variant generation so any level can be replayed with new data | done |
| W7 | Vibe Profiler over a local codebase, emitting a Vibe Vector | done |
| W8 | Vibe Tips: conservative, rule-based post-level coaching | done |
| W9 | Session persistence: per-level bests, streaks, run artifacts | done |
| W10 | CLI covering profile / levels / play / status / replay / verify / reset | done |
| W11 | Slow-motion **replay** of a recorded trace (playback only) | done |

## Exit criteria

Written 2026-08-08 before implementation; all verified the same day.

| # | Criterion | Result |
| --- | --- | --- |
| 1 | Every level's reference solution passes its own generated tests on ≥4 seeds | ✅ `test_levels.py::test_every_reference_solves_every_variant`, 24 level×seed runs |
| 2 | A correct-but-naive O(n·m) solution scores materially below a correct O(n) one | ✅ 89.3 vs 120.0 on `w1-l3-join`; Functional axis 33.1 vs 100.0 |
| 3 | The sandbox survives infinite loops, syntax errors, `sys.exit` and module-level raises | ✅ `test_runner.py::TestFailureModes`, 6 cases |
| 4 | A player cannot score by submitting a stub | ✅ zero accuracy forces zero functional; starter templates asserted to fail |
| 5 | Profiling a real codebase yields non-trivial, correct tags | ✅ self-profile: 18 files, 120 functions, tags `typing, io, oop, data, functional` |
| 6 | Whole suite runs with no third-party dependency | ✅ 127 tests, stdlib `unittest`, 4.4s |

## Known hazards

Recorded before the work, kept verbatim.

- **The op count is a proxy, not a complexity measure.** Counting traced line
  executions rewards pushing work into C builtins, which is *usually* the right
  lesson but is not the same as measuring asymptotic complexity. A player who
  calls a quadratic builtin looks efficient. Accepted for T1; revisit in T4.
- **`tracemalloc` peak is noisy at small sizes.** Mitigated by weighting ops at
  0.7 against memory at 0.3, and by sizing at least one variant of every level
  large enough to dominate interpreter noise.
- **JSON-serialisable test data constrains level design.** No level can pass a
  custom object to a submission. This has not blocked any level yet and buys a
  clean process boundary.

## What actually went wrong

Both found by running the system, not by reading it. Full write-up in the
[session review](../../journal/2026-08-08-S001-core-loop.md).

1. **The `--solution` path handed out a free 100 on Speed.** Scoring a file from
   disk starts the clock moments before scoring it, so a naive nested-loop join
   earned three stars. Fixed by introducing *practice mode*: when there is no
   honest solve time, the Speed axis is dropped, the remaining two are
   renormalised, and the run is not banked. `--elapsed` lets a front-end supply
   a real measurement and get a ranked run.
2. **Pattern shares saturated at 100%.** File-level patterns were reported as
   `min(1.0, count / files)`, so anything common pinned to 100% and carried no
   signal. Now reported as *share of files containing the pattern*, with
   per-function patterns still normalised per function.

## Instrument checks

- `python3 -m unittest discover -s tests` — 127 tests, must stay green.
- `python3 -m vibecoder.cli verify --seeds 3` — every reference against every
  variant; this is the gate that stops a broken level shipping.
- Manual: the naive-vs-optimal score gap on `w1-l3-join` is the single number
  that says whether the Functional axis is doing its job.
