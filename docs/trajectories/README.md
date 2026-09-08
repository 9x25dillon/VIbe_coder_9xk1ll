# Trajectories

A **trajectory** is this project's unit of forward planning. It replaces the
word "roadmap", which implies fixed ground and a route someone else surveyed.
A trajectory is a heading with waypoints: the destination is committed, the
path between waypoints is expected to bend as we learn.

Each trajectory document has the same five sections.

| Section | What it answers |
| --- | --- |
| **Heading** | Where this is going, in one paragraph, and why it is worth going there |
| **Waypoints** | Ordered, individually shippable milestones (`W1`, `W2`, …) |
| **Exit criteria** | The observable facts that make the trajectory *done* — not opinions |
| **Known hazards** | What we already believe will go wrong |
| **Instrument checks** | How we will measure that the destination was actually reached |

## Status vocabulary

| Status | Meaning |
| --- | --- |
| `LANDED` | Exit criteria met and verified. The trajectory is closed. |
| `IN FLIGHT` | Actively being worked. Exactly one trajectory should hold this. |
| `CLEARED` | Fully specified, dependencies met, ready to start. |
| `PLOTTED` | Sketched. Waypoints may still move. |
| `HOLDING` | Blocked on an external dependency, named in the document. |

## Current flight board

| ID | Trajectory | Design phase | Status | Target |
| --- | --- | --- | --- | --- |
| [T1](T1-core-loop.md) | Core loop: levels, sandbox, three-axis scoring | Phase 0 | `LANDED` | 2026-08-08 |
| [T2](T2-sandbox.md) | Trusted execution & codebase ingestion | Phase 1 | `IN FLIGHT` | 2026-08-30 |
| [T3](T3-boss-engine.md) | Boss engine: interactive slow-motion debugger | Phase 2 | `LANDED` | 2026-09-20 |
| [T4](T4-adaptive.md) | Adaptive difficulty | Phase 3 | `IN FLIGHT` | 2026-10-04 |
| [T5](T5-community.md) | Daily challenges, leaderboards, level editor | Phase 4 | `PLOTTED` | 2026-10-18 |
| [T6](T6-presentation.md) | Presentation layer: capability-aware terminal rendering | cross-cutting | `LANDED` | 2026-08-08 |
| [T7](T7-interactive.md) | Interactive full-screen play: editor, motion, visualiser | cross-cutting | `LANDED` | — |

T6 is cross-cutting rather than tied to a design phase: it presents whatever the
other trajectories build, and it landed early because T1's output was already
leaking escape codes into pipes. T7 extends it from *drawing* to *interacting*
and is likewise cross-cutting; it was opened out of sequence at the user's
request while T2 is still in flight, which is a schedule fact recorded in
[S003](../../journal/2026-09-03-S003-sandbox-seam.md) rather than absorbed
silently.

**T2 waypoint state:** W1 `LANDED` ([S003](../../journal/2026-09-03-S003-sandbox-seam.md)),
W2 `LANDED` ([S005](../../journal/2026-09-03-S005-hardening.md)),
W3 `LANDED` ([S006](../../journal/2026-09-03-S006-provenance.md)),
W5 `LANDED` ([S012](../../journal/2026-09-06-S012-archive-ingestion.md)),
W6 `LANDED` ([S014](../../journal/2026-09-06-S014-ingestion-budgets.md)),
W7 `LANDED` ([S015](../../journal/2026-09-06-S015-vector-versioning.md)).
**W4 is the only waypoint left, and it is externally blocked** on a registered
OAuth application and the client-versus-server profiling decision, which is why
W5, W6 and W7 were taken out of order. Exit criteria 1, 2, 3, 4, 6 and 7 are verified.
Criterion 6 is met by *finishing*: a 5,000-file repository profiles in 11.7 s
against a 60 s budget, and the same tree under a small budget degrades to a
flagged partial profile rather than hanging. Criterion 5 — no source retained
after a run — is verified *for the archive path*, where it holds by
construction because nothing is written to disk at all; it stays open until
W4's clone path exists to be checked. The trajectory's 2026-08-30 target has
passed; it is late, not re-dated.

T2 is **one waypoint from landing** and must not be marked `LANDED` on six of
seven. Criterion 5 is the other half of that: it is verified for the archive
path, where it holds by construction, and cannot be finished until W4's clone
path exists to be inspected.

⚠ The hard gate in [T5](T5-community.md) — "W6 may not ship unless T2 W1–W3
are landed" — is now *satisfiable*, and is not sufficient. A level is an
importable module and its `make_tests` runs in the parent, so neither is
covered by the provenance flag W3 added. See M12 in
[S006](../../journal/2026-09-03-S006-provenance.md).

**T7 waypoint state:** W1–W8 `LANDED`
([S004](../../journal/2026-09-03-S004-interactive.md),
[S007](../../journal/2026-09-03-S007-streaming.md),
[S008](../../journal/2026-09-03-S008-latency.md)). W8 shipped partial and was
completed afterwards: the harness now replies in newline-delimited events, so
Accuracy assembles as tests report instead of animating a finished result.
**T7 is `LANDED` as of 2026-09-08**
([S026](../../journal/2026-09-08-S026-landing-t7.md)).

Landing it was not the bookkeeping the board had been calling it for five
sessions. Checking the nine criteria one at a time found **two without
evidence**, and criterion 8 was not merely untested but false: the typing
visualiser animated identically whether or not `animate` was set, so a
terminal that had asked for no motion got twenty frames a second of a
draining bar. It now degrades to a reading taken at the last keystroke, and an
idle editor emits zero bytes. Criterion 1 named `SIGINT` and nothing tested
it; it also says "with the cursor visible", and only the normal exit path had
ever checked that. Both are now covered on every path. The lesson is M43's,
one trajectory later and from the other direction: **a trajectory recorded as
complete is a claim, and the claim is worth checking before it is closed.**

Exit criterion 3 is measured on two clocks as of
[S008](../../journal/2026-09-03-S008-latency.md): a wall-clock median for what
a player feels, and a CPU-time worst case of 12.7 ms at 4000 lines for what the
code costs. The percentile S007 adopted was hiding a real defect rather than
noise — keystroke latency was proportional to the process's total live object
count — which is Q27's answer and M15's subject.

**Outside every waypoint:** the machine view — a submitted function drawn as
apparatus with its own recorded run moving through it — shipped in
[S013](../../journal/2026-09-06-S013-machine-view.md) at the user's request
while T2 W6 was being started. It belongs to no waypoint on any trajectory.
T3's own heading draws the line it falls on: "replaying a recording is a
visualisation", and T3's waypoints are all the live engine. It is filed under
T6 because presentation is the closest honest home, not a comfortable one —
T6 is `LANDED`, so either it reopens or this and what follows it deserve a
trajectory of their own. That is Q51 and it is the user's call, recorded here
rather than absorbed.

**T3 waypoint state:** W1 `LANDED`
([S016](../../journal/2026-09-06-S016-boss-format.md)),
W2 `LANDED` ([S017](../../journal/2026-09-06-S017-live-stepping.md)),
W3 `LANDED` ([S018](../../journal/2026-09-06-S018-step-back.md)),
W4 and W5 `LANDED` ([S019](../../journal/2026-09-06-S019-edit-and-resume.md)),
W6 `LANDED` ([S021](../../journal/2026-09-06-S021-boss-hp.md)),
W7 `LANDED` ([S024](../../journal/2026-09-08-S024-scoring-the-fight.md)).
W8 `LANDED` ([S025](../../journal/2026-09-08-S025-the-ledger.md)).
**Every waypoint has shipped and every exit criterion has evidence, so T3 is
`LANDED` as of 2026-09-08**, twelve days inside its target.
**Exit criteria 1 through 5 were verified before this session.**
[S022](../../journal/2026-09-06-S022-actually-playable.md) then played the
fight from the starter for the first time and found it unplayable — a wrong
answer offered no repair, and the buffer never grew to hold the next step.
Both fixed; the fight has now been completed by typing. It also surfaced Q79,
which the user answered — *the starter should run, not fail* — and
[S023](../../journal/2026-09-06-S023-starters-that-run.md) shipped it: all
three starters now do real work and fail *visibly in the trace*, with partial
credit (50%, 83%, 33%) so a repair's heal is proportionate. Three new contract
tests keep it so. **Q80 was the open half, and the user resolved it in
[S024](../../journal/2026-09-08-S024-scoring-the-fight.md):** `BOSS DOWN` is
unreachable from the starters — a starter must fail its own tests and every
failure costs a repair — and that is now the design rather than a defect. The
floor was *measured* at exactly 65, which also showed the heal is not what
puts zero out of reach (14 HP of the missing 35; the compounding damage
halving costs the other 51). So the ending is a mastery one, reached by
returning with a solution that passes every step first time, and a first run
is graded by the scorecard instead. A boss runs
step by step with a visible current line and live locals; a deliberate error
pauses *on* the offending line; editing that line and resuming completes the
fight with the edit in the submitted source; a replay that stops matching is
reported rather than presented as continuous; and the per-step damages sum to
exactly the starting HP, so nothing but clearing every step reaches zero.
Criterion 6 was read as needing the fight *scored* on the three axes, which is
W7, and W7 has now landed: a fight is graded at 40/30/30 on the same card a
level uses, with Speed corrected for the engine's own slow motion and hit
points deliberately kept out of the score. **All six criteria therefore have
evidence.** Q77 asked whether T3 could land on those six with W8 still
outstanding, since no criterion points at W8. The user's answer was no — the
waypoint list is the real contract and the criteria list has a gap, which is a
finding about the criteria rather than a licence to edit them (N7). So W8 was
built, and [S025](../../journal/2026-09-08-S025-the-ledger.md) shipped
`w2-boss-ledger`: a three-link chain where `totals_by_customer` calls
`index_prices` and `top_spenders` calls `totals_by_customer`, which is a
stronger reading of "linked steps" than W1's boss, where only the last step
called anything. **T3 is now `LANDED`.**

Building it found the gap the criteria could not: **bosses appeared in no
listing at all**, so the only way to reach one was to already know its id.
Criterion 6 says a boss fight is "fully playable from the CLI", and it had been
read as satisfied for two sessions while the fight was unreachable by anyone
who had not read the source. `vibecoder levels` and `levels --map` now name
both bosses and print the command. That is the third time in T3 that running
the thing found what the suite could not.

W4 was the one waypoint in the project whose difficulty the trajectory itself
called genuinely uncertain, and the hazard list said to ship W1–W3 as a
playable "watch it run" boss first so a slip would degrade the feature rather
than delete it. That is what happened, and W4 then came in cheaply: the memo
strategy A needs turned out to be the test payload, which the parent already
holds. **W5 landed with it rather than after it**, because strategy A is only
honest if divergence is detected — the safety net is not optional equipment.

The instrument check T3 asks for — *divergence rate on edit-and-resume,
measured over real play sessions; if it exceeds ~5%, strategy C is justified* —
is now measurable and unmeasured. Nobody has played a fight and been diverged
on.

**Q67 is answered** ([S020](../../journal/2026-09-06-S020-typing-the-fix.md)):
the edit is typed into the paused fight, in a repair pane that reuses the T7
editor's buffer, decoder and keymap rather than the editor itself. Criterion 6
loses that blocker but is still **not** claimed, because S018 read it as also
requiring the fight to be *scored* rather than merely watched, and that is W6
and W7. Two readings of one criterion is itself worth noticing: "fully
playable" was written before anyone had to decide whether playable means
scored. T3
was started at the user's request with T2 one waypoint from landing and
externally blocked, which is the honest reason it went first rather than a
claim that T2 finished.

**Two** trajectories hold `IN FLIGHT`. It was three on the morning of
2026-09-08, then one by that evening — T3 landed and T7 followed — and then
two again when **T4 started the same day**. The other is **T2**, late and
blocked on W4's registered OAuth application rather than being worked.

Recorded rather than absorbed, per the rule: a second trajectory starting
means the first slipped, and T2 has. The honest reading is that T2 is not
in flight in any sense that involves flying — it is one externally blocked
waypoint from landing, and has been since 2026-09-03. **T4 is the one being
worked.**

**T4 waypoint state:** W1, W2 and W3 `LANDED`
([S027](../../journal/2026-09-08-S027-mastery.md)). Mastery is persisted per
tag, difficulty is a parameter level authors opt in to, and the update rule
runs on every banked run. W4 — the selection policy targeting a 70–80%
success band — is next and is the first waypoint whose design is genuinely
open.

The count was wrong for five sessions and the reason is worth keeping: T7 was
opened while T2 was in flight and T3 while both were, so the board was being
used as a set of open workstreams rather than a heading. What made it wrong
for so long afterwards was subtler — T7 was *finished* and simply never
closed, and "never closed" hid a criterion that was not met. **A trajectory
left open is not a neutral state; it is an unchecked claim.**

Scheduling for these lives in [`SCHEDULE.md`](../../SCHEDULE.md). Progress
against them is recorded chronologically in [`journal/`](../../journal/).

## Rules

1. A waypoint that cannot be shipped alone is not a waypoint — split it.
2. Exit criteria are written **before** work starts and are not edited to match
   what was built. If they turn out wrong, that is a finding worth recording in
   the journal, not a document to quietly amend.
3. A trajectory moving to `LANDED` requires a journal entry citing the evidence
   for each exit criterion.
