# S023 — A starter you can watch

**Date:** 2026-09-06 · **Duration:** — · **Trajectory:** T3 (Q79) ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-06-S023.json`](../data/sessions/2026-09-06-S023.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | Every boss starter runs real work instead of returning immediately | ✅ met |
| 2 | Each starter's bug is visible in the trace, not just in the verdict | ✅ met |
| 3 | A starter is wrong without being hopeless, so the heal is proportionate | ✅ met |
| 4 | "A starter must run" is a contract, not this boss's good luck | ✅ met |
| 5 | The walkthrough describes the game that now exists | ✅ met |

## What was built

Q79 was the user's to answer and they answered it: **the starter should run,
not fail.**

### Three starters that do something

The old ones were `return []`, `return []`, and `return {"count": 0,
"revenue": 0.0}`. Legal under every rule in the contract, and useless in a
fight whose entire pitch is *watch your code execute*: the boss engine drew a
single line of trace and stopped.

Each starter now does the work and gets one thing wrong, chosen so the bug is
**visible while it runs**:

| Step | The bug | Accuracy | What the trace shows |
| --- | --- | --- | --- |
| `parse_rows` | `return rows` sits *inside* the loop | 50% | It builds one dict and leaves — `rows` holds exactly one row when it stops |
| `above_floor` | `>` where the brief says the floor qualifies | 83% | The comprehension iterating, and one boundary case missing from the result |
| `summarise` | Revenue sums prices and ignores quantity | 33% | It descends into both functions the player wrote, and `count` is already right |

```
  Parse the feed  parse_rows()
      3 ▸ lines = ['widget,25.0,2', 'sprocket,3.5,10', 'gasket,12.25,4
      4 ▸ rows = []
      5 ▸ line = 'widget,25.0,2'
      6 ▸ quantity = '2'
     11 ▸ rows = [{'name': 'widget', 'price': 25.0, 'quantity': 2}]
    50% of cases pass
```

You find that bug by *watching*, which is the first time this project's most
distinctive feature has had anything to be distinctive about.

### Partial credit is what makes the heal curve work

A starter that passes nothing hands the boss the maximum heal on every step,
and the curve built in W6 never gets to do its job. These pass 50%, 83% and
33%, so the repairs cost 5, **2** and 7. Step two is the one to look at: code
that is nearly right is nearly free to fix, which is precisely the property
D142 was chosen for and the first time it has been observable.

A full play-through of the three starters now leaves the boss on **65** rather
than 73.

### The contract, so this cannot quietly come back

Three new tests in `tests/test_bosses.py`, because "the starter should run" is
exactly the kind of rule that rots when it lives only in prose — which is
Q75's whole complaint and M36's cost:

- **`test_no_starter_crashes`** — a starter that raises puts a stack trace
  where the feature should be.
- **`test_a_starter_does_enough_work_to_watch`** — more than three traced
  lines. Deliberately a floor on "something happens", not a target.
- **`test_a_starter_is_wrong_without_being_hopeless`** — it fails, and it does
  not fail everything.

This is the half of the contract a plain level does not need. A level's starter
is read; a boss's starter is *watched*.

## Evidence

```
$ python3.11 -m unittest discover -s tests
Ran 988 tests in 76.736s — OK

$ VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests
Ran 964 tests in 53.865s — OK

$ python3.11 -m vibecoder.cli verify --seeds 3
45/45 reference runs clean
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| No starter crashes | `test_no_starter_crashes`, every step of every boss | verified |
| Every starter produces more than three traced lines | `test_a_starter_does_enough_work_to_watch` | verified |
| Every starter fails without failing everything | `test_a_starter_is_wrong_without_being_hopeless` | verified |
| No starter passes its own step | `test_no_starter_already_passes_its_own_step`, unchanged | verified |
| The accuracies are 50%, 83%, 33% | measured directly against each step's own tests | verified |
| The repairs therefore cost 5, 2 and 7 | `heal = 100 × 0.10 × (1 − accuracy)`, checked against the run | verified |
| A whole fight is still playable by typing | pty run: three panes, three typed functions, exit 0 | verified |
| The fight now ends on 65 rather than 73 | same pty play-through, before and after | verified |
| The references still pass every variant | `verify --seeds 3`, 45/45 | verified |
| `BOSS DOWN` is reachable from the starters | it is not, and cannot be while starters must fail. See Q80 | **falsified** |
| Whether the new starters are *better to play* | the user has still not played it | `UNVERIFIED` |

## Misconceptions and corrections

### M39 — I pinned a starter's text as if it were the contract

**Believed:** That
`test_the_starter_answers_wrongly_rather_than_crashing`, which I wrote one
session ago, documented a premise. It asserted `self.assertIn("return []",
starter)`.

**Revealed by:** It failed the moment the starter changed — which was the very
next session, and for a reason the user asked for.

**Corrected to:** The premise that test exists to protect is that the starter
**runs and is wrong**, because that is what makes it exercise the
wrong-answer repair path rather than the crash path. It now asserts exactly
that, via `_check`, and is immune to the next redesign of the level's text.

**Cost:** Two minutes. Recorded because the failure mode is quiet in the other
direction: a test pinned to an implementation detail passes happily while the
thing it was meant to protect rots, and only complains when something
unrelated changes. This one at least failed loudly and immediately.

**Worth noting alongside it:** M37 was about asserting counts I had not
measured, and this session I designed three starter bugs and then *measured*
the accuracy each produced before writing a single number into a document.
The 50/83/33 in the table above are observations, not intentions.

## Friction

- Designing a bug that fails *partially* is harder than designing one that
  fails. Two candidates for `summarise` were discarded first: forgetting the
  `round` passed almost everything (float error decides, which makes the
  starter's difficulty depend on the seed), and dropping the filter failed
  everything. Ignoring quantity fails four of six cases for a reason a player
  can name.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D154 | A boss starter runs real work and gets one thing wrong | Keep the stubs; ship a correct starter | The fight's whole pitch is watching code execute, and a stub gives one line of trace. A correct starter would break the contract that a starter must not pass | yes — it is level content |
| D155 | Each bug is chosen to be visible *in the trace* | Any wrong answer would satisfy the tests | A bug you can only see in the verdict is a bug the debugger did not help you find, which wastes the feature the fight exists to show off | yes |
| D156 | Starters give partial credit | Any failing starter | The heal scales with `1 − accuracy`. A starter that passes nothing hands over the maximum every time and W6's curve never does its job | yes |
| D157 | "Runs", "watchable" and "not hopeless" are enforced tests, not prose | A note in `LEVEL_AUTHORING.md` | M36's cost was an invariant nothing tested drifting for two trajectories. Q75 asks which rules can be given a test; these three can, so they were | no |

## Handoff

- **State:** Q79's first half is answered and shipped. All three starters run,
  each fails visibly in the trace, and they pass 50%, 83% and 33% so the
  repairs cost 5, 2 and 7. Three new contract tests keep it that way. A full
  play-through lands the boss on 65. 988 tests green unpinned, 964 pinned,
  `verify` clean on 45 reference runs.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action: the user plays it.** Twice now the useful findings have come
  from running the game rather than the suite, and the suite has never been
  the thing that was wrong.
- **Q80 is the open half of Q79** and needs deciding before W7, because
  scoring a fight whose best outcome is unreachable would bake the problem in.
- **Then T3 W7**, boss scoring at 40/30/30 — still the only waypoint between
  T3 and its exit criteria.
- **Blockers:** none. T2 W4 remains blocked on a registered OAuth application.
- **Context required:** D156 before authoring another boss starter — partial
  credit is load-bearing for the heal curve, not a nicety. M39 before writing
  a test that quotes level content.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q68 | Two events land on one line when it raises. Should the display merge them? | T3 | open |
| Q69 | `Timeline` holds `Step` objects for a live run and dicts for a recorded one | T3 | open |
| Q70 | An edit past step 400 fast-forwards against a truncated original | T3 | open |
| Q71 | Divergence rate over real play is measurable and uncollected | T3 | open |
| Q73 | Should the crash path show the expected value, as the wrong-answer path now does? | T3 | open |
| Q75 | Which of the remaining non-negotiables can be given a test? | T6 | open, and three fewer |
| Q76 | The heal curve and pool size were chosen by argument, not playtest | T3 | open |
| Q77 | W8 is a waypoint no exit criterion points at. Does T3 land without it? | T3 | open |
| Q78 | Should the pane have a "replace this function" affordance? | T3 | open |
| Q79 | Should a boss step start from something that runs? | T3 | **answered** — yes. Starters do real work and fail visibly (D154, D155) |
| Q80 | **`BOSS DOWN` is still unreachable from the starters**, because the contract says a starter must fail its own tests and every failure costs a repair. So the flawless ending exists and normal play cannot reach it. Does the boss contract differ from the level contract here, does the first repair become free, or is `BOSS DOWN` simply not for a first attempt? | T3 | open — the user's call |
