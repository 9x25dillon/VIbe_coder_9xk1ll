# S017 — Pause is the parent not answering

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T3 (W2) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-06-S017.json`](../data/sessions/2026-09-06-S017.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A submission runs one line at a time under the parent's control | ✅ met |
| 2 | Pause, resume and abort work without a state machine on both sides | ✅ met |
| 3 | A paused fight cannot time out for being watched | ✅ met |
| 4 | The live engine emits the trace shape both renderers already read | ✅ met |
| 5 | A boss is watchable from the CLI | ✅ met |

## What was built

### One decision, and everything follows

> The child runs a line, reports it, and **blocks waiting to be told what to do
> next**.

Three properties fall out of that, and each is a thing not built:

- **Pause needs no implementation.** It is the parent not answering yet. There
  is no pause flag on either side, so there is no pause flag to get out of sync.
- **The child never sleeps.** Pacing, variable speed and fast-forward live in
  the parent, which is where the player is — exactly where T3's slow-motion
  hazard says the controls belong.
- **A paused fight cannot time out.** The child's budget counts *executing*
  time, never time blocked on the parent. A fight that failed for being read
  carefully would defeat the feature.

The payload and the control channel share the child's stdin, which is why the
harness now reads its payload with `readline` rather than `json.load` — the
latter waits for a close that stepping never performs.

### Two rules in the trace hook that look like details

**Every line is reported; only the first 400 are kept.** Recording is bounded
because it is memory the parent is handed. Reporting is not, because stopping it
at the cap would leave a paused parent waiting forever for a line that never
arrives. Both halves were wrong in the first draft, and both were found by
running it rather than reading it.

**The budget is checked on every line**, not only while free-running, so a loop
that runs away after `run` is stopped by its own budget rather than by the
sandbox's CPU limit and a `NoReply`.

### One trace shape, two renderers

The step event carries exactly `{line, func, locals}` — the shape
`_record_trace` already produces. `replay` and `vision` render a live run with
no translation, which is what T3's hazard list asks for, and
`test_a_live_trace_and_a_recorded_trace_agree` asserts the two engines do not
disagree about what happened.

### Watchable

`vibecoder boss <id> --live` runs each step line by line with the changed local
beside it. Loop bodies auto-fast-forward after three laps, because a fixed delay
in a loop stops teaching and starts costing — the hazard list calls that a
requirement, not polish.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 804 tests in 71.555s — OK          (25 of them stepping, in 3.8s)

$ python3.11 -m vibecoder.cli verify --seeds 3
45/45 reference runs clean

$ python3.11 -m vibecoder.cli showcase | grep -c $'\033'
0

$ python3.11 -m vibecoder.cli boss w1-boss-pipeline --live --reference
  Parse the feed  parse_rows()
      3 ▸ lines = ['widget,25.0,2', 'sprocket,3.5,10', ...
      4 ▸ rows = []
      5 ▸ line = 'widget,25.0,2'
      4 ▸ rows = [{'name': 'widget', 'price': 25.0, 'quantity': 2}]
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| Each call advances exactly one line | `test_each_call_advances_exactly_one_line` | verified |
| Locals arrive as they were at that instant | `test_locals_arrive_as_they_were_at_that_instant` | verified |
| The child does not advance while we do not ask | `test_the_child_does_not_advance_while_we_do_not_ask`, 0.3 s of silence | verified |
| A pause longer than the timeout does not fail the run | `test_a_long_pause_does_not_time_out_the_run`, 1.5 s pause on a 1 s budget | verified |
| Resuming runs to completion unprompted | `test_resuming_runs_to_completion_without_further_prompting` | verified |
| Abort stops the run where it stands | `test_aborting_stops_the_run_where_it_stands` | verified |
| An aborted run keeps the steps it reached | `test_an_aborted_run_keeps_the_steps_it_reached`, 5 steps | verified |
| A runaway loop is stopped by its own budget | `test_a_runaway_loop_is_stopped_by_its_own_budget` | verified |
| Stepping past the recording cap does not hang the parent | `test_stepping_past_the_recording_cap_does_not_hang_the_parent`, 430 events | verified |
| The recorded trace is still capped at 400 | `test_the_recorded_trace_is_still_capped` | verified |
| A crash is reported rather than raised, keeping prior steps | two tests in `TestItStaysContained` | verified |
| A step carries exactly the recorded fields | `test_a_step_carries_exactly_the_recorded_fields` | verified |
| `vision` renders a live trace without translation | `test_vision_renders_a_live_trace_without_translation` | verified |
| A live trace and a recorded trace agree line for line | `test_a_live_trace_and_a_recorded_trace_agree` | verified |
| Closing an unfinished run does not hang | `test_closing_without_finishing_does_not_hang` | verified |
| The existing non-stepping protocol still works | `tests/test_runner.py`, `tests/test_sandbox.py` green after the `readline` change | verified |
| The pacing feels right to watch | `--speed` and the loop patience were set by eye on one boss | `UNVERIFIED` — not tuned against a player |

### Against T3's exit criteria

- **1 — a boss level runs step by step with a visible current line and live
  locals:** met. `--live` shows both.
- **2 — a deliberate error pauses execution on the offending line:** *not* met
  and not attempted. A crash currently ends the run and is reported; pausing
  *on* the line is W3's territory.

## Misconceptions and corrections

### M32 — the parent knows when the child is waiting

**Believed:** The parent can infer whether the child is blocked from whether it
has read a step yet. `resume()` therefore sent its command only `if self._steps`
— if no step had been read, there was nothing to release.

**Revealed by:** `test_a_crash_is_reported_rather_than_raised` hanging forever.
It calls `resume()` before any `step()`. The child had already emitted its first
line and was blocked; the parent set its own `free` flag, told the child
nothing, and then waited for a child that was waiting for it. A textbook
deadlock, and one that only appears when resume comes first — every test that
stepped once before resuming passed.

**Corrected to:** Whether the child owes us a line and whether we owe the child
a command are *different facts*, and the parent only knows the second by
tracking it. `_awaiting` is set when a step event is read and cleared when a
command is written, so `resume` before the first `step` releases a child the
parent had not yet heard from.

**Cost:** ~20 minutes, most of it working out which test hung, because a
deadlock reports nothing at all. Worth recording that the passing tests were
not evidence: they all happened to step first.

## Friction

- The first draft of the trace hook returned early once `MAX_TRACE_STEPS` was
  reached, which stopped *both* reporting and the budget check. The runaway test
  then passed for the wrong reason — the sandbox's CPU rlimit killed the child
  and the parent reported `NoReply`. A test can be green because the thing under
  test worked, or because something else caught the failure, and the error type
  is what tells them apart.
- Three attempts to inspect the hanging test with `timeout … ; echo $status`
  returned exit 144 from the shell and swallowed the output, including one that
  silently discarded a redirect. Running it as a background task and reading the
  log worked first time.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D110 | The child blocks after each line; the parent sends the next command | The child sleeps at a configured rate and streams | Pause becomes the absence of a command rather than a state on both sides, and pacing ends up where the player is | no — the protocol |
| D111 | The budget counts executing time, excluding time blocked on the parent | One wall clock for the whole run | A fight paused while somebody reads it must not fail for being watched carefully | no |
| D112 | Every line is reported; only the first 400 are recorded | Stop reporting at the cap, as the recorder does | Recording is memory the parent is handed; reporting is what keeps the parent in control. Stopping it strands a paused parent | no |
| D113 | The step event is exactly the recorded trace shape | A richer live event with extra fields | `replay` and `vision` already read that shape, and a second one means a second renderer | no |
| D114 | The harness reads its payload with `readline` | Keep `json.load`, open a second channel | `json.load` waits for a close stepping never performs. One pipe carrying the payload then the commands is fewer moving parts than two | yes |
| D115 | `_awaiting` is tracked explicitly by the parent | Infer it from whether a step has been read | The two facts differ, and inferring produced a deadlock (M32) | no |
| D116 | Loop bodies fast-forward after three laps | A single configurable delay | A fixed delay inside a loop stops teaching and starts costing; T3 names this a requirement | yes |
| D117 | EOF on the control channel reads as abort | Continue at full speed | Executing on for a parent that will never read the result is the one behaviour that is certainly wrong | yes |

## Handoff

- **State:** T3 W2 is landed. `LiveRun` drives a submission line by line with
  pause, resume and abort; `vibecoder boss <id> --live` watches a fight
  execute. 804 tests green unpinned, `verify` clean on 45 reference runs,
  `showcase` prints zero escapes in a pipe.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action: T3 W3**, step-back over the recorded trace. It is read-only
  history with no re-execution, so it is the cheapest of the remaining
  waypoints and the one that makes W4 approachable — and `LiveRun.steps`
  already holds exactly the history it needs.
- **W3 also unlocks exit criterion 2**, which W2 did not attempt: a deliberate
  error should pause *on* the offending line rather than ending the run. The
  hook currently unwinds on exception; pausing there means reporting the
  exception as a step and waiting, which is a small change to
  `_run_stepped` and a large change to how a failure feels.
- **Blockers:** none for T3. T2 W4 remains blocked on a registered OAuth
  application, with T2 otherwise one waypoint from landing.
- **Context required:** D110 before adding any sleep to the child — the pacing
  belongs to the parent and pause depends on it. D112 before making the cap
  stop reporting. M32 before simplifying the `_awaiting` tracking away.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q63 | `--live` runs each step against its **first** test case only. That is enough to watch, and wrong as a verdict: a step can pass the case you watched and fail the other five. Should the live view say which case it is running, or run all of them? | T3 | open |
| Q64 | The parent has no wall-clock guard at all in stepping mode — the child's executing budget and the player's abort are the only limits. A child that blocks *before* emitting its first step would hang the parent forever. Is a start-up deadline worth adding? | T3 | open |
| Q65 | Loop patience is three laps, chosen by eye. The hazard list also asks for variable speed; `--speed` exists but nothing adapts it. Should the delay shrink as the step count grows, the way `vision.sample` bounds the reveal? | T3 | open |
| Q66 | Stepping runs through `Source.PLAYER`, so it takes the host path. A community boss (T5) stepped live would run untrusted code under `settrace` in a subprocess with an open control channel, which is a wider aperture than a normal run. Does stepping need its own provenance rule? | T2 | open |
