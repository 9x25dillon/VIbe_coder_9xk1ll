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
| [S002](2026-08-08-S002-presentation.md) | 2026-08-08 | Capability-aware terminal rendering | T6 | `Create` |
| [S003](2026-09-03-S003-sandbox-seam.md) | 2026-09-03 | The transport seam under `run_code` | T2 | `Create` |
| [S004](2026-09-03-S004-interactive.md) | 2026-09-03 | Into the alternate screen: the full-screen editor | T7 | `Create` |
| [S005](2026-09-03-S005-hardening.md) | 2026-09-03 | The second layer: seccomp, rlimits, escape suite | T2 | `Create` |
| [S006](2026-09-03-S006-provenance.md) | 2026-09-03 | Where the code came from: the provenance flag | T2 | `Create` |
| [S007](2026-09-03-S007-streaming.md) | 2026-09-03 | Streaming: accuracy assembles as tests report | T7 | `Create` |
| [S008](2026-09-03-S008-latency.md) | 2026-09-03 | The flaky test was right: keystroke latency | T7 | `Analyse` |
| [S009](2026-09-03-S009-beginner-world.md) | 2026-09-03 | An on-ramp, and the world that moved to make room | T1 | `Create` |
| [S010](2026-09-03-S010-scaffolding.md) | 2026-09-03 | Telling a beginner what actually happened | T4 | `Evaluate` |
| [S011](2026-09-04-S011-style-engine.md) | 2026-09-04 | The profiler reads its own code, and dislikes it | T4 | `Create` |
| [S012](2026-09-06-S012-archive-ingestion.md) | 2026-09-06 | The archive we refuse to open | T2 | `Create` |
| [S013](2026-09-06-S013-machine-view.md) | 2026-09-06 | Your function, drawn as a machine, running | T6 | `Create` |
| [S014](2026-09-06-S014-ingestion-budgets.md) | 2026-09-06 | Stopping is not refusing: ingestion budgets | T2 | `Create` |
| [S015](2026-09-06-S015-vector-versioning.md) | 2026-09-06 | The direction that actually loses data | T2 | `Create` |
| [S016](2026-09-06-S016-boss-format.md) | 2026-09-06 | A boss is n linked functions | T3 | `Create` |
| [S017](2026-09-06-S017-live-stepping.md) | 2026-09-06 | Pause is the parent not answering | T3 | `Create` |
| [S018](2026-09-06-S018-step-back.md) | 2026-09-06 | Stepping back is not running backwards | T3 | `Create` |
| [S019](2026-09-06-S019-edit-and-resume.md) | 2026-09-06 | The memo was already in the payload | T3 | `Create` |
| [S020](2026-09-06-S020-typing-the-fix.md) | 2026-09-06 | A fix nobody can type is not playable | T3 | `Create` |

Twenty sessions, and the band column is worth reading as a column rather
than a set of cells: one `Analyse`, one `Evaluate`, and the rest `Create`. That
is a project still building mechanisms rather than tuning them, which is the
right place to be in Phase 2 and will stop being so.

## Writing a new entry

Copy [`TEMPLATE.md`](TEMPLATE.md), fill every field, and add the matching JSON
in `data/sessions/`. Do not delete a field because it is empty — write `none`,
which is information. A field silently missing is not.
