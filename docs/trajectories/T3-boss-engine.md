# T3 — Boss engine: interactive slow-motion debugger

**Design phase:** 2 · **Status:** `PLOTTED` · **Target:** 2026-09-20 ·
**Depends on:** T2 (execution boundary must be settled first)

## Heading

The boss fight is the design's most distinctive idea and its hardest
engineering problem. The pitch: your code runs one line every few seconds, you
watch it happen, and when it breaks you **fix the line and resume from that
point** rather than starting over.

That last clause is the whole feature. Replaying a recording — which T1 already
ships in `replay.py` — is a visualisation. Editing mid-flight and continuing is
a *live interpreter under external control*, and it is where the difficulty
lives. This trajectory exists to confront that honestly rather than let
"slow-motion debugger" stay a bullet point.

## The actual problem

`sys.settrace` gives a hook before each line and lets you set `frame.f_lineno`
to jump within a frame. It does **not** let you swap out the code object of a
running frame. So "edit line 7 and continue" is not something CPython supports
directly, and the design has to pick a strategy:

| Strategy | How it works | Cost |
| --- | --- | --- |
| **A. Restart-with-memo** | On edit, re-run from the top, replaying recorded inputs, fast-forwarding silently to the edit point | Simple and safe. Breaks on side effects and non-determinism. |
| **B. Frame surgery** | Recompile, build a new frame, copy locals across, resume at the mapped line | Feels genuinely live. Line mapping after an edit is ambiguous, and the failure modes are confusing. |
| **C. Step-boundary checkpointing** | Snapshot locals each step; on edit, rebuild a frame from the nearest valid snapshot | Middle ground. Snapshot cost per step; deep-copy semantics get hairy for mutable state. |

**Recommendation: start with A, measure how often it is wrong.** For the level
shapes the game actually poses — pure functions over JSON-ish data — the inputs
are recorded and replay is deterministic, so A is correct far more often than
its reputation suggests. Ship A behind an interface that C can replace, and
treat "how often did replay diverge?" as the metric that justifies the upgrade.

## Waypoints

| ID | Waypoint | Notes |
| --- | --- | --- |
| W1 | Multi-step boss level format: ordered steps, per-step tests, shared state | A boss is `n` linked functions, not one big one. |
| W2 | Live stepping under `sys.settrace` with pause / resume / abort | Real interpreter, driven by a control channel. |
| W3 | Step-back over the recorded trace | Read-only history; no re-execution. |
| W4 | Edit-and-resume via strategy A | Requires deterministic input replay. |
| W5 | Divergence detector | Compare replayed trace to the original prefix; if it differs, say so instead of lying. |
| W6 | Boss HP model tied to first-try step completions | Per the design: correct-first-time steps damage the boss. |
| W7 | Boss scoring at 40/30/30 weights (`BOSS_WEIGHTS`, already defined) | Elegance judged by static analysis against the reference. |
| W8 | Two boss fights: World 1 (data pipeline) and World 2 (algorithm assembly) | The design's web-scraper boss needs network, so it waits for T2 W2. |

## Exit criteria

1. A boss level runs step by step with a visible current line and live locals.
2. A deliberate error pauses execution on the offending line, not after it.
3. Editing the paused line and resuming completes the fight, with the edit
   reflected in the final submitted source.
4. When replay diverges from the original execution, the player is told
   explicitly; the engine never presents a divergent state as continuous.
5. Boss HP reaches zero only when every step passes.
6. A boss fight is fully playable from the CLI with no web front-end.

## Known hazards

- **This is where the schedule will slip.** W4 is the only waypoint in the
  project whose difficulty is genuinely uncertain. Budget accordingly, and
  ship W1–W3 as a playable "watch it run" boss before attempting W4, so a slip
  degrades the feature instead of deleting it.
- **Side effects break replay.** Any boss step that prints, writes, or calls the
  network cannot be silently re-run. Either forbid side effects in boss steps or
  record and suppress them on replay. Forbidding is cheaper and probably fine.
- **Slow motion is boring at the wrong speed.** 1 line / 2 s (the design's
  figure) is ~2 minutes for a 60-line function. Needs variable speed, a skip
  control, and probably auto-fast-forward through loop bodies after the first
  couple of iterations.
- **The trace format is already load-bearing.** `replay.py` consumes it today;
  the live engine must emit the same shape so both paths share one renderer.

## Instrument checks

- Divergence rate on edit-and-resume, measured over real play sessions. If it
  exceeds ~5%, strategy C is justified.
- Time-to-first-frame when a boss fight starts.
- Player-visible: does anyone finish a boss fight without abandoning it? The
  drop-off point in the step sequence is the number that matters.
