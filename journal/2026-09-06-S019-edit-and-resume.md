# S019 — The memo was already in the payload

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T3 (W4, W5) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-06-S019.json`](../data/sessions/2026-09-06-S019.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A player can fix the line a fight paused on and the fight carries on from there | ✅ met |
| 2 | A resume that is not really a continuation is said out loud | ✅ met |
| 3 | The edit is what the rest of the fight is judged on | ✅ met |
| 4 | A step is judged on its answer, not on having failed to crash | ✅ met |
| 5 | The whole loop — watch, fail, edit, resume — is playable from the CLI | ✅ met |

## What was built

### `LiveRun.edit` — strategy A, and it was cheap

T3 called W4 "the one waypoint in the project whose difficulty is genuinely
uncertain". It was not, and the reason is worth stating because it is a
property of this codebase rather than of the strategy.

Strategy A re-runs the edited source from the top and fast-forwards to the edit
point, which needs a *memo* of the original inputs. **The memo was already
there.** `LiveRun` holds the test as a JSON payload, because that is how it
crosses the process boundary — so replaying the inputs is re-sending a dict.
There is nothing to record, nothing to snapshot, and nothing that can drift.

The reputation strategy A has for being fragile is earned against programs that
read a clock, a socket, or a file. The shapes this game poses are pure
functions over JSON-ish data, which is exactly the case the trajectory said to
bet on.

Two rules make it behave, and both are about *where* the fast-forward stops.

**It stops at the step the reader is on, never through it.** That step is the
one whose behaviour the player just changed. Replaying it would replay the edit
away — and, worse, would make the divergence detector fire on every successful
fix, because a fixed line is *supposed* to do something different. Getting this
wrong turns the safety net into noise.

**The edit point is where the reader is looking, not where the child is
blocked.** `Timeline.cursor`, not the end of history — so an edit made after
stepping back resumes from there. W3 paid for that for free.

### `timeline.compare` — the safety net, landed with the thing it catches

The handoff said W5 "should probably land with W4, not after it". It should,
and not for tidiness: strategy A is a *claim* that the part the player did not
watch a second time happened the same way. Shipping the claim without the check
is shipping the lie exit criterion 4 names.

It is a pure function over two lists, so it lives in
[`timeline.py`](../vibecoder/timeline.py) next to the cursor, imports nothing,
and its 20 tests run in a millisecond.

**A step's signature is `(func, locals)` — deliberately not the line number.**
The player has just edited the file, so the text has moved. A statement sliding
down a line because a guard clause was added above it is not the program
behaving differently, and a detector that reports it would fire on almost every
edit and teach a player to ignore the warning. The cost is a false negative:
two adjacent statements with identical locals are indistinguishable. That is
the cheaper error, because a missed divergence still surfaces as the run
visibly disagreeing with its own history, whereas a detector that cries wolf
gets switched off.

**Running out early counts as divergence.** A re-run that returns before
reaching the line the player was looking at has not reproduced the prefix
either, and saying nothing would leave them at a position that no longer
exists.

`edit` returns the finding rather than raising or printing it. Only the caller
knows who is watching. The CLI prints it and keeps the fight going, because a
divergent resume is still playable — it just is not continuous, and the player
is told so.

### A stepped run now reports whether it answered

Found while wiring the CLI, and the more important half of this session.
`_run_stepped` called the function and discarded the return value, so a stepped
run produced no outcomes and `_live_step`'s `True` meant *nothing raised*. A
boss step could be cleared by `return None`.

That would have made this session's own evidence false: "editing the paused
line and resuming completes the fight" is exit criterion 3, and it would have
been satisfied by a fix that answers nothing. So step mode now reports one
outcome, for the one test it runs. Scoring a fight is still W6/W7; this is only
the difference between "it did not crash" and "it answered".

This is M1's shape — a thing that looked measured and was not — and it is
written up as M35 below rather than left as a quiet fix.

### The CLI: `--fix`

```
$ vibecoder boss w1-boss-pipeline --live --solution broken.py --fix fixed.py
  Drop the cheap stock  above_floor()
     16 ▸ floor = 10.0
     16 ✘ KeyError: 'prise'
    ▸ edit applied, resumed at step 3
     16 ▸ row = {'name': 'widget', 'price': 25.0, 'quantity': 2}
     ...
  BOSS DOWN
```

and when the edit reaches back into what was already watched:

```
     16 ✘ KeyError: 'prise'
    ✘ replay diverged: step 2 ran above_floor() where it had run <listcomp>()
      the re-run is not a continuation of what you watched
```

The edited source carries forward between boss steps: a fix made at step two is
what step three is judged on, because that is what the player would submit.

`--fix` is a scripted edit, not a keystroke. Nothing yet lets a player type
into a paused fight — that is Q67, still open, and it is why criterion 6 is not
being claimed.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 887 tests in 59.655s — OK      (42 timeline tests in 0.001s; 61 stepping in 5.7s)

$ VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests
Ran 863 tests in 43.915s — OK

$ python3.11 -m vibecoder.cli verify --seeds 3
45/45 reference runs clean
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| The edit becomes the source the child runs | `test_the_edit_becomes_the_source` | verified |
| It resumes at the edit point, not from the top | `test_it_resumes_at_the_edit_point_rather_than_the_top`, 2 steps not 0 | verified |
| The edited step is not replayed away | `test_the_edited_step_is_not_replayed_away`, line 3, not failed | verified |
| The fast-forward leaves the child blocked, not finished | `test_the_fast_forward_leaves_the_child_blocked` | verified |
| A fixed run finishes and answers correctly | `test_the_fixed_run_finishes_and_answers` | verified |
| The replaced history is kept for comparison | `test_the_history_it_replaced_is_kept` | verified |
| Editing from a stepped-back cursor resumes there | `test_editing_from_a_step_the_reader_stepped_back_to`, 0 steps | verified |
| Editing twice works and the last edit wins | `test_it_can_be_edited_more_than_once` | verified |
| A fix confined to the paused line does not diverge | `test_a_fix_confined_to_the_paused_line_does_not_diverge` | verified |
| Changing an already-watched line diverges, at the right index | `test_changing_a_line_already_watched_diverges`, index 1 | verified |
| The fast-forward stops *at* the divergence | `test_the_fast_forward_stops_at_the_divergence` | verified |
| A re-run that ends early is reported, not ignored | `test_a_run_that_ends_before_the_edit_point_diverges` | verified |
| Moved text is not divergence | `TestMovedTextIsNotDivergence`, same step at lines 7 and 9 | verified |
| Divergence works on `Step` objects and recorded dicts alike | `test_objects_and_dicts_compare_the_same` | verified |
| Not crashing is not passing | `test_not_crashing_is_not_passing`, `return None` → passed False | verified |
| The answer given is reported against the expected one | `test_the_answer_it_gave_is_reported`, `("None", "3")` | verified |
| The fight completes from the CLI with an edit | `test_with_a_fix_the_fight_is_completed`, exit 0 + `BOSS DOWN` | verified |
| The CLI says so when the replay diverged | `test_a_divergent_fix_is_said_out_loud` | verified |
| Divergence *rate* on real play | T3's instrument check; nobody has played a diverging fight | `UNVERIFIED` — measurable now, unmeasured |
| Nobody has typed an edit into a paused fight | `--fix` is a file path, not a keystroke; Q67 open | `UNVERIFIED` |

### Against T3's exit criteria

- **1, 2** — verified in S017 and S018.
- **3 — editing the paused line and resuming completes the fight, with the
  edit reflected in the final submitted source:** **met**. `LiveRun.code` is
  the edited text and the CLI carries it into the remaining steps;
  `test_with_a_fix_the_fight_is_completed` runs the fight to `BOSS DOWN`.
  Worth naming what "completes" now means: the step also has to answer, which
  it did not before this session (M35).
- **4 — divergence is never presented as continuous:** **met**. The
  fast-forward stops at the first mismatch and the finding is returned to the
  caller, which prints it.
- **5 — boss HP reaches zero only when every step passes:** open, W6.
- **6 — fully playable from the CLI:** still open, and deliberately not
  claimed. The loop runs end to end, but the edit arrives as a file path
  rather than as something a player types (Q67).

## Misconceptions and corrections

### M34 — there is always a step after the edit point

**Believed:** Writing the test for "the run is stepping again after an edit", I
asserted the next `step()` would take the count from 2 to 3.

**Revealed by:** `AssertionError: 2 != 3`. The fixed source is
`value = n` / `return value` — after fast-forwarding onto `return value` there
is no further line, so the next `step()` ends the run and appends nothing.

**Corrected to:** How many events exist after a point is a property of the code
being run, not of the engine. The test now uses a source with a line after the
edit point, plus a separate assertion that the fast-forward leaves the child
*blocked* rather than finished — which is the property I actually meant.

**Cost:** ~3 minutes. Recorded because it is M33's family again: the code was
right and the test was wrong, and the reflex on a failing assertion is to
suspect the code.

### M35 — a live step that returned `True` had passed

**Believed:** `_live_step` returns a bool and the CLI prints `BOSS DOWN` on
three of them, so a live boss fight was being checked.

**Revealed by:** Reading `_run_stepped` while wiring `--fix`. It calls
`fn(*args)` and throws the value away; step mode filled no `outcomes`, and
`_live_step`'s only test was `if result.error`. A live fight was cleared by
*not raising*.

**Corrected to:** Step mode reports one outcome for the test it runs, and the
CLI checks it. A step cleared by `return None` is now caught
(`test_not_crashing_is_not_passing`).

**Cost:** ~15 minutes, and it was nearly much more expensive than that. This
session's central claim is exit criterion 3, "editing the paused line and
resuming **completes the fight**" — and without this the criterion would have
been satisfiable by an edit that answers nothing. The evidence would have been
written, and it would have been false.

This is **M1's shape**: a thing that looked measured and was not. M1 was free
points on an axis that could not be measured honestly; this was a cleared step
on a check that was not being made. Both were only visible from running the
system adversarially — M1 by scoring a bad solution, this by asking what a
*lazy* fix would do.

## Friction

- `close()` was not re-entrant across a restart: it sets `_closed` and returns
  early, which an edit needs to undo. Split into `close` (and never again) and
  `_teardown` (shut the child down), which is the distinction that was missing
  rather than a workaround.
- An f-string with implicit string concatenation inside the expression is a
  syntax error before 3.12, and this machine is pinned to 3.11 (M5). Caught by
  the import, cost under a minute.
- Choosing what counts as divergence took longer than implementing it. That is
  the right ratio for this waypoint and produced no wasted artefact.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D125 | Edit-and-resume is strategy A: re-run from the top, fast-forward to the edit point | B (frame surgery), C (step-boundary checkpointing) | The memo A needs is the test payload the parent already holds, so replay costs nothing and cannot drift. T3 recommended A and said to measure how often it is wrong; D126 is how we will find out | yes — the seam is `LiveRun.edit`, which C can replace |
| D126 | W5 lands with W4, not after it | Ship the resume, add the detector next session | Strategy A is a *claim* about the part the player did not watch again. Shipping the claim without the check is shipping the thing criterion 4 forbids | no |
| D127 | The fast-forward stops **at** the edit point, never through it | Replay through it and compare the whole prefix | The edited step is the one that is supposed to differ. Replaying it both undoes the edit and makes divergence fire on every successful fix | no — it is the waypoint |
| D128 | The edit point is the cursor, not the end of history | Always resume from where the child is blocked | The player edits the line they are looking at. W3 already tracks that | yes |
| D129 | A step's signature excludes the line number | Compare `(line, func, locals)` | The player just moved the text; moved text is not different behaviour. A detector that fires on every edit gets ignored. Accepts a false negative on adjacent statements with identical locals | yes |
| D130 | `edit` returns the divergence; the caller decides how loudly to report it | Raise, or print from the runner | Only the caller knows who is watching, and `runner.py` must not grow display opinions | yes |
| D131 | A divergent resume continues the fight with a warning | Abort the fight on divergence | It is still playable — it is just not continuous. Criterion 4 asks that the player be *told*, not that the run be stopped | yes |
| D132 | Step mode reports one outcome for the test it runs | Leave correctness to W6/W7 | Without it, "the fight completes" means "nothing raised" and this session's own evidence for criterion 3 would be false. This is not scoring; it is the signal scoring will be built on | no |

## Handoff

- **State:** T3 W4 and W5 are landed together. `LiveRun.edit` re-runs edited
  source and fast-forwards to the edit point; `timeline.compare` says when the
  fast-forward stopped matching, and the fast-forward stops there. Step mode
  now reports whether the step *answered*. T3 exit criteria 1, 2, 3 and 4 are
  verified; 5 and 6 remain. 887 tests green unpinned, `verify` clean on 45
  reference runs.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action: T3 W6, the boss HP model tied to first-try step
  completions.** D132 put the signal in place — a stepped run now says whether
  it answered — so HP has something honest to consume. Read M35 first: the
  reason that signal exists is that its absence would have made a criterion
  claimable by a fix that answers nothing, and HP is the next thing that could
  be gamed the same way.
- **Before W6, decide Q67.** `--fix` proves the engine but is a file path, not
  a keystroke, and criterion 6 ("fully playable from the CLI") is being held
  open because of it. W6 will make a fight *scored*; scoring an experience
  nobody can drive by hand is the wrong order.
- **T3's instrument check is now measurable and unmeasured:** divergence rate
  on edit-and-resume over real play, with ~5% as the line that would justify
  strategy C. Nothing collects it yet. That is Q71.
- **Blockers:** none for T3. T2 W4 remains blocked on a registered OAuth
  application, with T2 otherwise one waypoint from landing.
- **Context required:** D127 before touching the fast-forward — stopping *at*
  the edit point rather than through it is what keeps the detector meaningful.
  D129 before "improving" divergence to compare line numbers; the false
  positive it avoids is the whole reason anyone would trust the warning. M35
  before building anything that decides whether a step was cleared.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q67 | Nothing lets a player type an edit into a paused fight — `--fix` is a file path. Does the edit belong in `boss --live` as a keystroke, in the T7 editor, or somewhere else? Criterion 6 is held open on it | T3 | open |
| Q68 | Two events land on one line when it raises. Should the display merge them into one entry carrying both the values and the failure? | T3 | open |
| Q69 | `Timeline` holds `Step` objects for a live run and dicts for a recorded one. `compare` now handles both by inspection, which works and is a second place that knows about two shapes | T3 | open |
| Q70 | The recording cap is 400 steps, so an edit made past step 400 of a longer run fast-forwards against a truncated original. Divergence would be reported against history the engine does not have | T3 | open |
| Q71 | T3's instrument check — divergence rate over real play, ~5% justifying strategy C — is measurable and uncollected. Where would the counter live, given that runs are not persisted? | T3 | open |
| Q72 | A stepped run executes `tests[0]` only, so a live boss step is cleared on one case while the same step scored normally faces all of them. Is one case enough to call a step passed, once W6 ties HP to it? | T3 | open |
