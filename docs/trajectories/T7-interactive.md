# T7 — Interactive play: editor, motion, visualiser

**Design phase:** cross-cutting · **Status:** `LANDED` · **Target:** — ·
**Landed:** 2026-09-08 · **Depends on:** T6 (`LANDED`)

## Heading

T6 taught the game to *draw*. It cannot yet *react*. Everything VibeCoder shows
today is a transcript: emitted once, scrolled past, gone. The player writes code
in some other window, comes back, and reads a report about what happened
somewhere else.

That is a strange shape for a game about how you write code. The most
interesting signal the project has — the rhythm of a person actually typing,
pausing, deleting, rewriting — is thrown away before scoring begins, because
nothing is watching the keyboard. The Vibe Profiler reads finished source with
`ast` and infers habits from the residue. Sitting inside the editor would let it
observe the process rather than reconstruct it.

So T7 moves the game into the alternate screen: a full-screen terminal
application with a real code editor in it, live syntax colouring, and a
visualiser that responds to keystrokes as they happen. The player writes, sees
the code react, runs it without leaving, and watches the score assemble in
place.

The constraint that shapes every decision here is N1. There is no `textual`, no
`rich`, no `blessed`, no `curses` convenience layer worth the dependency —
`termios`, `tty`, `select` and the escape codes T6 already owns. That is more
work, and it is the same argument the project has already made about metrics:
a thing you can read in this repository beats a thing you borrowed.

## Waypoints

| ID | Waypoint | Notes |
| --- | --- | --- |
| W1 | Raw-mode terminal session: alt screen, hidden cursor, restored on any exit | The foundation. A crash that leaves the terminal in raw mode is the failure mode that makes people distrust TUIs. |
| W2 | Key decoder: printable keys, control keys, arrows, and a bracketed-paste path | Escape sequences arrive as bytes over time, so this is a small state machine, not a lookup table. |
| W3 | Text buffer with cursor, selection-free editing, undo/redo | Pure data structure, no drawing. Testable without a terminal at all. |
| W4 | Damage-tracked frame renderer: diff two frames, emit only changed cells | Redrawing everything each keystroke flickers and wastes bandwidth over ssh. |
| W5 | Live syntax highlighting via `tokenize`, degrading to plain at `Depth.NONE` | Reuses T6's palette. Must survive a partial line that does not tokenise. |
| W6 | Typing visualiser: keystroke rhythm, burst/pause detection, an afterglow trail | The signal the profiler currently cannot see. |
| W7 | In-editor run: execute the buffer through `run_code`, show results in place | Closes the loop. No leaving the screen to find out what happened. |
| W8 | Live score panel: the three axes assembling as tests report | T6's `axis_row` and `gauge`, driven by a run in progress. |

## Exit criteria

1. Any exit path — normal quit, exception, `SIGINT`, `SIGTERM`, `SIGHUP` —
   leaves the terminal in its original mode with the cursor visible.
2. The editor is usable with no colour, no Unicode, and no animation: every
   glyph has an ASCII fallback of identical width, per T6's rule.
3. A keystroke produces a visible change in under 16 ms at an 80×24 terminal,
   measured, not asserted.
4. A frame redraw emits only the cells that changed. A single-character edit on
   one line does not repaint the screen.
5. Editing correctness is proved without a terminal: the buffer's tests run
   headless in CI, including undo across multi-line edits.
6. Syntax highlighting never changes the text, only its colour — the T6
   depth-invariance rule, extended to the editor.
7. Running code from inside the editor produces the same `RunResult` as running
   the same source through the CLI.
8. The typing visualiser degrades to a static summary when `animate` is false,
   and the game is fully playable with `VIBECODER_NO_ANIM=1`.
9. A terminal narrower than the editor's minimum shows a legible message rather
   than a corrupted frame.

## What landing it needed

W1–W8 shipped across [S004](../../journal/2026-09-03-S004-interactive.md),
[S007](../../journal/2026-09-03-S007-streaming.md) and
[S008](../../journal/2026-09-03-S008-latency.md), and the board recorded the
trajectory as complete for five sessions. Checking the criteria one at a time
in [S026](../../journal/2026-09-08-S026-landing-t7.md) found that **two of the
nine had no evidence**, and one of those was not merely untested but false:

- **Criterion 8 was not met.** The typing visualiser animated identically at
  `animate=True` and `animate=False` — the rhythm trail is a function of `now`,
  so it scrolled and drained at twenty frames a second on terminals that had
  asked for no animation. It now degrades to a reading taken at the last
  keystroke, so an idle editor composes an identical frame and puts *zero*
  bytes on the wire.
- **Criterion 1 named `SIGINT` and nothing tested it.** `term.py` installs no
  `SIGINT` handler, deliberately and correctly — raw mode clears `ISIG`, so
  Ctrl-C arrives as a key. But an externally delivered `SIGINT` still raises
  `KeyboardInterrupt`, which is a `BaseException`. That path is now tested,
  as is the premise that `ISIG` really is off. The criterion also says "with
  the cursor visible", and only the *normal* exit path had ever asserted
  `CURSOR_SHOW`; every abnormal path now does.

The instrument checks are a weaker story than the criteria and are recorded
that way rather than quietly counted as met — see the section below.

## Known hazards

- **Terminal restoration is the whole ballgame.** Raw mode plus alternate
  screen plus a hidden cursor is three pieces of global state on a resource the
  process does not own. Restoration has to be driven by `try/finally` *and*
  signal handlers *and* `atexit`, because each one misses a case the others
  catch.
- **`tokenize` raises on incomplete input.** A buffer mid-edit is nearly always
  incomplete Python. The highlighter must treat a tokenise failure as "colour
  what parsed, leave the rest plain", never as an error.
- **Damage tracking is a cache, and caches go stale.** A renderer that believes
  a cell is unchanged when it is not produces artefacts that survive until the
  next full repaint. A forced full repaint on resize and on demand (`^L`) is the
  escape hatch.
- **Wide characters and combining marks break column arithmetic.** An emoji in
  a comment is two columns wide and one character long. Either handle width
  properly via `unicodedata.east_asian_width` or refuse to render the line.
- **The visualiser can become the point.** Motion that competes with the code
  for attention makes the editor worse. Every effect must be judged with the
  question "would I want this on hour three", not "is this impressive in a
  screenshot".
- **Measuring typing is measuring a person.** Keystroke timing is behavioural
  data. It stays on the machine that produced it, exactly like source under
  T2's ingestion commitment, and it never leaves with a score submission.

## Instrument checks

Recorded honestly at landing: two are met, one is partly met, one was never
built. A trajectory does not land on its instrument checks — they are how the
destination gets measured, not what makes it the destination — but counting an
unbuilt one as met is the mistake criterion 8 already cost a session to.

| Check | State at landing |
| --- | --- |
| A headless test suite for the buffer and the key decoder — no pty, no terminal, no timing dependence | **Met.** `tests/test_editing.py` and `tests/test_keys.py`, 100 cases between them, no pty and no clock. |
| A pty-based test that drives the real application, asserts the frame it draws, sends `SIGINT`, and checks `termios` attributes are restored | **Partly met.** `tests/test_term.py` drives a real pty, sends `SIGINT`/`SIGTERM`/`SIGHUP` and checks `termios` and the cursor. It does **not** assert a frame drawn by the real application — frames are asserted headless via `compose`. Nothing drives the whole editor through a pty. |
| A frame-timing histogram at 80×24 and 200×50, recorded per session | **Not built.** Latency is asserted against a budget in `TestLatency` and was measured at landing (2.03 ms median wall at 80×24, 6.05 ms at 200×50, 9.60 ms worst-case CPU), but no per-session histogram is recorded anywhere, so a slow drift inside budget would be invisible. Q86. |
| A damage-ratio metric: cells emitted divided by cells changed, sitting near 1 | **Met as a test, not as a metric.** `test_the_damage_ratio_stays_near_one` asserts it, and it measured **1.00** over 43 keystrokes at landing. It is not recorded over time. |
