# S040 — Desktop discovery and architecture for review

**Date:** 2026-09-28 · **Duration:** not tracked · **Trajectory:** T6 (discovery only) ·
**Competency band:** `Analyse` ·
**Data:** [data twin](../data/sessions/2026-09-28-S040.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | Existing engine boundaries and baseline are evidenced | met |
| 2 | Desktop architecture is concrete enough for user review | met |
| 3 | Application implementation waits for the requested review | met |

## What was built

Documentation only: [proposed ADR](../docs/desktop/ADR-001-desktop.md) and
[engine API inventory](../docs/desktop/ENGINE_API.md). The ADR includes product
vision, migration policy, protocol families, packaging and acceptance gates.
The inventory records module public signatures, fields and package exports.
No application, test, dependency or existing player-data file was changed.

The requested desktop scope extends beyond the existing trajectories. This
analysis is filed under T6 as presentation discovery, following the existing
record precedent; it does not reopen T6 or claim a new trajectory has landed.
A desktop trajectory should be established after architecture approval.

## Evidence

- Existing clean origin checkout at `7a5940c8c95ed3dbe5c1f21d8b475241ea867644`;
  no duplicate clone needed. Read all existing docs and requested guidance.
- `python3.11 -m unittest discover -s tests` with host access:
  **1420 tests OK in 82.864s**, no skips reported.
- `python3.11 -m vibecoder.cli verify --seeds 3`: **54/54 clean**.
- Documentation/schema/link gate with host access: `python3.11 -m unittest
  discover -s tests -p test_records.py`: **21 tests OK in 4.652s**.
- Restricted run: 1396 discovered, three documentation-count failures, one
  unavailable isolation backend error, 32 skips. Host gate passed unchanged.
- CLI map/showcase/profile/status/practice/replay succeeded in scratch homes;
  captured transcripts contained no escape bytes. Both live reference boss and
  starter plus scripted repair completed successfully.
- Daily 2026-09-28 selected `w1-l3-count`, seed 687241; two supplied-time
  completions retained ranked flags `[true, false]`.
- Real PTY driver `/tmp/vibecoder-phase0-pty.py` exercised campaign → objective
  → failed starter → reference paste → successful second attempt → campaign →
  quit at 80×24 and 120×30. Both scored 110 and restored termios attributes.
  Driver is temporary, not a durable regression test or human playtest.
- Source review found CLI/editor orchestration differences, absent boss banking,
  Windows pipe/resource/terminal constraints, persistence concurrency gaps and
  a provenance pin exception. A selection-only probe returned nonisolating
  subprocess for `untrusted=True` under an explicit subprocess pin; no hostile
  code was executed.
- Seed-1 default-difficulty latency across all twelve levels: generation
  0.08–1.60 ms; cold reference 56.13–93.47 ms; median of three traced reference
  submissions per level 56.85–114.43 ms. Python 3.11.15/Linux/subprocess only.
- Windows/macOS execution, signed installation, GUI quality and native latency:
  **UNVERIFIED**, pending implementation and native-platform checks.

Temporary raw evidence: `/tmp/vibecoder-phase0-host-tests.log`,
`/tmp/vibecoder-phase0-verify.log`, `/tmp/vibecoder-phase0-latency.json`.
These files may disappear; the results above and the data twin are the durable
record. No user source was copied into committed evidence.

## Misconceptions and corrections

### M59 — A single engine means the clients have identical mechanics

**Believed:** A GUI could wrap the public functions without resolving lifecycle
policy. **Revealed by:** `cmd_play`, `Editor.execute/_bank`, and `cmd_boss`.
**Corrected to:** Pure scoring is shared, but adaptation, banking, trace capture
and boss persistence differ or are absent. Extract a service and characterize
those differences before declaring parity. **Cost:** inspection time, no shipped
code or player-data change.

## Friction

Restricted execution hid isolating backends; host authorization resolved it.
An initial daily smoke used the missing configured editor `cursor`; subsequent
checks used explicit solutions. An initial replay invocation incorrectly assumed
a `--speed` flag; the documented replay command succeeded. Broad output reads
were split into smaller reads where the tool truncated them.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D239 | Propose Tauri/React/Monaco with real CPython sidecar; not yet accepted | Electron, PyQt6, ImGui, PyO3, frozen single executable | Keeps engine stdlib-only and fresh-child interpreter contract; exposes portability work early | yes, outer transport/client seam |

## Handoff

- **State:** Phase 0 complete; ADR proposed, no application code written.
- **Next action:** User reviews ADR; on approval establish desktop trajectory
  and prove packaged execution/repair on Windows and macOS before building UI.
- **Blockers:** User-requested architecture review precedes implementation;
  signing credentials and native runners are release prerequisites, not assumed
  available. Existing T2 OAuth and Q100 decisions remain separate.
- **Context required:** Python 3.11; full host backend gate; exact API inventory;
  service orchestration gaps; do not weaken provenance or fake timing.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q102 | Accept the proposed desktop stack, session policy and staged portability/service gates? | T6 (discovery; future desktop trajectory pending review) | open |

Existing Q84 (boss progression) remains open. This proposal adds no boss unlocks
or durable boss record without a separate storage/product decision.
