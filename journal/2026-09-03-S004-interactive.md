# S004 — Into the alternate screen

**Date:** 2026-09-03 · **Duration:** — · **Trajectory:** T7 ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-03-S004.json`](../data/sessions/2026-09-03-S004.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | The terminal is returned to its original state on every exit path | ✅ met |
| 2 | Editing correctness is provable with no terminal involved | ✅ met |
| 3 | A keystroke redraws the cells that changed, not the screen | ✅ met |
| 4 | A keystroke is handled inside a 16 ms frame budget, measured | ✅ met |
| 5 | The editor is usable with no colour and no Unicode | ✅ met |
| 6 | Code can be written, run and scored without leaving the screen | ✅ met |
| 7 | Typing rhythm is observable | ✅ met |
| 8 | The three axes assemble in place after a run | ⚠️ partial — animated reveal, not streamed |

## What was built

Eight modules, none of which knows about more than one thing.
[`term.py`](../vibecoder/term.py) owns the terminal;
[`keys.py`](../vibecoder/keys.py) turns bytes into key events;
[`editing.py`](../vibecoder/editing.py) is a text buffer that has never heard of
a screen; [`screen.py`](../vibecoder/screen.py) is a cell grid that diffs
itself; [`highlight.py`](../vibecoder/highlight.py) colours code that is
usually invalid; [`pulse.py`](../vibecoder/pulse.py) watches the keyboard;
[`keymap.py`](../vibecoder/keymap.py) is a table; and
[`editor.py`](../vibecoder/editor.py) is layout and dispatch over the top of
them. `vibecoder edit <level>` opens it.

The split is the design. Every hard question in a terminal application is
either *is the text right* or *is the drawing right*, and mixing them is what
makes TUIs untestable — you end up needing a pty to find out whether backspace
joins lines correctly. Here `compose()` is a pure function from state to a
grid, so a frame can be asserted as plain text in CI, and the buffer's 35 tests
never touch a terminal at all.

**Restoration gets three independent mechanisms** because each misses a case
the others catch: `try/finally` through the context manager, `atexit` for
interpreter shutdown, and handlers for `SIGTERM`/`SIGHUP` for being killed.
`restore()` is idempotent so all three firing is free. `SIGINT` is deliberately
absent — raw mode turns off ISIG, so Ctrl-C arrives as a key event and the
application decides what it means. The pty suite kills a child six different
ways and reads `termios` attributes back afterwards; it is the only part of
this trajectory that could not be tested honestly without a real terminal.

The visualiser reports and does not score. Rhythm is behavioural data about a
person, it stays on the machine that produced it, and it is not attached to a
submission. N5 also applies: what an even cadence *means* about a programmer is
not established, so `evenness` is an observation, not an axis.

**On objective 8.** The waypoint asks for the axes to assemble "as tests
report". They do not. `_harness.py` returns one JSON object at the end of a
run, so there is nothing to stream, and building a streaming protocol was not
in this waypoint. What shipped is an animated reveal of a finished result over
0.9 s, which looks like the intended thing and is not it. Recorded as partial
rather than met, and as Q17 rather than quietly redefined — this is what N7 is
for, and the temptation to call it met was real.

## Evidence

```
$ python3 -m unittest discover -s tests
Ran 398 tests in 6.403s — OK

$ python3 -m unittest tests.test_term          # pty-driven restoration
Ran 15 tests — OK

$ python3 -m vibecoder.cli edit w1-l1-revenue  # driven through a pty
  acc ████████  spd ████████  fn █████░░░              102.7  ★★★

keystroke latency, worst of 200, truecolor:
  10 lines,   80x24   median 2.12ms  p95  2.31ms  worst  4.79ms
  400 lines,  80x24   median 2.88ms  p95  3.13ms  worst  5.46ms
  4000 lines, 200x50  median 5.46ms  p95 10.32ms  worst 12.69ms

damage over a 146-keystroke session at 80x24:
  4386 cells emitted / 4380 changed = ratio 1.00
  30 cells per keystroke, against 1920 for a full repaint
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| The terminal is restored on normal exit, exception, SIGTERM, SIGHUP and `sys.exit` | `tests/test_term.py::TestRestoration`, 8 pty tests reading `termios` back | verified |
| Raw mode is genuinely entered, so the above is not vacuous | `::test_raw_mode_is_actually_entered` | verified |
| Every private-mode sequence enabled is disabled | real run: alt screen 1/1, cursor 1/1, paste 1/1 | verified |
| Editing is correct without a terminal | `tests/test_editing.py`, 35 tests, no pty | verified |
| Undo works across multi-line edits | `::test_undo_crosses_multiple_lines` | verified |
| One keystroke repaints one cell | `tests/test_screen.py::test_a_single_character_edit_repaints_a_single_cell` | verified |
| Damage ratio sits at 1.0 | 4386/4380 over a realistic session | verified |
| A keystroke fits the 16 ms budget | worst 12.69 ms at 4000 lines on a 200×50 terminal | verified |
| An uncoloured frame contains no non-ASCII and no colour | `tests/test_editor.py::TestDegradation` | verified |
| Row widths are identical across capabilities | `::test_glyphs_have_equal_width_at_both_capabilities` | verified |
| Highlighting never alters the text | every prefix of a program round-trips | verified |
| Code runs and scores in place | driven through a pty to `102.7 ★★★` | verified |
| The editor's result matches the CLI's | `tests/test_editor.py::test_running_from_the_editor_matches_running_from_the_cli` | verified |
| A terminal below the minimum shows a legible message | `TestSmallTerminal`, 5 tests | verified |
| The axes assemble *as tests report* | not built; the harness returns one object at the end | `UNVERIFIED` |
| The visualiser is pleasant over an hour | needs a person, not a test | `UNVERIFIED` |

## Misconceptions and corrections

### M7 — An idle redraw tick can safely resolve a held Escape

**Believed:** The loop could call `decoder.flush()` whenever a read timed out.
Escape is only ambiguous until more bytes arrive, and if none did, it was a
bare Escape.

**Revealed by:** Driving the real editor through a pty and reading the frame it
drew. Shift-Tab had put the literal characters `[Z` into the buffer, twice, and
the run failed with `SyntaxError: '[' was never closed`. The redraw loop calls
`flush()` every 50 ms; any escape sequence whose bytes straddle a tick was
being torn into an Escape key followed by its remaining bytes as text.

**Corrected to:** Held input is only resolved after `ESCAPE_TIMEOUT` of genuine
silence, tracked from the last byte actually received. Below that threshold
`flush()` returns nothing and keeps waiting, which is what vim's `ttimeoutlen`
has always been for.

**Cost:** ~20 minutes. It would have shipped. Every headless test passed —
`feed(b"\x1b")` then `feed(b"[A")` decodes correctly, because in a test the two
calls are adjacent. The bug lives entirely in the *timing* between them, which
is a thing only a real terminal has. Two lessons: the pty suite tests
restoration and should also test decoding under realistic delivery; and a
component tested only through its own interface can be correct in isolation and
wrong in the loop that drives it.

### M8 — Highlighting the buffer on every keystroke is affordable

**Believed:** `tokenize` is fast and buffers are small, so re-highlighting the
whole buffer per keystroke would sit comfortably inside the frame budget.

**Revealed by:** `test_the_budget_holds_on_a_large_buffer`, written to *record*
a number rather than to catch anything. It failed at 26.2 ms against a 16 ms
budget on a 400-line buffer — tokenising 400 lines to draw 18 of them.

**Corrected to:** `highlight_window` tokenises only the visible slice. Two
problems make a slice harder than a whole file: it may begin indented, which
`tokenize` rejects outright, and it may begin inside a triple-quoted string,
which it cannot know. The first is solved by dedenting and shifting the columns
back; the second degrades to plain text for the affected lines, which is the
contract the module already keeps. Worst case fell to 12.69 ms on a buffer ten
times larger.

**Cost:** ~15 minutes. The exit criterion said "measured, not asserted", and
writing the measurement as a test is what turned an assumption into a number.
An assertion of the form "this is fast enough" would have passed forever.

## Friction

- The captured pty transcript initially showed no restore sequences at all,
  which looked like a serious bug for twenty minutes. The harness was closing
  the pty before the child's final write; the application had been restoring
  correctly the whole time. A measurement apparatus can fail in exactly the
  shape of the bug it is looking for.
- Two of the first editor tests failed on the assertion rather than the code —
  one matched `\033[3` and caught cursor-positioning rather than colour, the
  other asserted a scroll offset before the frame that computes it had been
  composed. Both were rewritten to say what they actually meant.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D16 | Editing logic is a separate module from drawing | One editor class owning buffer and screen | Makes correctness provable headless; a renderer bug can never be a text bug | no — it is the shape of the trajectory |
| D17 | A backend-free cell grid with a frame diff | Redraw everything each keystroke; use `curses` | 30 cells per keystroke instead of 1920, and `curses` is a dependency N1 forbids | yes |
| D18 | Restoration by three mechanisms, `restore()` idempotent | `try/finally` alone | Each mechanism misses a case the others catch; the cost of overlap is zero | no |
| D19 | Held Escape resolves on a timeout, not on an idle tick | Resolve whenever a read returns nothing | M7: the eager version types escape sequences into the buffer | yes |
| D20 | Only the visible window is tokenised | Highlight the whole buffer; cache by text | M8: cost must scale with the window, not the file | yes |
| D21 | Rhythm is reported, never scored | Feed cadence into the elegance axis | N5 — what an even cadence means is not established | yes |
| D22 | Reverse video is emitted at `Depth.NONE`, colour is not | Suppress every attribute, as `Renderer.paint` does | Otherwise `NO_COLOR` leaves the editor with no visible cursor; reverse video is not colour | yes |
| D23 | The editor banks a cleared level in full | Treat it as practice, as `cmd_play` does for a file | This front-end knows the real solve time, so the Speed axis is honest — the case `cmd_play`'s comment anticipated | yes |

## Handoff

- **State:** T7 W1–W7 `LANDED`, W8 partial. `vibecoder edit <level>` is a
  working full-screen editor: type, run with Ctrl-R, see the score in place.
  398 tests green on the subprocess and bubblewrap backends, `verify` clean on
  18 reference runs. T2 W1 landed earlier the same day
  ([S003](2026-09-03-S003-sandbox-seam.md)); T1 and T6 remain `LANDED`.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action:** back to **T2 W2** — seccomp, uid mapping, and
  `tests/test_sandbox_escape.py`. T7 was opened out of sequence at the user's
  request while T2 was in flight; T2 is the trajectory that is actually late.
  If T7 is picked up again first, the honest next step is W8 proper, which
  needs the harness to stream per-test results (Q17).
- **Blockers:** none.
- **Context required:** [`docs/UI.md`](../docs/UI.md), which now covers the
  editor and the one place it deliberately diverges from `Renderer`; M7 above
  before touching the input loop; the hazard list in
  [T7](../docs/trajectories/T7-interactive.md) before adding any motion.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q14 | The pty suite tests restoration but not decoding. M7 was a timing bug that every headless test passed. Should the pty harness grow a "deliver these bytes with these delays" mode, and would that have caught it? | T7 | open |
| Q15 | Rhythm data is collected and shown but never stored. Is it worth persisting locally so the profiler can use process signal as well as residue, and what is the consent story if so? | T7 | open |
| Q16 | Two modules now turn an RGB into an escape code — `Renderer.paint` for strings, `Editor.style` for cells. Should the grid learn to consume `Renderer` output, or `Renderer` learn to emit style prefixes? | T7 | open |
| Q17 | W8 wants the axes to assemble as tests report, which needs `_harness.py` to stream per-test results rather than return one object. Worth a protocol change, or is the animated reveal enough? | T7 | open |
| Q18 | There is no way to save the buffer. A crash mid-level loses the work. Is a scratch file the answer, or does that reintroduce the disk round-trip the editor exists to remove? | T7 | open |
