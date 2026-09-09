# Architecture

Phase 0 is a single Python package with no third-party dependencies, no
network code and no database. That is a deliberate constraint, not an
unfinished state: every measurement the game makes is one you can read in this
repository rather than one borrowed from a library, and the whole thing runs
anywhere a Python 3.10+ interpreter does.

## Module map

```
vibecoder/
├── models.py      Dataclasses, plus Source: where code came from. Depends on nothing.
├── scoring.py     The three axes, bonuses, stars, streak multiplier.
│                  `score_submission` for a level, `score_fight` for a boss.
├── runner.py      Parent side of the sandbox. Builds payloads, parses replies.
├── sandbox.py     Backend selection. THE SEAM: subprocess / bwrap / docker.
├── seccomp.py     Hand-assembled BPF filter. No libseccomp (N1).
├── _harness.py    Child side. Standalone script, stdlib only.
├── profiler.py    Vibe Profiler. Pure ast; executes nothing.
├── ingest.py      Archive ingestion. Untrusted input; imports no game module.
├── style.py       Style-goal checkers behind the elegance bonus.
├── tips.py        Rule-based post-level coaching.
├── session.py     Progression state, atomic writes.
├── replay.py      Slow-motion playback of a recorded trace.
├── cli.py         Command line.
├── editor.py      Full-screen play. Layout and dispatch only.
├── keymap.py      What each key does. A table, kept separate.
├── term.py        Raw mode and the alternate screen. Restores three ways.
├── keys.py        Byte stream to key events. A state machine, not a table.
├── editing.py     Text buffer, cursor, undo. No terminal at all.
├── screen.py      Cell grid; diffs frames so a keystroke repaints one cell.
├── highlight.py   Syntax colour. A tokenise failure is the normal case.
├── pulse.py       Keystroke rhythm. Behavioural data; never leaves the host.
├── vision.py      The machine view. Pure frames; the trace drives them.
├── fight.py       Boss hit points and the repair pool. Arithmetic only.
├── abilities.py   What may spend or refill those resources, and what it costs.
├── mastery.py     Per-tag competency and its update rule. Imports nothing.
├── policy.py      How hard the next variant should be, and what to drill.
├── repair.py      The pane a player types a boss-fight fix into.
├── timeline.py    A cursor over history, and whether a re-run matches it.
│                  No re-execution, imports nothing.
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
     sandbox    style      models
        │
     seccomp
        │         │          ▲
        ▼         └──────────┘
     _harness         tips ──┘

  cli, profiler ──► ingest         (T2 W5: archives, and what we refuse to read)
  cli ──► vision ──► screen, ui    (the machine view; frames, never a terminal)

  editor ──┬─► term ──┬─► keys      (T7: the interactive front-end)
           ├─► screen ├─► editing
           ├─► keymap └─► highlight ──► ui
           ├─► pulse
           └─► runner, scoring, session   (the same engine `cli` drives)
      (child)     │          ▲
                  └──────────┘
                       tips ──┘
```

`models.py` depends on nothing. `_harness.py` depends on nothing *including the
rest of this package* — it is executed as a standalone script, so a broken game
module cannot corrupt a submission run. `ingest.py` likewise imports nothing
from the package: it is the boundary where a stranger's archive arrives, and it
should be readable and testable without the game around it. Nothing imports
`cli.py`.

## Live stepping (T3 W2-W5)

`LiveRun` drives a submission one line at a time. The protocol is one
decision and everything follows from it:

> **The child runs a line, reports it, and blocks waiting to be told what to
> do next.**

- **Pause needs no implementation.** It is the parent not answering yet, so
  there is no pause state on either side to get out of sync.
- **The child never sleeps.** Pacing, variable speed and fast-forward all live
  in the parent, which is where the player is.
- **A paused fight cannot time out.** The child's budget counts *executing*
  time, never time blocked on the parent — otherwise a fight would fail for
  being watched carefully, which is the whole feature.

The payload and the control channel share the child's stdin, which is why the
harness reads its payload with `readline` rather than `json.load`: the latter
waits for a close that stepping never performs.

```
 parent (LiveRun)                │  child (_harness._run_stepped)
                                 │
 write payload line ────────────▶│  readline() -> payload
                                 │  settrace(...)
                       ◀──────── │  {"event": "step", line, func, locals}
 step() / resume() / abort() ───▶│  _control() unblocks
                       ◀──────── │  {"event": "result", ...}
```

Two rules in the trace hook look like details and are not. **Every line is
reported; only the first 400 are kept** — recording is bounded because it is
memory the parent is handed, while reporting is what keeps the parent in
control, and stopping it at the cap would leave a paused parent waiting for a
line that never arrives. And **the budget is checked on every line**, so a loop
that runs away after `run` is still stopped.

The step event carries exactly `{line, func, locals}`, the same shape
`_record_trace` produces, so [`replay.py`](../vibecoder/replay.py) and
[`vision.py`](../vibecoder/vision.py) render a live run with no translation.
`tests/test_stepping.py` asserts a live trace and a recorded trace agree line
for line.

### Stepping back (T3 W3)

Stepping back is not running backwards. The steps already happened and are
already recorded, so going back is moving an index over a list —
[`timeline.py`](../vibecoder/timeline.py) is a list and an integer, imports
nothing, and is tested without a sandbox, a child process or a terminal.
**Nothing is re-executed**, so there is no side effect to replay and no way for
history to disagree with itself.

The subtlety is the *edge*. History has an end, and past that end sits a child
still blocked mid-run. A cursor inside history is browsing; a cursor at the edge
is driving. `LiveRun.forward()` is one verb for both, because a caller should
not have to know which it is doing — inside history it is a cursor move, at the
edge it continues the run. `LiveRun.browsing` says which.

Appending always jumps the cursor to the edge: a step arriving while the reader
is in the past would otherwise leave the view still while the run moved, which
reads as a hang.

### Pausing on the failing line (exit criterion 2)

`settrace` reports an `exception` event while `f_lineno` is *still the line that
raised*. That is the only moment at which "pause on the offending line, not
after it" is possible — once the frame unwinds, the best anyone can say is which
function failed. The harness reports that instant as a step carrying `error`
and then blocks like any other, so the parent decides what happens next.

`error` rides on the **live event only**. The recorded trace stays exactly
`{line, func, locals}`, because that is what `replay` and `vision` read and a
fourth key would be a second shape for them to know about.

A stepped run also reports **one outcome**, for the one test it executes.
Watching a function not crash says nothing about whether it answered, and a
step cleared by `return None` would otherwise be celebrated. Scoring a fight is
W6/W7; this is only the difference between "it did not crash" and "it
answered", which edit-and-resume needs in order to mean anything.

### Edit-and-resume (T3 W4)

CPython will not swap the code object of a running frame, so "edit line 7 and
continue" is not something the interpreter offers. `LiveRun.edit(code)` is
T3's **strategy A**: run the edited source again from the top against the same
recorded inputs, and fast-forward silently to the edit point.

The memo strategy A normally needs is already here. **The inputs are the test
payload** — data the parent holds — so replaying them costs nothing and cannot
drift, which is why A is a better bet for the shapes this game poses than its
general reputation suggests.

Two rules make it behave:

- **Fast-forward stops *at* the step the reader is on, never through it.** That
  step is the one whose behaviour the player just changed, so replaying it
  would replay the edit away. The run is left blocked just before it, ready to
  execute the edited line next.
- **The edit point is where the reader is looking**, not where the child
  happens to be blocked — the cursor, so an edit made after stepping back
  resumes from there.

`LiveRun.code` is the source the child is running, which is how exit criterion
3 — the edit reflected in the final submitted source — is read rather than
assumed. The CLI carries it forward between boss steps, so a fix made at step
two is what step three is judged on.

### Divergence (T3 W5)

Strategy A is only honest if somebody checks that the fast-forwarded part
actually happened the same way. `timeline.compare` walks the two histories and
returns the first step at which they stop agreeing; `edit` calls it after every
fast-forwarded step and **stops there** rather than continuing, because going
on would present a different execution as a continuation of the one the player
watched — the lie exit criterion 4 exists to forbid.

Two decisions in the comparison:

- **The line number is deliberately not part of a step's signature.** The
  player has just edited the file, so the text has moved; a statement sliding
  down a line because a guard clause was added above it is not the program
  behaving differently. Comparing lines would fire on almost every edit and
  teach a player to ignore the warning. The cost is a false negative — two
  adjacent statements with identical locals are indistinguishable — which is
  the cheaper error, because a missed divergence still shows up as the run
  visibly disagreeing with its own history.
- **Running out early counts.** A re-run that returns before reaching the line
  the player was looking at has not reproduced the prefix either, and saying
  nothing would leave them at a position that no longer exists.

`edit` returns the finding rather than raising or printing it: only the caller
knows who is watching. The CLI prints it as a warning and keeps the fight
going, because a divergent resume is still playable — it just is not
continuous, and the player is told so.

### Typing the fix (Q67)

`--fix <path>` proves the engine and is not playing. The player types the fix
into the paused fight itself, in [`repair.py`](../vibecoder/repair.py):

```
─ FIX Drop the cheap stock above_floor() ─────────────────────────────────────
 ✘ line 16: KeyError: 'prise'
   floor = 10.0
──────────────────────────────────────────────────────────────────────────────
   14 def above_floor(rows, floor):
   15     ...docstring...
 ✘ 16     return [row for row in rows if row["prise"] >= floor]
   17
──────────────────────────────────────────────────────────────────────────────
 ctrl-r resume   ctrl-z undo   ctrl-k kill line   ctrl-x give up
```

**The pane is not the T7 editor.** `editor.Editor` is bound to a `Level` — it
runs that level's tests, scores the attempt and banks the result — and a boss
step is none of those; threading one through a `Level`-shaped API would be
dressing a mismatch up as reuse. What is reused sits a layer down and is
reused whole: `Buffer` for the text, `KeyDecoder` for the input, and the same
`KEYMAP`, so ctrl-R runs a level in one and resumes a fight in the other and
there is no second set of bindings to learn. Only the help *labels* differ,
which is why `describe_keys` takes them as an argument.

Three details that are the feature rather than decoration:

- **It opens on the line that raised, past the indent**, and that line stays
  marked in the gutter however far the player scrolls. A submission is longer
  than a short terminal, and making someone hunt for the line they just
  watched fail is the feature not working.
- **The locals at the failure are drawn in the pane.** The alternate screen
  has just hidden the scrollback, so a fix argued from remembered values is a
  guess.
- **The edit is compiled before the fight resumes.** A fix with a syntax error
  would otherwise restart the child only to have it die on import, spending a
  step of the fight on something the pane can point at while the cursor is
  still next to it. The guard is about compiling, never about being right —
  deciding a fix is *wrong* is the fight's job.

**The child stays blocked for as long as the player types, and that is free:**
its budget counts executing time and never time spent waiting on the parent
(T3 W2). A fight cannot time out for being thought about, which is what makes
opening an editor at the pause point safe at all.

`--fix` remains as the scriptable path — the same loop driven by a file
instead of a person, and the one the test suite can drive, since
`repair.available()` is false without a real terminal on both streams.

### What a fight costs (T3 W6)

[`fight.py`](../vibecoder/fight.py) is the boss's resources and nothing else:
no execution, no drawing, no clock. Arithmetic over a small amount of state,
so the rules are testable without a sandbox — and so that when
[T4](trajectories/T4-adaptive.md) W10 picks the pool up as something an
ability can refill, there is a plain object to refill.

```
  boss ████████████████████ 100   repairs ●●●●●
    ✔ cleared first try   -33
  boss █████████████░░░░░░░  67   repairs ●●●●●
    repaired — the boss recovers 8  (accuracy 17%)
    ✔ cleared after 1 repair   -17
  boss ████████████░░░░░░░░  58   repairs ●●●●·
```

### What the player is good at (T4 W1, W3)

[`mastery.py`](../vibecoder/mastery.py) holds a per-tag competency estimate
and the rule that moves it. Like [`fight.py`](../vibecoder/fight.py) it
**imports nothing** — the update rule takes plain numbers rather than a
`ScoreBreakdown`, so staying dependency-free costs the caller one line instead
of costing the module its independence.

It is a separate module from `models.py` rather than another dataclass in it,
for the reason `fight.py` is: this is a model *with rules* — a confidence
threshold, an update step, a decay to come in W6 — and those rules have
constants that need explaining. `models.py` holds shapes.

Its counterpart is the **function class** in
[`profiler.py`](../vibecoder/profiler.py), which reads the Vibe Vector and
never the mastery model. The two live in different modules with no import
between them, which is the cheapest enforcement of exit criteria 6 and 8
available: habits and scores cannot be blended by accident when neither module
can see the other.

**It is not the Vibe Vector and the two must never be averaged.** The vector
measures how you write, read statically from your code; mastery measures what
you score, from runs you played. T4's exit criterion 8 forbids any screen
showing a single number blending them, and keeping them in two modules with no
import between them is the cheapest enforcement available.

Since T4 W6 the model also **decays**: `Mastery.as_of(now)` returns a view
with age taken off both the value and the observation count. It is a view
rather than a mutation, applied at one call site (`Session.current_mastery`),
so the stored profile stays a record of what was measured instead of one that
rots on disk. Only `observe` writes decay back, and only because a new run has
superseded the old reading.

The update happens inside `Session.submit`, which is the *only* writer, and
which practice mode never calls. That makes "practice does not move mastery"
(criterion 5) a consequence of one branch rather than a second rule to
remember — the same branch that drops the Speed axis for an unmeasurable
clock.

### Choosing a difficulty, and saying why (T4 W4)

[`policy.py`](../vibecoder/policy.py) turns a profile into a `Decision`: a
`Difficulty`, the source it came from, a one-sentence reason, and the numbers
that sentence was built from.

**The reason is produced with the decision, not after it.** Exit criterion 4
requires every choice to be explainable "with no hidden state", and a policy
that computes a number and has an explanation bolted on later has exactly
that — two code paths that can disagree, one of which the player sees.

Two sources, used one at a time and always named: **mastery** whenever the
level's tags have enough observations, **habits** (the Vibe Vector) only as a
bounded prior when nothing has been measured. That resolves a tension inside
T4 itself, where one hazard says to fall back to the vector and the next says
never to confuse what you write with what you are good at. The player is never
shown a blend; they are shown which source was used.

`reference_benchmark` takes the difficulty too, and it is part of the cache
key. Benchmarking the reference at the default while the player runs a hard
variant would divide their ops by a denominator from a smaller input.

### Difficulty is a parameter, not a fork (T4 W2)

`Level.tests_for(seed, difficulty)` passes a `Difficulty` to `make_tests` only
if the generator's signature accepts one. Authors opt in one level at a time
and the old one-argument form keeps working, so this is inspected rather than
declared: a flag on the `Level` would be a second place to keep in sync with
the function it describes, and the function is what is actually true.

**The default difficulty reproduces pre-difficulty data byte for byte.** Every
op count in `data/baselines/` was measured before the parameter existed, so a
level that shifted under the default would quietly turn those files from
evidence into decoration. `tests/test_difficulty.py` asserts it for every
level and every boss step.

### What a fight scores (T3 W7)

The bar above is the fight's *outcome*. The **score** is a separate reading of
the same play, on the three axes at `BOSS_WEIGHTS` (40/30/30), and the two are
deliberately not folded together — HP already prices how wrong the code was
through the heal curve, so feeding it into the score as well would score one
property twice.

Three pieces carry it, and they sit where the existing seams already were:

| Piece | Where | Why there |
| --- | --- | --- |
| `StepScore` / `score_fight` | `scoring.py` | Pure arithmetic over plain numbers. It takes `repairs_spent` as an `int` rather than a `Fight`, so `scoring.py` keeps depending on nothing but `models.py`. |
| `boss_step_benchmark` | `runner.py` | A boss step's reference must run **with its predecessors present**, because a later step calls an earlier function by name. That is the module `verify` already builds, so a step is benchmarked against code the gate proves passes. |
| `_Pacer` | `cli.py` | The engine's slow motion is the parent's business and always has been. It now also measures itself, because that animation must not land on the Speed axis — see [SCORING.md](SCORING.md#boss-fights-the-scorecard-t3-w7). |

The measurement runs against the source the fight **ended** with, not the
attempt that cleared each step: a fight carries one buffer forward, so a fix
typed at step three is part of what step one is judged on.

Per-step damages are cumulatively rounded so they sum to **exactly** the
starting HP. Criterion 5 is an `== 0`, and a rounding crumb left anywhere in
here would make a won fight look unwon.

Spending a repair does two things — it halves what that step will deal, and it
heals the boss by up to 10% of starting HP scaled by `1 - accuracy`. The
numbers and the reasoning behind them are in
[`SCORING.md`](SCORING.md#boss-fights-hit-points-and-repairs-t3-w6); the shape
that matters architecturally is that **accuracy has to be real for the heal to
mean anything**, and a stepped run watches only one case. So the CLI measures
it with an ordinary `run_code` against the step's whole test set, in a process
of its own, while the paused child sits untouched. That is also what decides
whether the step cleared, which closes Q72: a live step is now judged on the
same cases it faces when scored normally.

`BOSS DOWN` is reserved for HP reaching zero, which only a fight with nothing
spent can do. Everyone else clears the boss and leaves it standing. Both paths
through `cmd_boss` — live and plain — share `_finish`, so the two cannot drift
into disagreeing about what winning means.

**Running out of repairs aborts rather than breaks.** The child is blocked
mid-run at that point, and draining one nobody has released waits forever.

## The execution boundary

This is the most important structural decision in the codebase.

```
 parent process                  │  child process (fresh interpreter)
                                 │
 runner.run_code()               │  _harness.main()
   ├ builds JSON payload  ──────────► reads stdin
   ├ sandbox.select() → Launch   │    ├ applies RLIMIT_AS / RLIMIT_CPU
   │   (argv + seccomp fd)       │    │   (+ RLIMIT_NPROC when isolated)
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
