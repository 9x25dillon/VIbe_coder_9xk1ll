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
| [T3](T3-boss-engine.md) | Boss engine: interactive slow-motion debugger | Phase 2 | `IN FLIGHT` | 2026-09-20 |
| [T4](T4-adaptive.md) | Adaptive difficulty | Phase 3 | `PLOTTED` | 2026-10-04 |
| [T5](T5-community.md) | Daily challenges, leaderboards, level editor | Phase 4 | `PLOTTED` | 2026-10-18 |
| [T6](T6-presentation.md) | Presentation layer: capability-aware terminal rendering | cross-cutting | `LANDED` | 2026-08-08 |
| [T7](T7-interactive.md) | Interactive full-screen play: editor, motion, visualiser | cross-cutting | `IN FLIGHT` | — |

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
([S016](../../journal/2026-09-06-S016-boss-format.md)). W2–W8 outstanding. T3
was started at the user's request with T2 one waypoint from landing and
externally blocked, which is the honest reason it went first rather than a
claim that T2 finished.

**Three** trajectories now hold `IN FLIGHT` at once, against the rule in the
status vocabulary above, which says exactly one should. T7 was opened while T2
was in flight; T3 was opened while both were. That is a fact rather than an
amendment, and it is worth reading as one: T2 is late and blocked, T7 is
complete through W8 but never formally landed, and the count says the board is
being used as a set of open workstreams rather than a heading. Landing T7 or
closing out T2's W4 would put it back to one.

Scheduling for these lives in [`SCHEDULE.md`](../../SCHEDULE.md). Progress
against them is recorded chronologically in [`journal/`](../../journal/).

## Rules

1. A waypoint that cannot be shipped alone is not a waypoint — split it.
2. Exit criteria are written **before** work starts and are not edited to match
   what was built. If they turn out wrong, that is a finding worth recording in
   the journal, not a document to quietly amend.
3. A trajectory moving to `LANDED` requires a journal entry citing the evidence
   for each exit criterion.
