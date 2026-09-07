# S020 — A fix nobody can type is not playable

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T3 (Q67) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-06-S020.json`](../data/sessions/2026-09-06-S020.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A player types the fix into the paused fight and it completes | ✅ met |
| 2 | The pane opens on the line that raised, and keeps it findable | ✅ met |
| 3 | A fix that will not compile costs no part of the fight | ✅ met |
| 4 | The bindings are the editor's, not a second set to learn | ✅ met |
| 5 | The pane is testable without a pty, a child, or a terminal | ✅ met |

## What was built

### `repair.py` — the pane, and what it deliberately is not

Q67 asked where the edit belongs: in `boss --live` as a keystroke, in the T7
editor, or somewhere else. The answer is the first, and the interesting half of
it is why not the second.

**`editor.Editor` is bound to a `Level`.** It runs that level's tests, scores
the attempt against `LEVEL_WEIGHTS`, and banks the result to the session. A
boss step is none of those things — it is one function in a shared module,
graded per step, mid-fight. Threading a boss step through a `Level`-shaped API
would have been dressing a mismatch up as reuse, and every later change to
either would have paid for it.

What *is* worth reusing sits a layer down, and is reused whole:
[`Buffer`](../vibecoder/editing.py) for the text and its undo history,
`KeyDecoder` for the input, and the same
[`KEYMAP`](../vibecoder/keymap.py). So Ctrl-R runs a level in one application
and resumes a fight in the other, Ctrl-Z is undo in both, and there is no
second set of bindings to learn. Only the help *labels* differ, which is why
`describe_keys` now takes them as an argument rather than closing over one
tuple.

```
─ FIX Drop the cheap stock above_floor() ─────────────────────────────────────
 ✘ line 16: KeyError: 'prise'
   floor = 10.0
──────────────────────────────────────────────────────────────────────────────
   14 def above_floor(rows, floor):
   15     (docstring)
 ✘ 16     return [row for row in rows if row["prise"] >= floor]
   17
──────────────────────────────────────────────────────────────────────────────
 ctrl-r resume   ctrl-z undo   ctrl-k kill line   ctrl-x give up
```

### Three details that are the feature

**It opens on the line that raised, past the indent.** A real submission is
longer than a short terminal — the pipeline boss is 24 lines and the failure is
on line 16 — so opening at the top and making the player hunt for the line they
just watched fail is the feature not working. The line stays marked in the
gutter however far they scroll away from it, because findable only by memory is
not findable.

**The locals at the failure are drawn in the pane.** The alternate screen has
just hidden the scrollback the player was reading, so a fix argued from
remembered values is a guess.

**The edit is compiled before the fight resumes.** Without it a fix with a
typo restarts the child only to have it die on import, spending a step of the
fight on something the pane can point at while the cursor is still next to it.
The guard is about *compiling*, never about being right — deciding a fix is
wrong is the fight's job, and doing it in a text editor would be scoring the
player from the wrong place.

### The whole submission is editable, not just the failing line

T3's pitch says "fix the line", and a single-line editor would have been
smaller. It would also have decided for the player that every bug is on the
line that raised, which is not true: a `KeyError` on line 16 is often a
misspelling introduced on line 8. Editing an earlier line is exactly the case
W5's divergence detector exists to report, so the honest thing is to allow it
and say what happened.

### The child waits, and that is free

The player can think for as long as they like. The child's budget counts
executing time and never time blocked on the parent — the property S017 built
for pausing — so a fight cannot time out for being thought about. Opening an
editor at the pause point is only safe because of a decision made three
sessions ago for a different reason.

`--fix <path>` stays, as the scriptable path: the same loop driven by a file
instead of a person, and the one the test suite can drive, since
`repair.available()` is false without a real terminal on both streams.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 924 tests in 77.270s — OK      (37 repair tests in 0.020s)

$ VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests
Ran 900 tests in 52.574s — OK

$ python3.11 -m vibecoder.cli verify --seeds 3
45/45 reference runs clean
```

The end-to-end proof is not a unit test. `boss --live` was driven through a
real pty with the broken pipeline solution, the fix typed as keystrokes
(`ctrl-k`, then the corrected line, then `ctrl-r`), and the fight watched to
completion:

```
$ python3.11 scratch/drive.py
--- reached the FIX pane: True
     16 ✘ KeyError: 'prise'
─ FIX Drop the cheap stock above_floor() ─ ...
=== after resuming ===
     16 ▸ row = {'name': 'widget', 'price': 25.0, 'quantity': 2}
     ...
  BOSS DOWN
=== exit status: 0
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| A player can type a fix and finish the fight | pty run above: keystrokes in, `BOSS DOWN`, exit 0 | verified |
| The cursor opens on the failing line, past the indent | `test_the_cursor_is_on_the_failing_line`, `test_the_cursor_skips_the_indent` | verified |
| A failing line beyond the buffer is clamped | `test_a_failing_line_past_the_end_is_clamped`, line 99 → row 2 | verified |
| The failing line is visible on a minimum-size terminal | `test_it_opens_with_the_failing_line_in_view`, line 61 of 61 | verified |
| The mark survives scrolling away from it | `test_the_mark_survives_scrolling_away_from_it` | verified |
| The locals at the failure are on screen | `test_the_locals_at_the_failure_are_shown` | verified |
| A fix that will not compile does not resume | `test_broken_syntax_does_not_resume` | verified |
| It says what is wrong, in the frame | `test_the_complaint_reaches_the_frame` | verified |
| A fixed fix then resumes | `test_a_fixed_fix_then_resumes` | verified |
| Valid-but-wrong Python is allowed through | `test_valid_python_that_is_still_wrong_is_allowed_through` | verified |
| Giving up is not resuming | `test_giving_up_is_not_resuming`, edited then ctrl-x | verified |
| A fix may add lines, not only retype one | `test_a_new_line_can_be_added` | verified |
| Both applications resolve one binding table | `test_the_bindings_come_from_the_one_table` | verified |
| Frames are identical text at every colour depth | `test_the_frame_is_the_same_text_at_every_depth` | verified |
| A tiny terminal says so rather than drawing rubbish | `test_a_tiny_terminal_says_so_rather_than_drawing_rubbish` | verified |
| The pane is testable with no pty | 37 tests in 0.020s | verified |
| Anyone but me has played a boss fight | nobody has | `UNVERIFIED` |
| Divergence rate over real play | still uncollected; Q71 | `UNVERIFIED` |

### Against T3's exit criteria

- **1–4** — verified in S017, S018 and S019.
- **6 — a boss fight fully playable from the CLI:** **still not claimed.**
  Q67 was one blocker and it is gone. But S018 read criterion 6 as also
  requiring the fight to be *scored* rather than merely watched, and that is
  W6 and W7. Two readings of one criterion is itself the finding: "fully
  playable" was written before anyone had to decide whether playable means
  scored, and it is not being decided now in the direction that makes the
  trajectory look closer to done (N7).

## Misconceptions and corrections

### M36 — `ui.py` is the only module that emits an escape sequence

**Believed:** [`docs/UI.md`](../docs/UI.md) states it in its second sentence,
and [`CLAUDE.md`](../CLAUDE.md) §6 repeats it as an architecture rule: "Never
write `\033` anywhere else — draw through the renderer." I took it as a live
invariant and started designing the repair pane to route its colour through
`ui.py`, which for a cell-diffed grid means not using the grid.

**Revealed by:** `grep -rn '\\033' vibecoder/*.py` before writing a line of it:

```
11 vibecoder/ui.py
 7 vibecoder/term.py
 5 vibecoder/replay.py
 3 vibecoder/screen.py
 2 vibecoder/editor.py
```

**Corrected to:** The rule was true when written and stopped being true the
moment T7 shipped a full-screen stack — a grid painted by cell damage cannot
be routed through a line renderer, and `replay.py` had already broken it
before that. The half that *is* true and *is* enforced is the one about
`cli.py`, which contains none and is checked by
`showcase | grep -c $'\033'` printing 0. `docs/UI.md` now documents the
exception explicitly, names the modules in it, and says what they pay in
return: pure composition, frames asserted as plain text, no escapes at
`Depth.NONE`.

**Cost:** ~10 minutes, and it would have been far more expensive in the other
direction. Had I not grepped, I would either have contorted the pane to avoid
the grid — reimplementing screen diffing badly — or quietly added a fifth
escape-emitting module and left a documented invariant one module further from
true.

**The generalisable part:** an invariant nothing tests is a comment. Three of
this project's non-negotiables have tests that enforce them (N9 has
`test_provenance`, N8 has CI, the record system has `test_records`). This one
did not, and it drifted for two trajectories without anyone noticing —
including me, reading it at the start of this session.

## Friction

- A heredoc containing a Python docstring inside a Markdown code fence
  terminated the heredoc early. Spliced the doc section from a file instead.
  Under a minute, but worth noting as the reason doc edits here go through
  files rather than inline strings.
- The first pty run *looked* like the pane had opened at line 1 rather than
  line 16. It had not: I was printing the last 900 characters of a raw
  terminal byte stream, and the pane's own frame ran past that window.
  Checked before changing anything, which is the only reason no time was spent
  fixing a bug that did not exist. A test now covers the real property
  (`test_it_opens_with_the_failing_line_in_view`) so the question does not
  have to be re-asked from a byte dump.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D133 | The repair pane is its own application, not `editor.Editor` | Open the T7 editor on the boss source; extend `Editor` to accept a boss step | `Editor` runs a level's tests, scores against `LEVEL_WEIGHTS` and banks to the session. A boss step is none of those, and threading one through a `Level`-shaped API is a mismatch dressed as reuse | yes |
| D134 | It reuses `Buffer`, `KeyDecoder` and the same `KEYMAP`; only the help labels differ | A minimal bespoke line editor with its own keys | A player who has used the editor should not learn a second set of bindings for the same actions. `describe_keys` takes the labels because only the labels should differ | yes |
| D135 | The whole submission is editable, not only the failing line | A one-line editor, matching T3's "fix the line" wording | A `KeyError` on line 16 is often a misspelling on line 8. Restricting the edit decides for the player that every bug is where it surfaced. Editing earlier is what W5 exists to report | yes |
| D136 | The edit is compiled before the fight resumes | Let the child fail on import and report it as the step failing | A typo would otherwise cost a step of the fight to discover, when the pane can point at it with the cursor still next to it. Compiling only — being *wrong* is the fight's job | yes |
| D137 | Giving up returns `None`, not the edited text | Resume with whatever is in the buffer | A player who edits and then quits has not asked for their edit to be run. Resuming a fight they were trying to leave is the wrong guess | yes |
| D138 | `--fix <path>` stays as the scriptable path | Remove it now that a person can type | It is the same loop driven by a file, and it is the only one the test suite can drive: `repair.available()` is false without a real terminal on both streams | yes |
| D139 | `binding()` moves into `keymap.py`, shared by both applications | Duplicate the three lines in the pane | Two applications sharing a table must resolve its keys identically, or the table is a lie | yes |
| D140 | `docs/UI.md` documents the full-screen exception rather than the rule being restored | Route the pane's colour through `ui.py`; delete the rule | The rule's `cli.py` half is true, valuable and tested. The full-screen half has been false since T7 and cannot be made true without reimplementing screen diffing through a line renderer. See M36 | no |

## Handoff

- **State:** Q67 is answered. `repair.py` is a pane a player types the fix
  into, reusing the T7 editor's buffer, decoder and keymap but not the editor.
  A fight now runs end to end from the CLI with no file paths: watch, fail,
  type, resume, win — verified through a real pty. 924 tests green unpinned,
  900 pinned, `verify` clean on 45 reference runs.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action: T3 W6, the boss HP model tied to first-try step
  completions.** Read Q74 before starting — it is a design conflict this
  session created and did not resolve.
- **Blockers:** none for T3. T2 W4 remains blocked on a registered OAuth
  application, with T2 otherwise one waypoint from landing.
- **Context required:** M36 before trusting any invariant in `CLAUDE.md` §6 or
  `docs/UI.md` that has no test behind it. D133 before adding boss features to
  `editor.py`. D136 before moving correctness checking into the pane.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q67 | Where does the typed edit belong? | T3 | **answered** — in the fight, in `repair.py`, reusing the editor's buffer/decoder/keymap but not the editor (D133, D134) |
| Q68 | Two events land on one line when it raises. Should the display merge them? | T3 | open |
| Q69 | `Timeline` holds `Step` objects for a live run and dicts for a recorded one; `compare` handles both by inspection | T3 | open |
| Q70 | The recording cap is 400 steps, so an edit past step 400 fast-forwards against a truncated original | T3 | open |
| Q71 | T3's instrument check — divergence rate over real play — is measurable and uncollected | T3 | open |
| Q72 | A stepped run executes `tests[0]` only, so a live boss step is cleared on one case | T3 | open |
| Q73 | The pane shows the locals at the failure but not what the step was *expected* to return. Would showing the expected value help the fix, or hand over the answer? | T3 | open |
| Q74 | **The pane allows unlimited repair attempts; `--fix` allows one.** W6 ties boss HP to *first-try* step completions, so "how many attempts did that take" is about to become a scored quantity, and the interactive path currently does not count them. Does a repair spend something? | T3 | open |
| Q75 | The rule that drifted in M36 is T6's, and it drifted because nothing tested it. Three of this project's invariants have tests and the rest are prose. Which of the remaining non-negotiables can be given one? Filed under T6 because that is the rule that broke, not because the question stops there | T6 | open |
