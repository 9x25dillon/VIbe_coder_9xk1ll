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
| [T3](T3-boss-engine.md) | Boss engine: interactive slow-motion debugger | Phase 2 | `PLOTTED` | 2026-09-20 |
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
W3 `LANDED` ([S006](../../journal/2026-09-03-S006-provenance.md)). W4–W7
outstanding. Exit criteria 1, 2, 3 and 7 are verified; 4, 5 and 6 belong to
W5–W6 and are untouched. The trajectory's 2026-08-30 target has passed; it is
late, not re-dated.

⚠ The hard gate in [T5](T5-community.md) — "W6 may not ship unless T2 W1–W3
are landed" — is now *satisfiable*, and is not sufficient. A level is an
importable module and its `make_tests` runs in the parent, so neither is
covered by the provenance flag W3 added. See M12 in
[S006](../../journal/2026-09-03-S006-provenance.md).

**T7 waypoint state:** W1–W7 `LANDED`, W8 partial
([S004](../../journal/2026-09-03-S004-interactive.md)). The score panel animates
a finished result rather than assembling as tests report, because the harness
returns one object at the end of a run. Recorded as partial rather than met.

Two trajectories hold `IN FLIGHT` at once, against the rule in the status
vocabulary above. T7 was opened at the user's request while T2 was still in
flight. That is a fact, not an amendment: T2 is the one that is late.

Scheduling for these lives in [`SCHEDULE.md`](../../SCHEDULE.md). Progress
against them is recorded chronologically in [`journal/`](../../journal/).

## Rules

1. A waypoint that cannot be shipped alone is not a waypoint — split it.
2. Exit criteria are written **before** work starts and are not edited to match
   what was built. If they turn out wrong, that is a finding worth recording in
   the journal, not a document to quietly amend.
3. A trajectory moving to `LANDED` requires a journal entry citing the evidence
   for each exit criterion.
