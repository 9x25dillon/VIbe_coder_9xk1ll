# T7 — Interactive play: editor, motion, visualiser

**Design phase:** cross-cutting · **Status:** `IN FLIGHT` · **Target:** — ·
**Depends on:** T6 (`LANDED`)

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

- A headless test suite for the buffer and the key decoder — no pty, no
  terminal, no timing dependence.
- A pty-based test that drives the real application, asserts the frame it
  draws, sends `SIGINT`, and checks `termios` attributes are restored.
- A frame-timing histogram at 80×24 and 200×50, recorded per session so a
  regression in redraw cost is visible rather than felt.
- A damage-ratio metric: cells emitted divided by cells changed. It should sit
  near 1; a drift upward means the diff is giving up.
