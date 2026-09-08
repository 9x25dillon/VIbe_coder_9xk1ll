# S024 — Scoring the fight

**Date:** 2026-09-08 · **Duration:** 01:40 · **Trajectory:** T3 ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-08-S024.json`](../data/sessions/2026-09-08-S024.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | Q80 is decided on a measurement rather than an argument, and the measurement is written down | ✅ met |
| 2 | A boss fight is scored on the three axes at 40/30/30, and the scorecard is what a first run is graded by | ✅ met |
| 3 | The engine's own slow motion does not reach the Speed axis | ✅ met |
| 4 | An abandoned fight is scored honestly rather than flatteringly | ✅ met — and this is where the session's real finding was |
| 5 | T3's remaining waypoint state is recorded accurately, including what W7 does *not* close | ✅ met |

## What was built

**`score_fight` and `StepScore` in [`scoring.py`](../vibecoder/scoring.py).** A
fight is graded on the same three axes as a level, at `BOSS_WEIGHTS`
(40/30/30) — the constant that had been defined and unused since T3 was
written. It takes `repairs_spent` as an `int` rather than a `Fight`, so
`scoring.py` still depends on nothing but `models.py`.

**`boss_step_benchmark` in [`runner.py`](../vibecoder/runner.py).** A boss
step's reference cannot be benchmarked in isolation: `summarise` calls the two
functions before it and raises `NameError` on its own. The benchmark therefore
runs `boss.reference_source(index)` — the same module `verify` already builds,
so a step is measured against code the gate proves passes. Cached per
`(boss, step, seed)`, because a variant with ten times the rows must not be
scored against a benchmark from a smaller one.

**`_Pacer` in [`cli.py`](../vibecoder/cli.py).** The fight's slow motion now
measures itself, and the measured sleep is subtracted from the clock handed to
the Speed axis. Without it the same fight, played identically, scores
differently at `--speed 0.1` and `--speed 2.0` — marks awarded for a display
setting.

**A scorecard at the end of every fight**, cleared or abandoned, in the layout
a level already uses. `--elapsed` was added to `boss` for the same reason
`play` has it: a front-end that genuinely tracks solve time gets a ranked run,
and everything else drops Speed and renormalises.

### What the score deliberately does not read

Hit points. HP and the repair pool already price how wrong the code was,
through W6's heal curve. Feeding them into the score as well would score one
property twice, which is the mistake §4 of the working agreement exists to
prevent. The pool reaches the score once, through `first_try`, and the bar is
printed beside the card rather than folded into it.

### Q80, answered by measuring first

The question was whether `BOSS DOWN` being unreachable from the starters is a
defect. Rather than argue it, the floor was measured on `w1-boss-pipeline`:
**exactly 65**, with the per-step heals and damages listed in the evidence
below. The measurement changed the question. The heal — the mechanic everyone
would reach for first — accounts for only 14 of the missing 35 HP. The
compounding damage halving accounts for the other 51. So "make the first repair
free" moves the floor to 51 and changes nothing about reachability; only a
repair that costs *literally nothing* reaches zero, and that makes the flawless
ending the default rather than the rare one.

The user's call was to leave the mechanic alone and be honest about the ending:
`BOSS DOWN` is a mastery ending, reached by coming back with a solution that
passes every step first time. The reasoning and the measured table are now in
[`SCORING.md`](../docs/SCORING.md#boss-down-is-a-mastery-ending-not-a-first-run-one-q80).

## Evidence

```
$ python3.11 /tmp/.../q80_floor.py
boss=w1-boss-pipeline steps=3 damages=[33, 34, 33] hp=100
  step 0 parse        acc=50% (3/6)  heal=+5  damage=-16  hp=89
  step 1 filter       acc=83% (5/6)  heal=+2  damage=-17  hp=74
  step 2 summary      acc=33% (2/6)  heal=+7  damage=-16  hp=65

best reachable from starters: 65 HP, 2 repairs left, flawless=False
```

```
$ python3.11 -m vibecoder.cli boss w1-boss-pipeline          # the starters
  the fight stops here  0/3 steps cleared
    accuracy    ████░░░░░░░░░░░░░░░░░░░░   16.7  x0.57  (3/18 cases)
    speed       not measured -- no honest solve time
    functional  ████████░░░░░░░░░░░░░░░░   33.3  x0.43  (48 ops vs 1412 reference)
    TOTAL       23.8   ☆☆☆
```

```
$ python3.11 -m vibecoder.cli boss w1-boss-pipeline --live --reference \
      --speed 0 --elapsed 1800
  BOSS DOWN  flawless -- nothing spent
    accuracy    ████████████████████████  100.0  x0.40  (18/18 cases)
    speed       ████████████░░░░░░░░░░░░   50.0  x0.30  (1800s vs 900s par)
    functional  ████████████████████████  100.0  x0.30  (1412 ops vs 1412 reference)
    subtotal 85.0  [+10%] first_try [+5%] elegance [+5%] clean_first_run
    TOTAL       102.0  ★★★
```

```
$ python3.11 -m unittest discover -s tests
Ran 1018 tests in 59.235s — OK

$ VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests
Ran 994 tests in 43.496s — OK (skipped=6)

$ python3.11 -m vibecoder.cli verify --seeds 3
45/45 reference runs clean

$ python3.11 -m vibecoder.cli showcase | grep -c $'\033'
0
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| The best outcome reachable from the starters is exactly 65 HP | the `Fight` object driven with real starter accuracies, above | verified |
| The heal accounts for 14 of the missing 35 HP; the damage halving for 51 | same run: damages 16+17+16 = 49 dealt, heals 5+2+7 = 14 | verified |
| A boss fight is scored at 40/30/30 | `tests/test_scoring.py::test_the_boss_weights_are_forty_thirty_thirty`, and the ranked run above showing `x0.40` / `x0.30` / `x0.30` | verified |
| A fight with no honest clock drops Speed and renormalises to 0.57 / 0.43 | `::test_a_fight_without_a_clock_does_not_score_speed` | verified |
| A dropped Speed axis reports `0.0`, not a value nothing measured | `::test_a_dropped_speed_axis_reports_nothing_rather_than_a_hundred` | verified |
| An abandoned fight is not scored as maximally efficient | `tests/test_cli_output.py::test_an_abandoned_fight_is_not_maximally_efficient`, and the starter run above showing 33.3 | verified |
| The engine's slow motion is measured and excluded | `::TestTheSlowMotionIsNotThePlayersTime`, three cases including a negative delay | verified |
| A boss step benchmarked alone would not run | `tests/test_bosses.py::test_a_step_benchmarked_alone_would_not_run` — `summarise` fails on its own reference, passes with its predecessors | verified |
| The scorecard emits no escape sequence into a pipe | `::test_the_scorecard_emits_no_escape_sequence_into_a_pipe`, plus `showcase \| grep -c` | verified |
| Both gates green | 1018 unpinned, 994 pinned, 45/45 verify | verified |
| Whether the scorecard *feels* right at the end of a real fight | nobody has played one with a score on it | `UNVERIFIED` |
| Whether 40/30/30 produces a useful spread across real players | one boss, no players | `UNVERIFIED` |

## Misconceptions and corrections

### M40 — pooling ops across a fight pays for work never done

**Believed:** That Functional could be computed the way a level computes it,
by comparing the fight's total ops against the reference's total ops. Summing
seemed obviously right: ops accumulate, so add them up.

**Revealed by:** Running the suite before writing a single test for it. A fight
that stopped on step one printed `functional 100.0` next to `accuracy 44.4`.
The later steps' functions are never defined when a fight stops early, so they
execute nothing; against the reference's total that reads as *doing less work*,
`functional_score` caps the ratio at 1.0, and the scorecard congratulated a
player who had achieved almost nothing.

**Corrected to:** Functional is computed per step and averaged, and a step that
passed nothing scores zero rather than scoring the ratio of the work it
skipped. That is the same guard `score_submission` already applies at whole-
submission level, applied at the granularity a boss actually has. It also fixes
a second problem the pooled version had: one frugal step could subsidise a
wasteful one.

**Cost:** ~10 minutes. Caught before shipping, but only because the output was
read rather than the exit status.

**Generalisable:** This is M1's shape for the fifth recorded time — free points
on an axis that is not measuring anything. Every instance so far has been found
by looking at what a *bad* run printed. The suite has never once been the thing
that caught it, because a test written by the same person who wrote the bug
asserts the same wrong thing.

### M41 — a zero weight hides a faked value, it does not prevent one

**Believed:** That dropping the Speed axis was handled entirely by
`Weights.without_speed()`. The weight becomes 0, the axis cannot affect the
total, therefore the axis is dropped.

**Revealed by:** `test_dropping_speed_renormalises_rather_than_gifting_it`,
which asserted `score.speed == 0.0` and got `100.0`. The value was still being
computed against a clock that had started moments earlier; only its
*contribution* was suppressed.

**Corrected to:** `score_fight` zeroes Speed when the axis carries no weight,
so the breakdown reports nothing rather than a confident fiction. N5 says an
axis that cannot be measured honestly must not be *scored*, and a breakdown is
stored and read back later — the weight hides the number from the total, not
from whoever quotes the record afterwards.

**Cost:** ~5 minutes.

**Note, and it is a finding rather than a fix:** `score_submission` has the
same property today. A level played in practice mode stores `speed` alongside
`accuracy` and `functional` in `runs/`, computed from a clock that started when
the file was read. It is invisible in the UI because `cmd_play` prints "not
measured in practice mode" instead of the gauge. Changing it would alter level
scoring and previously banked run records, which §12 says to ask about rather
than decide. **Left alone deliberately; raised as Q81.**

### M42 — `redirect_stdout` does not capture a scorecard

**Believed:** That the existing boss tests captured everything `cmd_boss`
printed, since they all wrapped it in `redirect_stdout`.

**Revealed by:** Three new assertions failing against transcripts with the
score cut out of the middle, while the gauges appeared on the real terminal.
`UI` binds `sys.stdout` when it is constructed, at import time, so
`redirect_stdout` catches the plain `print` calls and misses every gauge and
star burst.

**Corrected to:** One `everything_printed()` helper in `test_cli_output.py`
that swaps both, used by all four fight harnesses. Not a product bug — in a
real pipe `sys.stdout` *is* the pipe — but it meant the boss tests had been
asserting against partial transcripts, and would have silently kept doing so.

**Cost:** ~10 minutes.

## Friction

Deciding where the "how wrong were you before repairing" signal belongs. The
heal curve measures it, the score cannot see it (a cleared fight is 100%
accurate by definition), and scoring it in both places would violate §4. The
resolution — HP is the outcome, the card is the grade, printed side by side —
took longer to justify than to implement, and the alternative is recorded as
Q82 rather than discarded.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D158 | `BOSS DOWN` is a mastery ending; the mechanic is unchanged | First repair free of its heal (floor 51); first repair free entirely (floor 0, but flawless becomes the default); damage reduction scaled by accuracy (floor ~36) | The measurement showed the heal is not the obstacle, so three of the four options were dials rather than answers. The fourth makes the rare ending common. | Yes — the alternatives are costed in `SCORING.md` |
| D159 | Hit points are not an input to the score | Fold remaining HP into the total; weight the axes by HP | HP already prices how wrong the code was via the heal curve; scoring it again is §4's exact prohibition. | Yes |
| D160 | Accuracy is pooled across cases; Functional is averaged per step | Both pooled; both averaged | Accuracy keeps the one definition it has everywhere (fraction of hidden tests passed). Functional is per step because each step has its own reference — and because pooling produced M40. | Yes |
| D161 | The engine subtracts its own slow motion from the Speed clock | Count wall clock; give the boss a longer par to absorb it | Counting it scores a display setting. A longer par would make the distortion smaller without making it honest. | Yes |
| D162 | An abandoned fight is still scored | Print no card unless the fight cleared | A zero printed for a reason is information; a blank reads as an omission. The starters fail, so the abandoned fight is what a first-time player actually gets. | Yes |
| D163 | T3 holds `IN FLIGHT` until W8 ships | Land on the six criteria and record W8 as a gap; land and re-scope W8 elsewhere | The user's call. The waypoint list is treated as the real contract and the criteria as incomplete — which is a finding about the criteria, not a licence to edit them (N7). | Yes |

## Handoff

- **State:** T3 W7 is `LANDED`. A boss fight is scored at 40/30/30 on the same
  card a level uses; Speed excludes the engine's slow motion; HP stays the
  fight's outcome and is deliberately not an input to the score. Q80 is
  answered — `BOSS DOWN` is a mastery ending, and the floor from the starters
  is a measured 65. **All six of T3's exit criteria now have evidence and T3 is
  deliberately still `IN FLIGHT`** (D163). 1018 tests green unpinned, 994
  pinned, `verify` clean on 45 reference runs, 0 escapes in a pipe.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action: T3 W8** — the second boss fight, World 2's algorithm
  assembly. It is the only waypoint left in T3 and the trajectory now waits on
  it. Read D156 first: partial credit in a starter is load-bearing for the
  heal curve, and the new scorecard reads the same starters.
- **Before that, ideally: someone plays a fight with a score on it.** Every
  number on the card was chosen by argument; M40 was found by reading output,
  not by running tests, and that has now happened five times.
- **Blockers:** none. T2 W4 remains blocked on a registered OAuth application.
- **Context required:** M40 before touching any axis — the free-points failure
  has a fifth instance and they all look like arithmetic that reads fine.
  Q81 before changing level scoring. M42 before asserting on CLI output.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q68 | Two events land on one line when it raises. Should the display merge them? | T3 | open |
| Q69 | `Timeline` holds `Step` objects for a live run and dicts for a recorded one | T3 | open |
| Q70 | An edit past step 400 fast-forwards against a truncated original | T3 | open |
| Q71 | Divergence rate over real play is measurable and uncollected | T3 | open |
| Q73 | Should the crash path show the expected value, as the wrong-answer path now does? | T3 | open |
| Q75 | Which of the remaining non-negotiables can be given a test? | T6 | open, and four fewer |
| Q76 | The heal curve and pool size were chosen by argument, not playtest | T3 | open — and the scorecard's numbers now join them |
| Q77 | W8 is a waypoint no exit criterion points at. Does T3 land without it? | T3 | **answered** — no. T3 holds until W8 ships (D163) |
| Q78 | Should the pane have a "replace this function" affordance? | T3 | open |
| Q80 | Is `BOSS DOWN` being unreachable from the starters a defect? | T3 | **answered** — no. It is a mastery ending (D158) |
| Q81 | **`score_submission` stores a computed `speed` for practice runs**, from a clock that started when the file was read. The UI hides it; the stored record does not. `score_fight` was written not to. Should the level path match, and what happens to already-banked runs? | T1 | open — the user's call |
| Q82 | **The score cannot see how wrong the code was before it was repaired.** A cleared fight is 100% accurate whether it was patched from 90% or from a guess; only HP distinguishes them. Is reporting the two side by side enough, or should the card read first-attempt accuracy? | T3 | open |
