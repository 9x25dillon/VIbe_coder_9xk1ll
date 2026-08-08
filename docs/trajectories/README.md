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
| [T2](T2-sandbox.md) | Trusted execution & codebase ingestion | Phase 1 | `CLEARED` | 2026-08-30 |
| [T3](T3-boss-engine.md) | Boss engine: interactive slow-motion debugger | Phase 2 | `PLOTTED` | 2026-09-20 |
| [T4](T4-adaptive.md) | Adaptive difficulty | Phase 3 | `PLOTTED` | 2026-10-04 |
| [T5](T5-community.md) | Daily challenges, leaderboards, level editor | Phase 4 | `PLOTTED` | 2026-10-18 |

Scheduling for these lives in [`SCHEDULE.md`](../../SCHEDULE.md). Progress
against them is recorded chronologically in [`journal/`](../../journal/).

## Rules

1. A waypoint that cannot be shipped alone is not a waypoint — split it.
2. Exit criteria are written **before** work starts and are not edited to match
   what was built. If they turn out wrong, that is a finding worth recording in
   the journal, not a document to quietly amend.
3. A trajectory moving to `LANDED` requires a journal entry citing the evidence
   for each exit criterion.
