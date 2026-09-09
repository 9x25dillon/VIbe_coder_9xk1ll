# T5 — Daily challenges, leaderboards, level editor

**Design phase:** 4 · **Status:** `IN FLIGHT` · **Target:** 2026-10-18 ·
**Started:** 2026-09-08 ·
**Depends on:** T2 (**hard** dependency — this trajectory executes untrusted code)

## Heading

Everything up to here is single-player and offline. T5 is where other people
arrive: a daily challenge with a shared leaderboard, and a level editor whose
output other players run on their own machines.

Note the dependency line. A community level is a Python file written by a
stranger that the game executes locally. Shipping W4 of this trajectory before
T2's container sandbox would turn the game into a malware delivery mechanism.
This is stated here so that no one can reach the editor by accident.

## Waypoints

| ID | Waypoint | Notes |
| --- | --- | --- |
| W1 | Deterministic daily seed: `hash(date)` → variant, identical for everyone | `LANDED` (S036). **Not `hash`** — it is randomised per process, so the same date differs between two runs on one machine. `hashlib.sha256`, and criterion 1 is checked by re-deriving in a separate interpreter. |
| W2 | Local leaderboard and personal daily history | Playable and useful with no backend at all. |
| W3 | Score submission API + server-side re-verification | A client-reported score is a claim, not a fact. Re-run the submission server-side. |
| W4 | Vibe-filtered leaderboards | The design's "compare against similar coding style" — cosine similarity over Vibe Vectors. |
| W5 | Level editor: author a level, validate it, export it | Validation runs the same contract tests as `tests/test_levels.py`. |
| W6 | Level sharing with mandatory container execution | Untrusted code, no exceptions. |
| W7 | Achievements and New Game+ | Cheap once the score history exists. |

## The daily (W1)

One level, one variant seed, from the date alone. Two people with no network
between them get the same problem, which is what makes a shared challenge
possible before any of this trajectory's backend exists.

### The waypoint's own wording was the first bug

W1 is written as `hash(date)` → variant, and that is precisely what it must
not do. Python randomises `str` hashing per process unless `PYTHONHASHSEED` is
pinned, so the same date gives a different answer on every **run** — exit
criterion 1 asks two machines to agree, and `hash` cannot manage two
invocations on one:

```
$ for i in 1 2 3; do python3 -c "print(hash('2026-09-08'))"; done
-7723537222559262413
-7920657940426615118
 1873428733625979326
```

`hashlib.sha256` is specified, stable across builds and platforms, and in the
standard library (N1). `tests/test_daily.py` re-derives the daily in a
**separate interpreter process** and compares, which is the closest a unit
test gets to two machines — and it documents the `hash` failure as a test, so
a future reader sees why rather than being asked to trust a comment.

### A daily is not adapted, and that is a T4 decision reversed

`Daily` carries no difficulty field. T4 spent eleven waypoints learning to
give each player a variant matched to them, and a shared challenge needs
exactly the opposite: **adapting a daily would hand two players different data
for the same puzzle**, and the leaderboard W2–W4 are building toward would be
comparing different problems.

So `cmd_daily` imposes the standard difficulty and `cmd_play` honours it,
saying so on screen — *"a daily challenge is the same for everyone, so this
variant is not adapted to you"*. The absence of the field on `Daily` is the
enforcement; the sentence is so the player is not left wondering why the
adaptation they were promised stopped.

### Scoped determinism

A daily is determined by **the date and the set of levels in this build**.
Adding a level changes which one a past date selects, and avoiding that would
mean pinning a catalogue snapshot into the code, which would then rot against
the levels that actually exist. The criterion is about two machines agreeing,
and two machines on the same build do. Ids are sorted before indexing, so a
registry ordering bug cannot silently move today's challenge.

## Exit criteria

1. Two machines given the same date generate a byte-identical daily challenge.
2. A forged score submission is rejected by server-side re-verification.
3. A community level cannot execute outside a container, enforced in code and
   proven by a test that tries.
4. An authored level failing any contract test cannot be exported.
5. Leaderboards remain usable offline, degrading to local-only.

## Known hazards

- **A level is code, not data, and `Source.THIRD_PARTY` does not cover all of
  it.** T2 W3 makes the *execution* path safe: a third-party level's reference
  solution is forced into an isolating backend, and forgetting to say so is a
  `TypeError` rather than a silent host run. But a level is loaded by
  importing a module, which runs its body, and `make_tests` is a callable
  invoked in the **parent** process on every `tests_for()`. Both bypass
  `run_code` entirely. The registry only loads levels bundled with this
  package, so nothing can reach either path today; W6 is what would open it.
  Shipping the level editor therefore needs a level *format* that is data
  rather than an importable module, or a way to generate test data inside the
  sandbox — the hard gate below is necessary and, on its own, not sufficient.

- **Leaderboards invite cheating, and the incentive is the point.** The only
  defensible position is that the server re-runs every ranked submission.
  Client-side timing in particular is unverifiable — which is exactly why T1
  already separates ranked runs from practice runs.
- **Speed as a leaderboard axis is the weakest link.** Wall-clock solve time
  cannot be verified at all. Consider ranking dailies on Accuracy + Functional
  only, and treating Speed as a personal-best statistic rather than a
  competitive one.
- **Community levels need a reference solution to score against.** An author
  who supplies a slow reference makes their level trivially easy on the
  Functional axis. Validation must benchmark the reference against submitted
  solutions over time and flag outliers.
- **Moderation is unbudgeted.** Level briefs are free text. Someone will write
  something vile in one. Decide the policy before the feature ships, not after.

## Instrument checks

- Cross-machine daily determinism test in CI.
- Re-verification disagreement rate: how often does a server re-run disagree
  with the client's claim? Anything non-zero needs explaining.
- Community level quality: distribution of reference-vs-player op ratios.
