# T5 — Daily challenges, leaderboards, level editor

**Design phase:** 4 · **Status:** `PLOTTED` · **Target:** 2026-10-18 ·
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
| W1 | Deterministic daily seed: `hash(date)` → variant, identical for everyone | No server needed for the puzzle itself. |
| W2 | Local leaderboard and personal daily history | Playable and useful with no backend at all. |
| W3 | Score submission API + server-side re-verification | A client-reported score is a claim, not a fact. Re-run the submission server-side. |
| W4 | Vibe-filtered leaderboards | The design's "compare against similar coding style" — cosine similarity over Vibe Vectors. |
| W5 | Level editor: author a level, validate it, export it | Validation runs the same contract tests as `tests/test_levels.py`. |
| W6 | Level sharing with mandatory container execution | Untrusted code, no exceptions. |
| W7 | Achievements and New Game+ | Cheap once the score history exists. |

## Exit criteria

1. Two machines given the same date generate a byte-identical daily challenge.
2. A forged score submission is rejected by server-side re-verification.
3. A community level cannot execute outside a container, enforced in code and
   proven by a test that tries.
4. An authored level failing any contract test cannot be exported.
5. Leaderboards remain usable offline, degrading to local-only.

## Known hazards

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
