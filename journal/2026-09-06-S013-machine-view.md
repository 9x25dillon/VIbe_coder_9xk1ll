# S013 — Your function, drawn as a machine, running

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T6 (presentation) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-06-S013.json`](../data/sessions/2026-09-06-S013.json)

> **This work maps to no waypoint on any trajectory.** It was requested
> directly — "make it look and feel more like a game" — while T2 W6 was being
> started, and it is recorded here as unplanned rather than folded into a
> waypoint it does not belong to. T6 is `LANDED`, so filing it under T6 is the
> closest honest home rather than a comfortable one; see Q51.

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A player can see *why* their solution cost what it cost | ✅ met |
| 2 | The picture is driven by the recording, never guessed from the source | ✅ met |
| 3 | Every frame is testable without a terminal | ✅ met |
| 4 | It plays in the score reveal without slowing the submit loop | ✅ met |
| 5 | T2 W6 started | ⛔ deferred — superseded mid-session by the above |

## What was built

### The machine view

A score says a solution cost 5,958 operations. It does not show *why*, and why
is what the Functional axis exists to teach. `vibecoder vision` draws the
submitted function as apparatus — statements are boxes wired top to bottom, a
loop is a box with a return rail down its left side — and walks the recorded
execution through it. The token sits where control is; the counter climbs each
time control comes back round a loop. An O(n²) solution is visibly a machine
whose inner ring spins while the outer barely turns.

Two properties keep it honest rather than decorative.

**It is driven by the recording.** Frames come from the same line-by-line trace
`replay.py` consumes and T3's live engine will consume. Nothing re-executes and
nothing guesses: if the trace says control was on line 7, the box holding line 7
lights up, and **a branch that was never taken never lights up**.

**Every frame is a value.** `render` returns a `Screen`, so all 46 tests assert
on `as_text()` with no pty — the same way the editor is tested. `vision.py`
writes no escape sequence of its own; styles arrive through the new
`ui.Renderer.style` and the escapes are `Screen.diff`'s business.

The layout is a vertical spine rather than a flowchart on purpose. Arbitrary
control flow needs edge routing, which needs a graph layout engine, which is a
dependency (N1) and a large pile of code that would mostly draw diagonal lines.
Sequence, loop, branch and return is what player solutions are made of.

Each drawing rule is a claim about where control is, not a preference: a
compound statement owns its header line only, so the token is never in two boxes
at once; a simple statement owns every line it spans, since the trace may report
any line of a call broken across four; an `elif` gets no `else` box, because an
`elif` is an `If` inside `orelse` and drawing "else" invents a step nobody wrote
— the same reasoning as D65.

### In the reveal, on a budget it cannot exceed

It plays after the test results and before the axes land. This is the hottest
path in the product, so the wiring is bounded rather than trusted: a trace runs
to 400 steps, which at a watchable frame rate is over half a minute. Frames are
**sampled to 36** and the delay capped so the whole thing fits 2.5 seconds.

Sampling rather than racing the delay, because sampling is the honest one. Every
frame carries state computed over the *whole* trace before sampling happens, so
a kept frame's loop counter is the true count at that instant rather than a
count of the frames that survived.

`_play_vision` never raises. A stream that cannot animate gets nothing at all
here — the one place the reveal differs from the command, which falls back to a
still frame.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 706 tests in 54.271s — OK

$ python3.11 -m vibecoder.cli verify --seeds 3
36/36 reference runs clean

$ python3.11 -m vibecoder.cli showcase | grep -c $'\033'
0

worst-case reveal, against a full 400-step trace:
  trace steps 400 -> frames drawn 36 -> delay 0.069s -> wall 2.50s (budget 2.5s)

piped `play`, before and after the reveal wiring:
  diff <(before) <(after)  ->  identical
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| A line lights the box that owns it | `test_a_line_lights_the_box_that_owns_it` | verified |
| A branch never taken never lights up | `test_a_branch_never_taken_never_lights_up` | verified |
| A compound statement owns its header line only | `test_a_compound_statement_owns_only_its_header_line` | verified |
| An `elif` invents no `else` box | `test_an_elif_chain_does_not_invent_an_else_box` | verified |
| A loop counts laps, not visits | `test_staying_in_the_loop_body_does_not_count_an_iteration` | verified |
| A helper step keeps the last box lit and says where | `test_a_step_inside_a_helper_keeps_the_last_box_lit_and_says_where` | verified |
| The return rail reaches the loop's deepest body | `test_the_return_rail_reaches_the_last_nested_box`; fails when the bug is reintroduced | verified |
| Nested boxes share a right edge | `test_nested_boxes_share_a_right_edge`; fails when the bug is reintroduced | verified |
| Layout is identical without Unicode | `test_the_layout_is_identical_without_unicode`, equal line lengths | verified |
| A frame carries no escape of its own | `test_a_frame_carries_no_escape_sequence_of_its_own` | verified |
| The viewport keeps the live box on screen | `test_the_viewport_keeps_the_live_box_on_screen`, 42-part function | verified |
| Sampling preserves the true count at each instant | `test_a_sampled_frame_keeps_the_true_count_at_that_instant`, 20 laps | verified |
| The first and last instants always survive sampling | two tests in `TestTheRevealBudget` | verified |
| The reveal cannot exceed its budget | measured: 36 frames × 0.069 s = 2.50 s on a 400-step trace | verified |
| A piped `play` is unchanged by the wiring | `diff` of piped output across the commit boundary | verified |
| It runs end to end on a real recorded run | `w2-l1-revenue`, 14 steps, 5 laps drawn | verified |
| The animation reads well to a player mid-solve | judged by eye on one level, by one person | `UNVERIFIED` — not tested with a player |

## Misconceptions and corrections

### M27 — the stdlib is a representative repository

**Believed:** T2 W6's budgets could be sized from measuring the profiler against
Python's standard library. It read 732 files in 12.5 s — 17.1 ms per file — so a
5,000-file repository would take about 85 seconds, well past any sane budget,
and exit criterion 6 would have to settle for "partial" on an ordinary repo.

**Revealed by:** Building an actual 5,000-file repository and profiling it:
**12.0 s**, 2.4 ms per file. The stdlib averages 16.6 KB per file; the synthetic
repo 1.3 KB. Per-file cost and per-byte cost are different quantities, and the
stdlib is an outlier on the one I extrapolated through.

**Corrected to:** A 5,000-file repository comfortably *completes*, so criterion 6
is met by finishing rather than by degrading. The budget defaults should be
picked from a realistic corpus, and the honest version of the earlier number is
that the profiler runs at roughly 1.1–1.8 MB/s with analysis taking 64% of it
(parse 4.37 s, analyse 7.69 s on the stdlib) — linear, not quadratic.

**Cost:** ~10 minutes, and it would have shipped budgets sized for the wrong
shape of input. Recorded here rather than in W6's eventual entry because the
measurement happened here and the number is the useful part.

### M28 — a pipe should get the still frame everywhere

**Believed:** `vision`'s fallback — a stream that cannot animate gets one still
frame — was a property of the machine view, so the reveal should inherit it.
Wiring it in, the same fallback fired for piped `play`.

**Revealed by:** Looking at the piped transcript. Every piped `play` had gained
twenty lines of box drawing, which meant every CI log and every captured
transcript had too.

**Corrected to:** The fallback belongs to the *command*, not to the reveal. The
still frame exists because somebody asked to see the machine; the reveal is a
live flourish and has no business changing a non-interactive transcript. The
reveal now draws nothing when the stream cannot animate, and the claim that
piped output is unchanged is verified by diffing across the commit boundary
rather than asserted.

**Cost:** ~5 minutes. Worth recording because the fallback was *correct* in the
place it was written and wrong one caller up, which is not a kind of mistake
that a test of the original module would ever catch.

## Friction

- Two rendering bugs shipped into the first draft and were caught by looking at
  output rather than by reasoning: the loop's return rail terminated on the
  loop's own body row, so it never reached the code it returns from; and nested
  boxes kept a fixed width, so right edges were ragged and nesting did not read
  as nesting. Both now have tests, and both tests were confirmed to fail when
  the bug is reintroduced.
- `p_play.add_argument("--no-vision", ...)` was inserted against a text anchor
  that matched *earlier* in the file than the `p_play` parser it belonged to,
  producing a reference to an undefined name. Caught immediately by `--help`.
  Anchoring an edit on a string that appears more than once is the hazard.
- The first scratch solution used `>=` where the level's reference uses `>`, so
  the run animated end to end was a 4/5 run rather than a clean pass. The
  animation was real; the solution was not correct, and saying "a real passing
  run" would have been wrong.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D78 | The machine is drawn as a vertical spine with loop return rails | A real flowchart with edge routing | Edge routing needs a graph layout engine: a dependency (N1) and a lot of code to draw diagonal lines. Sequence, loop, branch, return is what solutions are made of | yes |
| D79 | Frames come from the recorded trace, never from the source | Animate the AST directly | A branch that never ran must never light up. Anything derived from the source alone would be a diagram, not a run | no — this is the feature |
| D80 | `render` returns a `Screen`; frames are values | Write to the terminal directly, as `replay.py` does | A frame that is a value is a frame a test can compare, with no pty. It is also what keeps this module free of escape sequences | yes |
| D81 | `ui.Renderer.style` added; `vision` never emits an escape | Copy `editor.py`'s private `style` helper | The rule is that `ui` owns escapes. `editor.py` rolling its own predates this and was left alone as out of scope | yes |
| D82 | A compound statement owns its header line only | Own the whole span | Owning the span puts the token in two boxes at once — a false claim about where control is, not a drawing artifact | no |
| D83 | The reveal samples to 36 frames rather than shortening the delay | Race all 400 frames inside the budget | Sampling keeps each frame legible and keeps every counter true, because state is computed before sampling. 400 frames in 2.5 s is a blur | yes |
| D84 | A non-animating stream gets nothing in the reveal | Inherit the command's still-frame fallback | The still frame answers a request to see the machine. Adding it to the reveal changes every CI log and piped transcript (M28) | yes |
| D85 | `_play_vision` never raises | Let errors surface | Nothing decorative may be able to break the reveal. A failed submission already has a failure block; a broken drawing on top of it is noise | yes |
| D86 | The parked W6 `VibeVector` fields were reverted, not left in place | Keep them as groundwork | Three defaulted fields nothing sets is a persisted schema change with no behaviour behind it, and a later reader has to work out why `partial` is always false | yes |

## Handoff

- **State:** The machine view ships in two places: `vibecoder vision [run-id]`
  on demand, and inside the score reveal bounded at 2.5 s. 706 tests green
  unpinned, `verify` clean on 36 reference runs, `showcase` prints zero escapes
  in a pipe. Working tree clean; three commits pushed.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action: T2 W6**, which was started and parked. Two decisions were
  already taken with the user and still stand: the vector records
  `partial` / `partial_reason` / `files_seen`, and a partial profile **is**
  saved, flagged. The field additions were reverted (D86), so W6 restarts from
  a clean `models.py` with those decisions made. Do not re-ask them.
- **What W6 still needs**, in order: a lazy pruning walk (`os.walk` with
  in-place `dirnames` pruning — today's `sorted(root.rglob("*.py"))` descends
  into `.git` and `node_modules` and only then filters, which *is* the hang on
  a monorepo); a `ProfileBudget` enforced in `profile_sources`; and the answer
  to Q46 — the streaming `max_source_bytes` rejection in `ingest` should
  probably become a truncation, since by the streaming stage hostility has
  already been ruled out.
- **Measurements already taken, do not redo them:** 5,000 files / 6.56 MB
  profiles in 12.0 s (2.4 ms per file); the stdlib's 732 files / 12.16 MB in
  12.5 s; analysis is 64% of that and is linear. A 5,000-file repository
  therefore *completes* rather than degrading, so exit criterion 6 is met by
  finishing. See M27 before sizing any budget from the stdlib.
- **Blockers:** T2 W4 remains blocked on a registered OAuth application.
- **Context required:** D79 before making the machine view show anything the
  trace does not say. D84 before adding output to the reveal. M28 for why a
  fallback can be right where it is written and wrong one caller up.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q48 | The machine view has been judged by one person on one level. Does it read to somebody mid-solve, or is it decoration they skip? The `--no-vision` opt-out is the cheapest instrument we have: if it gets used, that is the answer. | T6 | open |
| Q49 | Sampling makes the step number jump, which is the cue that instants were skipped. Nothing *says* so. Is the jump enough, or should a sampled run be labelled as sampled? | T6 | open |
| Q50 | `_target_function` picks `solve`, else the last function. A submission whose real work is in a helper draws the wrong machine and only says `in helper()`. Should the view follow the call, or should it draw every function and let the token move between them? | T6 | open |
| Q51 | This work belongs to no waypoint and is filed under a `LANDED` trajectory. Either T6 reopens, or the machine view and whatever follows it deserve a trajectory of their own. Which is a call for the user, not for a session that wants somewhere to file its entry. | — | open |
| Q52 | `editor.py` carries a private copy of the `style` helper that now lives on `ui.Renderer` (D81). Folding it in is a small change to the T7 hot path. Worth doing, or is a duplicated six-line helper cheaper than touching the editor? | T7 | open |
