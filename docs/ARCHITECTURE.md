# Architecture

Phase 0 is a single Python package with no third-party dependencies, no
network code and no database. That is a deliberate constraint, not an
unfinished state: every measurement the game makes is one you can read in this
repository rather than one borrowed from a library, and the whole thing runs
anywhere a Python 3.10+ interpreter does.

## Module map

```
vibecoder/
├── models.py      Dataclasses. No behaviour beyond JSON round-tripping.
├── scoring.py     The three axes, bonuses, stars, streak multiplier.
├── runner.py      Parent side of the sandbox. THE SEAM for T2.
├── _harness.py    Child side. Standalone script, stdlib only.
├── profiler.py    Vibe Profiler. Pure ast; executes nothing.
├── style.py       Style-goal checkers behind the elegance bonus.
├── tips.py        Rule-based post-level coaching.
├── session.py     Progression state, atomic writes.
├── replay.py      Slow-motion playback of a recorded trace.
├── cli.py         Command line.
└── levels/        One module per level; auto-discovered.
```

## Dependency direction

```
                 cli
        ┌─────────┼──────────┬──────────┐
        ▼         ▼          ▼          ▼
     runner   profiler    session    replay
        │         │          │
        ▼         ▼          ▼
     _harness   style      models
      (child)     │          ▲
                  └──────────┘
                       tips ──┘
```

`models.py` depends on nothing. `_harness.py` depends on nothing *including the
rest of this package* — it is executed as a standalone script, so a broken game
module cannot corrupt a submission run. Nothing imports `cli.py`.

## The execution boundary

This is the most important structural decision in the codebase.

```
 parent process                  │  child process (fresh interpreter)
                                 │
 runner.run_code()               │  _harness.main()
   ├ builds JSON payload  ──────────► reads stdin
   ├ spawns python -I harness    │    ├ applies RLIMIT_AS / RLIMIT_CPU
   ├ enforces wall timeout       │    ├ compiles submission
   └ parses JSON result  ◄──────────┤ runs each test twice:
                                 │    │   pass 1 untraced → time, memory
                                 │    │   pass 2 traced   → op count
                                 │    └ writes JSON to stdout
```

Two passes per test case, because `sys.settrace` roughly doubles runtime —
timing taken from a traced run would measure the instrumentation.

The child is launched with `-I` (isolated mode: no user site-packages, no
`PYTHONPATH`), communicates only over stdin/stdout, and captures the
submission's own `print` output into the result rather than letting it corrupt
the JSON channel.

**What this boundary is and is not.** It is an *isolation* boundary that
protects the game from a learner's infinite loop, memory hog or `sys.exit`. It
is **not** a *security* boundary. It does not defend against hostile code and
must not be used to run submissions written by other people. That is
[T2](trajectories/T2-sandbox.md)'s job, and `run_code`'s signature is the seam
where a container-backed implementation drops in without anything above it
changing.

## How "ops" are counted

The Functional axis needs a deterministic efficiency measure. Wall-clock time is
far too noisy at these scales, so the harness counts **line executions inside
the submitted file only**, filtering `sys.settrace` events by code filename:

```python
def global_trace(frame, event, arg):
    if frame.f_code.co_filename == filename:   # the submission, not the stdlib
        return local_trace
    return None
```

A call to `sorted()` therefore costs **one** op; a hand-written sort costs
hundreds. That is not a complexity measurement — a player calling a quadratic
builtin looks efficient — but it is stable run to run and it rewards exactly
the habit the game wants to teach. The limitation is recorded as an open
question against [T4](trajectories/T4-adaptive.md).

The same mechanism, with locals snapshotted per step instead of counted,
produces the trace that `replay.py` plays back and that
[T3](trajectories/T3-boss-engine.md)'s live engine will consume.

## Levels are generators, not fixtures

A level supplies `make_tests(rng)` rather than a fixed list of cases:

```python
level.tests_for(seed)   # random.Random(seed) → same data every time
```

Seed 1 and seed 2 are different puzzles of the same shape. This is what makes
the replayability claim real, and [T4](trajectories/T4-adaptive.md) reuses it
for adaptive difficulty — varying input size and edge-case density rather than
swapping in different problems.

Reference solutions are benchmarked against **the same generated data the
player faces**, cached per `(level, seed)`. Benchmarking against fixed data
would score a 400-row variant against a 12-row baseline.

## State

One JSON file at `$VIBECODER_HOME` (default `~/.vibecoder`), written
temp-then-rename so an interrupted save cannot truncate it. A corrupt profile is
renamed aside rather than overwritten, because a hand-edited profile is a thing
players will do.

The global score is **recomputed from per-level bests on every save** rather
than incremented. A corrupted increment cannot compound, and replaying a level
badly can never reduce a total already banked.

Run artifacts (code, score, full result including trace) are written to
`$VIBECODER_HOME/runs/` so any run can be replayed later.

## Extension points

| You want to | Touch |
| --- | --- |
| Add a level | One new file in `vibecoder/levels/` — see [LEVEL_AUTHORING.md](LEVEL_AUTHORING.md) |
| Change how code is executed | `runner.run_code` — the seam; nothing above it should change |
| Add a style goal | `style.CHECKERS` and `style.DESCRIPTIONS` |
| Add a coaching rule | Decorate a function with `@tips.rule` |
| Change the scoring curves | `scoring.py` — read [SCORING.md](SCORING.md) first |
| Add a profiler signal | `profiler._analyse_tree`, plus a tag mapping |
