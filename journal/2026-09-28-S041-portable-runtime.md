# S041 — Portable runtime transport, and reconciling the record

**Date:** 2026-09-28 · **Duration:** not tracked · **Trajectory:** T8 ·
**Competency band:** `Create` ·
**Data:** [data twin](../data/sessions/2026-09-28-S041.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | The runtime transport streams bounded results without POSIX `select`, on any OS | met |
| 2 | Third-party source cannot execute on a nonisolating backend, even under an explicit pin | met |
| 3 | The CLI imports and runs with POSIX terminal modules absent | met |
| 4 | A packaged CPython runtime executes a level on Windows and macOS | deferred |
| 5 | The record honestly separates discovery from implementation | met |

## What was built

This session is the **implementation** half of the desktop work whose discovery
was recorded in [S040](2026-09-28-S040-desktop-discovery.md). S040 was, and
remains, a documentation-only record; the code below was written after the ADR
was approved and had no session record of its own until now. Because `data/` is
immutable (N6), S040 is left untouched and this record is added rather than
S040 being rewritten.

- [`vibecoder/_process.py`](../vibecoder/_process.py) — a `Process` transport:
  reader threads (not `select`, which cannot read anonymous pipes on Windows)
  draining stdout and stderr concurrently, a bounded queue, byte-safe line
  decoding, output/line caps, and process-tree ownership on close.
- [`vibecoder/_windows_job.py`](../vibecoder/_windows_job.py) — Windows Job
  Object memory/CPU/process limits via `ctypes`, no C extension (N1).
- [`vibecoder/runner.py`](../vibecoder/runner.py) — `run_code` and `LiveRun`
  stream through `Process`; one streaming path for both progress and silent
  runs; a parent watchdog that fires even when the child is inside a silent
  native call; provenance kept authoritative (`_backend_for` raises
  `SandboxUnavailable` if third-party source would land on a nonisolating
  backend, even under an explicit pin — N9).
- [`vibecoder/term.py`](../vibecoder/term.py) — imports of `termios`/`tty` made
  optional so the line-oriented CLI imports on Windows.
- [`tests/test_portability.py`](../tests/test_portability.py) — 17 tests of the
  real failure modes (UTF-8 split across writes, stderr drain, output bounds,
  blocked writer vs deadline, thread reaping, owned-descendant kill, the
  provenance guard, live abort/watchdog/crash paths).
- [`docs/trajectories/T8-desktop.md`](../docs/trajectories/T8-desktop.md) and a
  flight-board note in [`docs/trajectories/README.md`](../docs/trajectories/README.md).
- `tools/desktop/` — a reproducible runtime bundler, launcher, smoke test and a
  runtime lock file. Recorded but **not** exercised: no network, no native host.
- `CLAUDE.md` and `README.md` test count corrected `1420 → 1437`.

## Evidence

- `VIBECODER_SANDBOX=bwrap python3 -m unittest tests.test_portability -v`:
  **17 ok, 1 skipped** (Windows job path). Passes under 3.11 and 3.14.
- `VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests`:
  **Ran 1413 tests in 96.200s, OK (skipped=7)**. The bwrap pin narrows the
  escape suite; unpinned discovery finds **1437**.
- `python3.11 -m unittest tests.test_records`: **21 ok** after the count fix.
- Interpreter drift, **verified**: this host's `python3` is **3.14.7** and the
  full suite fails **25** tests under it — 24 op-count baseline mismatches plus
  one boss-replay assertion — while `python3.11` (**3.11.15**, the interpreter
  the baselines were recorded on) is clean. Op counts are interpreter-dependent.
- **UNVERIFIED**: the unpinned multi-backend escape sweep was not re-run this
  session (only bubblewrap). The portability changes do not alter backend
  selection beyond the provenance guard, which is directly tested.
- **UNVERIFIED**: Windows/macOS packaged execution. No native runner; the
  runtime download fails with `URLError` offline. The lock file is recorded;
  execution is unproven.

## Misconceptions and corrections

### M60 — A docs-only journal can ship with an implementation diff

**Believed:** The S040 record described what reached the repository.
**Revealed by:** The working tree carried the transport, tests and an IN FLIGHT
T8 trajectory that S040 explicitly says were not built; the first commit paired
a "no code changed" journal with a large code diff. **Corrected to:** Discovery
and implementation are separate sessions; S040 stands, S041 is added. **Cost:**
the reconciliation this record performs. **Lesson:** a journal entry must
describe the diff it ships in.

### M61 — A baseline reproduces on any interpreter

**Believed:** `python3 -m unittest discover` reproduces the op-count baselines
anywhere. **Revealed by:** 25 failures under `python3` (3.14.7), zero under
`python3.11`. **Corrected to:** the baselines are pinned to CPython 3.11; run
the gates as `python3.11` on this host. **Lesson:** pin the interpreter, not
just the sandbox backend — a reproducibility gate is only reproducible against
the interpreter that produced it.

## Friction

The implementation transcript ended on a failing portability test; the committed
tree has all 17 green. The host default `python3` (3.14) diverges from the 3.11
baseline, so every gate must be invoked as `python3.11`. Packaged-runtime
bundling could not be exercised offline and without a native host.

## Decisions

| # | Decision | Alternatives | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D240 | Record implementation as a new session S041, not an edit of S040 | edit S040; squash into one; supersede S040 | `data/` is immutable (N6); S040 is truthful about discovery, so this is additive | no |
| D241 | Drain pipes with reader threads + bounded queue, not `select` | select/poll; asyncio; `communicate()` | Windows can't `select` anonymous pipes; threads work everywhere, drain stderr concurrently, keep `run_code`'s signature stable | yes (behind `_process.Process`) |

## Handoff

- **State:** T8 W1 transport implemented and committed; full suite green under
  `python3.11` pinned to bubblewrap; records reconciled; test count now 1437.
  Native packaging and Windows/macOS execution unproven.
- **Next action:** on a Windows and a macOS runner with network, run
  `tools/desktop/bundle_runtime.py` then `tools/desktop/smoke.py` to prove a
  relocated packaged CPython runs a level and a live repair (T8 W1 criterion 1).
- **Blockers:** no Windows/macOS runner here; no network for the runtime
  download; signing credentials absent (T8 W4).
- **Context required:** run gates as `python3.11`, not `python3` (host default
  is 3.14 and op-count baselines only reproduce under 3.11); `runner.run_code`
  is the stable seam with `_process.Process` underneath; N9 provenance must not
  weaken. See [`Hand_off.md`](../Hand_off.md).

## Open questions

| # | Question | Owner | Status |
| --- | --- | --- | --- |
| Q102 | Accept the desktop stack, session policy and staged gates? | T8 | answered — approved 2026-09-28; T8 IN FLIGHT |
| Q103 | Which native runners and signing identity supply Windows/macOS execution and installer evidence for T8 W1/W4? | T8 | open |
