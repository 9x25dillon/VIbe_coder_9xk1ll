# Working journal

A chronological record of every working session on VibeCoder. One file per
session, named `YYYY-MM-DD-Snnn-slug.md`, so the directory sorts into
chronological order by default and a session can be cited by id.

Each entry has a machine-readable twin in [`data/sessions/`](../data/sessions/)
carrying the same facts as JSON, so progress can be queried without parsing
prose. The Markdown is for humans; the JSON is for tooling. Neither is a
summary of the other — they are generated together and must agree.

## Why this exists

Two reasons, and the second is the one that usually gets dropped.

1. **Continuity.** Any session may be picked up by someone else — or by the
   same person three weeks later with no memory of it. The handoff block exists
   so that resuming does not require re-deriving the state of the world.
2. **Learning.** This project is a teaching tool, and a teaching tool built
   without recording what its own construction taught is wasting the best data
   it will ever have. Every wrong assumption caught here is a candidate Vibe
   Tip, a candidate level, or a candidate exit criterion.

## Educational parameters

Every session review is structured against the same rubric. The fields are
fixed so that entries can be compared across months.

### 1. Objectives

What the session set out to establish, written as observable outcomes
("the Functional axis separates naive from optimal solutions"), never as
activities ("work on scoring"). An objective that cannot be shown to have
succeeded or failed is malformed.

### 2. Competency band

Where the session's work sat on a Bloom-style ladder. Recorded because a project
spending every session at `Apply` is executing, not designing, and that is worth
noticing early.

| Band | In this project |
| --- | --- |
| `Recall` | Looking up an API, re-reading a spec |
| `Understand` | Tracing existing behaviour, reading a trace |
| `Apply` | Implementing a specified component |
| `Analyse` | Finding why a measurement disagrees with expectation |
| `Evaluate` | Judging a design trade-off against evidence |
| `Create` | Designing a mechanism that did not previously exist |

### 3. Evidence

The commands run and the results observed. Claims without evidence are marked
`UNVERIFIED` and stay that way until someone runs something. A session that
reports success with no evidence field is an incomplete session.

### 4. Misconceptions and corrections

The most valuable field. What was believed at the start of the session that
turned out to be wrong, what revealed it, and what the corrected understanding
is. Written even when — especially when — the mistake was avoidable.

### 5. Friction

Where effort went that produced no artefact: confusing APIs, slow feedback
loops, missing tooling. Friction recorded across several sessions is what
justifies building infrastructure.

### 6. Handoff

The block a person reads first when resuming. Four fields, no prose:

- **State** — what is true of the repository right now
- **Next action** — the single next thing to do, concretely
- **Blockers** — what would stop that, or `none`
- **Context required** — what to read before starting

### 7. Open questions

Questions raised and not settled, carried forward until answered or dismissed.
Each one has an owner trajectory.

## Index

| Session | Date | Focus | Trajectory | Band |
| --- | --- | --- | --- | --- |
| [S001](2026-08-08-S001-core-loop.md) | 2026-08-08 | Phase 0 core loop, end to end | T1 | `Create` |

## Writing a new entry

Copy [`TEMPLATE.md`](TEMPLATE.md), fill every field, and add the matching JSON
in `data/sessions/`. Do not delete a field because it is empty — write `none`,
which is information. A field silently missing is not.
