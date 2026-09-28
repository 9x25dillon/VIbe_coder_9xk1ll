# T8 — Native desktop product

**Status:** `IN FLIGHT` · **Started:** 2026-09-28 · **Target:** evidence-gated
**Depends on:** existing engine and accepted [ADR-001](../desktop/ADR-001-desktop.md).

## Heading

Deliver the existing Python learning mechanics through Tauri, React/TypeScript
and Monaco with a bundled CPython interpreter. The user approved the architecture
and implementation on 2026-09-28. Core runtime and core tests remain stdlib-only.
This starts while T2's OAuth waypoint is externally blocked and T5 is unfinished;
those workstreams are not silently declared complete or re-dated.

## Waypoints

| ID | Outcome | State |
| --- | --- | --- |
| W1 | Reproducible packaged Python runtime; portable pipes, cleanup and limits; level/live repair on Windows and macOS | implementing |
| W2 | Versioned stdio application service; level/boss lifecycle shared with CLI; transactional progress and explicit provenance | pending W1 native gate |
| W3 | Campaign, editor, scoring, replay, boss, daily, profiler and onboarding desktop flows | pending W2 |
| W4 | Signed installers, verified updater, migration and user documentation | pending W3 |
| W5 | Native regression, accessibility, human play and performance qualification | checks throughout; release gate pending |

## Exit criteria

1. A relocated packaged runtime starts with no system Python, executes a level,
   reports progressive results, pauses and repairs a live failure on Windows,
   macOS and the supported Linux baseline.
2. Untrusted execution cannot fall back to a nonisolating backend, including
   under an explicit pin. Resource exhaustion, blocked native calls, oversized
   output, cancellation and process exit cannot hang the parent or leak owned
   children.
3. Scoring, trace and profiler semantics match the existing engine. Application
   use cases have explicit, tested timing, practice and idempotent bank rules.
4. Existing player records and runs remain readable without data loss; concurrent
   clients and interrupted writes have tested recovery behavior.
5. All critical desktop paths run against the real packaged engine, with
   keyboard access, readable failures, reduced motion and native checks.
6. Signed installer and update artifacts pass clean-machine checks on the
   supported platform matrix. Signing credentials and publishing remain explicit
   release prerequisites.
7. The original Linux regression gate and reference verification stay green;
   new native tests cover OS-specific replacements without deleting old coverage.

## Known hazards

- Windows pipe semantics and macOS resource enforcement differ from Linux.
- A frozen Python app is not necessarily an interpreter capable of launching
  the standalone harness. Bundle a real CPython installation instead.
- Private CLI/editor orchestration currently differs; characterize before merging.
- Native CI requires publishing an isolated development branch; a local pass
  cannot substitute for that evidence. No release may be inferred from CI config.
- Keep test automation and build dependencies out of the shipped core.
- Boss persistence/unlocks remain the separate Q84 decision.

## Instrument checks

Record packaged startup and execution latency by platform and runtime hash.
Keep cold-reference timing separate from cached execution; enforce responsive
cancellation during intentionally slow submissions. Validate installs with no
Python, Node, Rust or Docker present. Record actual native CI links, signatures
and human play observations before claiming the corresponding gate complete.
