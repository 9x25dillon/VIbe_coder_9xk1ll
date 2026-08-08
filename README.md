# VibeCoder

A Python puzzle game that scores your code on three axes — **is it right, how
fast did you write it, and how much work does it actually do** — and adapts its
challenges to how you already write code.

Most coding exercises stop at pass/fail. VibeCoder's central claim is that
pass/fail teaches half the lesson. You should be able to write a correct
solution, be told it is correct, and *in the same breath* be shown that it does
twenty-two times the work of the reference:

```
$ vibecoder play w1-l3-join --solution my_join.py

  PASS  no_events
  PASS  unmatched_event_dropped
  PASS  random_60x400

  5/5 passed   49590 ops   64.4 KiB peak

  SCORE
    accuracy    ########################  100.0  x0.67
    functional  ########----------------   33.1  x0.33  (49590 ops vs 2184 reference)

    TOTAL        89.3   [**.]

  VIBE TIPS
    - Correct, but your solution executes about 22.7x as many lines as the
      reference. Look for work being repeated inside a loop that could happen
      once outside it.
    - Nested loops over two collections is O(n*m). If the inner loop is looking
      things up, build a `set` or `dict` first and the lookup drops to O(1).
```

**Status:** Phase 0 complete. Playable, scored, 127 tests, **zero third-party
dependencies**. Boss fights are designed and scheduled, not yet built — see
[Trajectories](#trajectories).

## Quick start

Requires Python 3.10+. Nothing else.

```bash
git clone https://github.com/9x25dillon/vibe_coder_9xk1ll
cd vibe_coder_9xk1ll

python3 -m vibecoder.cli levels                 # what is available
python3 -m vibecoder.cli play w1-l1-revenue     # opens $EDITOR, scores on save
python3 -m vibecoder.cli status                 # stars, streak, global score
```

Personalise it by pointing the profiler at code you have already written:

```bash
python3 -m vibecoder.cli profile ~/code/my-project
python3 -m vibecoder.cli levels                 # now ordered for you
```

Optionally install as a command:

```bash
pip install -e .      # then: vibecoder levels
```

## How scoring works

Three independent axes, each 0–100, weighted 50 / 25 / 25 on levels.

| Axis | Measures | Notes |
| --- | --- | --- |
| **Accuracy** | Fraction of hidden tests passed | Correctness dominates — nothing rescues a wrong answer |
| **Speed** | How long **you** took, versus the level's par | Full marks at or under par; 50 at 2× par; never zero |
| **Functional** | How much work your **code** does, versus the reference | Traced line executions (70%) and peak memory (30%) |

Speed is your solve time, not your program's runtime — runtime belongs to
Functional. Bonuses (+10% first try, +5% elegance, +5% clean first run) can push
a total to 120.

A submission that passes nothing scores zero on Functional too, so a stub cannot
farm efficiency points. Full derivation, including the curves and why each was
chosen: [`docs/SCORING.md`](docs/SCORING.md).

## The Vibe Profiler

`vibecoder profile <path>` statically analyses a codebase — **it never executes
it** — and builds a *Vibe Vector*: libraries you reach for, constructs you
favour, how long your functions run, how you name things, which exceptions you
actually handle.

Level recommendation then weights **gaps over comfort** (60/40), because a game
that only serves what you are already good at is a leaderboard, not a teacher.

```
  PATTERNS
    type_hints         #################- 97%
    fstring            ################-- 89%
    comprehension      ##############---- 78%
    try_except         ########---------- 44%

  TAGS
    typing, io, oop, data, functional
```

Details, including the normalisation bug that shaped the design:
[`docs/VIBE_PROFILER.md`](docs/VIBE_PROFILER.md).

## Slow-motion replay

Every run records a line-by-line trace with a snapshot of locals at each step:

```bash
python3 -m vibecoder.cli replay w1-l3-join-1786155331 --step
```

```
  step 14/97
      6 |     lookup = {u["id"]: u["name"] for u in users}
  >>  7 |     for e in events:
      8 |         if e["user_id"] in lookup:

  watch  in join_events()
    lookup = {1: 'ada12', 2: 'grace7'}
    e = {'user_id': 2, 'action': 'click'}
```

This is playback only — pause, step-back, **edit-and-resume** are the boss-fight
engine, scheduled in [T3](docs/trajectories/T3-boss-engine.md). Shipping the
replay first was deliberate: it validates the trace format the live engine will
consume.

## Commands

| Command | Does |
| --- | --- |
| `profile <path>` | Build a Vibe Vector from a codebase (`--json` for raw) |
| `levels` | List levels, ordered by your vibe (`--campaign` for story order) |
| `play <id>` | Play a level (`--seed` for a specific variant, `--solution` to score a file) |
| `status` | Progression, stars, streak, global score |
| `replay [run-id]` | Slow-motion playback (`--step` to advance manually) |
| `verify` | Run every level's reference against its own tests |
| `reset` | Delete the local profile |

State lives in `$VIBECODER_HOME` (default `~/.vibecoder`) as inspectable JSON.

## Repository layout

```
vibecoder/            The game. 11 modules, no dependencies.
├── _harness.py       Sandbox child process; stdlib only, never imports the package
├── runner.py         Parent driver — the seam a container runner replaces
├── scoring.py        The three axes
├── profiler.py       Pure-ast codebase analysis
└── levels/           One file per level, auto-discovered

tests/                127 tests, stdlib unittest
docs/                 Architecture, scoring, profiler, level authoring, glossary
└── trajectories/     Forward plan — T1..T5
journal/              Chronological session reviews, with handoffs
data/                 Machine-readable records: session data, measurement baselines
SCHEDULE.md           Calendar plan through 18 Oct 2026
```

## Trajectories

Forward planning lives in [`docs/trajectories/`](docs/trajectories/). A
*trajectory* is a heading with waypoints and observable exit criteria — the
destination is committed, the path is expected to bend.

| ID | Trajectory | Status | Target |
| --- | --- | --- | --- |
| [T1](docs/trajectories/T1-core-loop.md) | Core loop: levels, sandbox, three-axis scoring | `LANDED` | 2026-08-08 |
| [T2](docs/trajectories/T2-sandbox.md) | Trusted execution & codebase ingestion | `CLEARED` | 2026-08-30 |
| [T3](docs/trajectories/T3-boss-engine.md) | Boss engine: interactive slow-motion debugger | `PLOTTED` | 2026-09-20 |
| [T4](docs/trajectories/T4-adaptive.md) | Adaptive difficulty | `PLOTTED` | 2026-10-04 |
| [T5](docs/trajectories/T5-community.md) | Daily challenges, leaderboards, level editor | `PLOTTED` | 2026-10-18 |

Week-by-week dates: [`SCHEDULE.md`](SCHEDULE.md).

## The journal

Every working session is reviewed in [`journal/`](journal/) against a fixed
rubric — objectives as observable outcomes, evidence for every claim,
**misconceptions and corrections**, friction, and a handoff block so the next
session does not have to re-derive the state of the world. Each entry has a
machine-readable twin in [`data/sessions/`](data/sessions/).

The misconceptions field is the point. From S001:

> **Believed:** scoring a file from disk could reuse the interactive timing
> path. **Revealed by:** running a deliberately terrible O(n·m) join through it
> — it scored 95.8 and three stars, because the clock had been running for 40
> milliseconds. **Corrected to:** an axis that cannot be measured honestly must
> not be scored.

## Security

Phase 0's sandbox is an **isolation** boundary, not a **security** boundary. It
protects the game from infinite loops, memory exhaustion and `sys.exit` in code
you wrote yourself, on your own machine.

It does **not** defend against hostile code. Do not use it to run submissions
written by other people. Container-backed execution is
[T2](docs/trajectories/T2-sandbox.md), and it gates every multiplayer feature in
[T5](docs/trajectories/T5-community.md) for exactly this reason.

The profiler never executes analysed code and never persists source — only
derived statistics.

## Contributing

Adding a level is adding one file:
[`docs/LEVEL_AUTHORING.md`](docs/LEVEL_AUTHORING.md). The contract tests in
`tests/test_levels.py` apply to it automatically — including that the starter
must *fail* its own tests and the reference must *pass* every variant.

```bash
python3 -m unittest discover -s tests     # ~4 seconds
python3 -m vibecoder.cli verify --seeds 5
```

## Licence

See [LICENSE](LICENSE).
