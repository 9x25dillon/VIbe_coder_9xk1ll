# S022 — I never once started a fight the way a player does

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T3 (playability) ·
**Competency band:** `Evaluate` ·
**Data:** [`data/sessions/2026-09-06-S022.json`](../data/sessions/2026-09-06-S022.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A fight can be played from the starter, with nothing but the game | ✅ met |
| 2 | A step that answers wrongly is repairable, not just one that crashes | ✅ met |
| 3 | Each step's stub reaches the player's buffer when they get there | ✅ met |
| 4 | A player has something to follow while testing it | ✅ met |
| 5 | The whole fight verified by typing, not by fixture | ✅ met |

## What happened

The user asked for a tutorial. Writing one requires starting the game the way a
reader would, and doing that took about ninety seconds to prove **the fight was
not playable at all.**

```
$ python3.11 -m vibecoder.cli boss w1-boss-pipeline --live

  Parse the feed  parse_rows()
      3 ▸ lines = ['widget,25.0,2', 'sprocket,3.5,10', 'gasket,12.25,4
    17% of cases pass

  the fight stops here
```

No repair offered. No indication of what was expected. Two commands into the
game I built across three sessions, and it refuses to be played.

### Bug one: only a crash could be repaired

The starter is `return []`. It does not raise — **it answers wrongly**, which
is how most code fails. The repair pane only ever opened from the `event.failed`
branch, which fires on an exception during stepping. A run that completed and
returned the wrong thing fell straight through to "the fight stops here".

The fix restructures `_live_step` into *attempts*. A step can fail two ways and
both are now repairable:

- **It crashes** — the run pauses on the line that raised and a repair resumes
  it in place, which is still strategy A.
- **It finishes wrongly** — there is nothing to resume, so a repair re-runs the
  step from the top.

Both draw on the same pool through one `_offer_repair`, because the pool is
only a resource if every way of using it costs the same.

A percentage on its own also cannot be acted on, so a wrong answer now prints
the `WHAT WENT WRONG` block the ordinary levels already had — given, expected,
you gave — and the pane's header carries `expected …, got …` with the cursor on
the function rather than on a line that never raised.

### Bug two: the buffer never grew

A boss is one shared file and each step brings a new function, but the live
path called `starter_source(0)` once and never again. Clearing step 1 would
have dropped the player into step 2 holding code that never mentions
`above_floor` — asked to write a signature the game had never shown them.

`_with_starter` appends the step's stub when the player reaches it, keeps
everything they wrote, and adds nothing if they already defined it.

### Then I actually played it

End to end through a pty, typing every line of all three functions:

```
--- pane opened for parse_rows
--- pane opened for above_floor
--- pane opened for summarise
    ✔ cleared after 1 repair   -16
  boss ███████████████░░░░░  73   repairs ●●···
  BOSS SURVIVES  on 73 hp; every step cleared, 3 repairs spent
=== exit status: 0
```

### And playing it immediately found a balance problem

Every step's starter answers wrongly. So **every step costs at least one
repair on a first play, and `BOSS DOWN` is unreachable** — the flawless ending
exists and no first-time player can ever see it. Three repairs on
low-accuracy starters leave the boss on 73 of 100, which reads less like "you
won narrowly" and more like the fight barely happened.

W6's own waypoint text is "HP tied to **first-try** step completions", and in
normal play there are no first-try completions at all. That is not a bug in
the code — the model does exactly what it says — it is a question about what a
starter is for, and it is the user's call rather than mine. Recorded as Q79
rather than quietly tuned.

### `docs/PLAYING.md`

A walkthrough, written as a **playtest guide** rather than a tutorial: the
mechanics are tested and the *feel* is not, so its last section lists what is
guesswork (the pool size, the heal ceiling, the pacing) and what would change
it. Linked from `README.md` and `CLAUDE.md`, because a tutorial nobody can find
is a file.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 985 tests in 73.489s — OK

$ VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests
Ran 961 tests in 52.207s — OK

$ python3.11 -m vibecoder.cli verify --seeds 3
45/45 reference runs clean

$ python3.11 -m vibecoder.cli showcase | grep -c $'\033'
0
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| The starter answers wrongly rather than crashing | `test_the_starter_answers_wrongly_rather_than_crashing` | verified |
| A wrong answer says what was expected | `test_a_wrong_answer_says_what_was_expected` | verified |
| A wrong answer offers a repair | `test_a_wrong_answer_offers_a_repair` | verified |
| The step is re-run after such a repair | `test_the_step_is_run_again_after_such_a_repair` | verified |
| The fight can be won from the starter | `test_the_fight_can_be_won_from_the_starter`, exit 0 | verified |
| Running out still ends it on a wrong answer | `test_running_out_still_ends_it_on_a_wrong_answer`, exit 1 | verified |
| The next step's stub is added, with its signature | two tests in `TestTheBufferGrowsWithTheFight` | verified |
| The player's own work is kept exactly | `test_what_the_player_wrote_is_kept_exactly` | verified |
| Solving ahead adds nothing | `test_solving_ahead_adds_nothing` | verified |
| The grown buffer is valid Python and defines every step | two tests | verified |
| Crash-repair still resumes in place | `TestFixingABossMidFight`, unchanged and still green | verified |
| **A whole fight is playable by typing** | pty run: three panes, three typed functions, `BOSS SURVIVES`, exit 0 | verified |
| `BOSS DOWN` is reachable in normal play | it is not — every starter answers wrongly | **falsified**, see Q79 |
| Whether the fight is any *good* | the user has not played it yet | `UNVERIFIED` — the point of this session |

## Misconceptions and corrections

### M38 — I tested the failure I built fixtures for, not the one players get

**Believed:** That the boss fight was playable. S019, S020 and S021 all shipped
against it, and each verified the loop end to end — S020 even drove it through
a real pty and watched `BOSS DOWN`.

**Revealed by:** Running `boss w1-boss-pipeline --live` with no arguments, for
the first time, in order to write a tutorial about it. It stops dead on step
one and offers nothing.

**Corrected to:** Every one of those verifications used `--solution broken.py`
— a file I wrote, whose bug was a `KeyError`. **A crash is the dramatic
failure, not the common one.** The starter, which is what every player without
exception begins with, fails by returning the wrong value, and that path had no
repair, no explanation, and no way forward. The same blind spot hid the second
bug: I never cleared step one from the starter, so I never saw that step two
arrives with no stub.

**Cost:** Three sessions of "verified" that were verified against a fixture. The
code was not wrong — every test I wrote passed, and still passes. The *tests
were of the wrong thing*, which is more expensive than a failing test and much
quieter.

**The generalisable part:** this is **M1's shape a third time**, and I should
have recognised it. M1 was scoring a system with a good solution and never a
bad one. M35 was checking that a step did not crash and never that it answered.
This is verifying a game with a fixture and never with its own front door. The
lesson each time is the same one: *use the thing the way its user will, not the
way your test harness does.*

S020's own journal listed "Anyone but me has played a boss fight — nobody has —
`UNVERIFIED`" and I wrote that line myself. Flagging a risk is not the same as
retiring it, and an `UNVERIFIED` I keep re-copying forward is a decision to
keep not looking.

## Friction

- Driving the repair pane from a pty needed bracketed paste
  (`ESC[200~ … ESC[201~`) rather than typed characters, because the buffer
  auto-indents and re-indenting pasted Python fights it. That is correct
  behaviour for a person typing and correct behaviour for a paste; it only
  looks like friction from a test harness.
- `ctrl-k` held down is the only way to clear a function before rewriting it.
  It works and the tutorial documents it, but "hold a key thirty times" is not
  a design. Q78.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D149 | A step that answers wrongly offers a repair and re-runs from the top | Only crashes are repairable; resume a finished run somehow | The common failure has to be the repairable one, and there is nothing to resume once the run has completed. Both paths spend from the same pool through one function | no — it is what makes the game playable |
| D150 | Each step's stub is appended to the player's buffer when they reach it | Hand out the whole skeleton up front; make them write signatures | A boss is one growing file. The whole skeleton would give away the shape of steps they have not reached; no stub asks them to guess a signature | yes |
| D151 | A wrong answer opens the pane on the function, with `expected … got …` | Open at line 1; show only a percentage | There is no offending line, and a percentage cannot be acted on. The ordinary levels already show expected-versus-got, so this is consistency rather than a new disclosure | yes |
| D152 | A scripted `--fix` is spent per attempt; a typed repair is not | Let `--fix` retry forever | A file cannot change its mind, so re-reading it loops. A person can, and is sitting right there | yes |
| D153 | `docs/PLAYING.md` is written as a playtest guide, not a tutorial | A pure how-to; no doc at all | The mechanics are tested and the feel is not. A tutorial that hides which numbers are guesses invites the reader to treat all of them as settled | yes |

## Handoff

- **State:** The boss fight is playable from the starter with nothing but the
  game — verified by playing the whole thing through a pty, typing every line.
  Two blocking bugs fixed: a wrong answer was unrepairable, and the buffer
  never grew. [`docs/PLAYING.md`](../docs/PLAYING.md) walks a player through
  it. 985 tests green unpinned, 961 pinned, `verify` clean on 45 reference
  runs.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action: the user plays it.** Nothing here is worth building on until
  someone who is not me has had a fight. Q79 is the first thing they will
  hit and it needs their answer, not a patch.
- **Then T3 W7**, boss scoring at 40/30/30 — still the only waypoint between
  T3 and its exit criteria.
- **Blockers:** none. T2 W4 remains blocked on a registered OAuth application.
- **Context required:** M38 before writing another "verified" against a
  fixture. D149 before touching `_attempt` — the two failure paths are not
  symmetrical and only one of them can resume. Q79 before tuning any number in
  `fight.py`.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q68 | Two events land on one line when it raises. Should the display merge them? | T3 | open |
| Q69 | `Timeline` holds `Step` objects for a live run and dicts for a recorded one | T3 | open |
| Q70 | An edit past step 400 fast-forwards against a truncated original | T3 | open |
| Q71 | Divergence rate over real play is measurable and uncollected | T3 | open |
| Q73 | The pane shows locals but not the expected value — except now it does, for a wrong answer (D151). Should the crash path show it too, or is that handing over the answer? | T3 | open, and narrowed |
| Q75 | Which of the remaining non-negotiables can be given a test? | T6 | open |
| Q76 | The heal curve and pool size were chosen by argument, not playtest | T3 | open |
| Q77 | W8 is a waypoint no exit criterion points at. Does T3 land without it? | T3 | open |
| Q78 | Clearing a function before rewriting it means holding `ctrl-k`. Should the pane have a "replace this function" affordance, or is a real editor's worth of editing out of scope for a fight? | T3 | open |
| Q79 | **Every starter answers wrongly, so every step costs a repair and `BOSS DOWN` is unreachable on a first play.** W6's waypoint text ties HP to *first-try* completions and normal play has none. Is a starter meant to be a failing stub here, or should a boss step start from something that runs? | T3 | open — the user's call |
