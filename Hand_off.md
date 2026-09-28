# Hand_off.md — orientation for the next session

**Composed:** 2026-09-28, at the close of S041 · **Trajectory in flight:** T8
(desktop) · **Consult after** the most recent [`journal/`](journal/) entry and
[`docs/trajectories/T8-desktop.md`](docs/trajectories/T8-desktop.md).

This document is a concise point of entry. It neither supersedes the working
agreement in [`CLAUDE.md`](CLAUDE.md) nor the record system; it directs you to
them. Historical session narratives reside in [journal/](journal/README.md);
this file describes only the present state and the immediate way forward.

---

## 1. The pitfall you will encounter first

**Execute every gate under `python3.11`, never bare `python3`.** On this host
`python3` resolves to **3.14.7**, whereas the op-count baselines in
`data/baselines/` were recorded under **3.11.15**. Because op counts are
interpreter-dependent, running under `python3` produces roughly 25 spurious
failures that do *not* indicate defective code. This was confirmed in S041.
The project metadata still declares Python 3.10+; compatibility with 3.14 has
not been established, so consult the existing runtime notes before broadening
support.

```bash
VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests   # ~40s inner loop, green
python3.11 -m unittest discover -s tests                           # unpinned; required before commit (N8)
python3.11 -m vibecoder.cli verify --seeds 3
```

Should a baseline ever require re-recording, undertake it deliberately and
exclusively under 3.11 — 3.14's figures must never become the recorded truth.
For any exploratory run capable of persisting progress, first point
`VIBECODER_HOME` at a fresh scratch directory; the player's genuine profile
must remain untouched.

## 2. Present state

- **T8 W1 (portable runtime transport) is implemented and committed.** The
  Unix-exclusive `select` streaming formerly in `runner.py` has been superseded
  by `vibecoder/_process.py` (`Process`), which provides reader threads,
  bounded output capture, a parent-side watchdog that fires even during silent
  native calls, and cleanup of the entire process tree. Windows resource limits
  are enforced in `vibecoder/_windows_job.py` (pure `ctypes`, no C extension).
  `term.py` now degrades gracefully in the absence of POSIX `termios`/`tty`.
- **Verified green:** `test_portability` (17 passed, 1 Windows-only skip); the
  full suite under `python3.11` pinned to bubblewrap = **1413 run, OK, 7
  skipped** (unpinned discovery = **1437**). Discovered counts vary with
  backend availability, so treat them as observations, not constants.
- **Records reconciled:** S040 is the discovery/ADR session (documentation
  only); S041 is this implementation. Because `data/` is immutable (N6), S040
  was deliberately left unedited.
- **The terminal cockpit** (shared presentation layer, campaign browser,
  editor sidebar, boss machine view, repair inspector) is landed and remains
  the current interface. Its design is documented in [docs/UI.md](docs/UI.md),
  with a [rendered preview](docs/visual-overhaul.svg) and the
  [2026-09-10 review](docs/reviews/2026-09-10.md); its interaction and layout
  contracts are exercised by [test_cockpit.py](tests/test_cockpit.py).

## 3. What remains unproven (do not assert these)

- Packaged execution on Windows and macOS. No native runner exists in this
  environment.
- `tools/desktop/bundle_runtime.py`, `launcher.py`, and `smoke.py` are written
  but **entirely unexercised**: the standalone CPython download requires
  network access (it fails here with `URLError`) as well as a native host.
- The unpinned multi-backend escape sweep (Docker included) was not re-run in
  S041 — only bubblewrap was exercised.
- Sustained human play of the cockpit at **80 × 24** and **120 × 30** (Q101).
  Automated PTY coverage exists, but it is not a substitute for a person
  playing.

## 4. The single next action (T8 W1, exit criterion 1)

On a Windows runner and a macOS runner, each with network access:

```bash
python3 tools/desktop/bundle_runtime.py     # fetch and relocate a private CPython
python3 tools/desktop/smoke.py              # level execution + live pause/repair on the bundle
```

Record the measured per-platform startup and execution latency together with
the runtime hash. Absent a native CI link, a signature, or a human-play note,
the corresponding gate is **not** complete — irrespective of how persuasive the
local evidence appears. If no native runner is obtainable, resolve Q103 first
rather than approximating the evidence.

## 5. Invariants most directly in play

- **N9 provenance:** `run_code` accepts a `Source`; third-party source must
  raise `SandboxUnavailable` rather than execute on a non-isolating backend,
  *even under an explicit pin*. `_backend_for` enforces this — preserve it.
- **N1, no dependencies** — extending to the desktop tooling and to tests.
- **N4:** the sandbox is an isolation boundary; never characterise it as a
  security boundary. Never weaken a sandbox assertion to obtain a green run.
- **`runner.run_code` is the seam** (see ARCHITECTURE): `_process.Process` now
  sits beneath it; keep the signature stable.
- **N2 / N3:** `_harness.py` never imports the package, and the profiler never
  executes the source it analyses.
- **Presentation:** colour is ornamentation, never structure. Preserve ASCII,
  `NO_COLOR`, and reduced-motion behaviour; `showcase | cat` must emit zero
  escape bytes. `TerminalSession.resized` is a *consuming boolean property*,
  not a method — do not reproduce an obsolete `.resized()` call. Restore
  terminal ownership before launching another screen; sessions must not nest
  alternate screens.

## 6. Carried-forward context (principal decisions and open assumptions)

- **D240:** the implementation was recorded as a distinct session (S041) rather
  than as an amendment to S040, because records are immutable.
- **D241:** reader threads with a bounded queue were chosen over `select`,
  since Windows cannot `select` on anonymous pipes.
- **Unverified assumption:** that a *bundled* CPython (as distinct from a frozen
  application) can launch the standalone `_harness.py` on Windows and macOS.
  This is the crux of W1 and currently lacks any native evidence.
- **Unverified assumption:** boss runs are not banked (Q84); the desktop product
  introduces no boss persistence without a separate storage decision.
- **Open — Q103:** which native runners and signing identity will furnish the
  platform evidence for T8 W1 and W4.
- **Open — Q100:** server-side verification cannot establish human solve time.
  The proposed leaderboard scores Accuracy + Functional and treats Speed as
  personal. This alters scoring semantics and requires the user's explicit
  approval before T5 W3 proceeds.
- **Community levels are not secured merely by sandboxing reference runs:**
  module imports and `make_tests` currently execute in the parent process. T5
  sharing needs a suitable data format before third-party levels are accepted.
- T1, T3, T4, T6, and T7 are landed; T5 W1/W2 are complete; T2 W4 remains
  blocked on a registered OAuth application.

## 7. Session review carried forward (S041)

**Vocabulary for more precise shorthand** (employ these in prompts; I shall
as well):

- **Idempotent** — an operation that yields an identical result however many
  times it is performed. "Make the bank step idempotent" signifies that a
  re-submission must never double-score — directly pertinent to T8 W2's
  transactional progress.
- **Provenance** — the recorded origin of an artefact, used to determine how
  far it may be trusted. It is already this repository's term for "where did
  this code originate, and may it run on the player's machine" (N9). "Watch
  provenance here" scopes an entire class of review in a single phrase.

**Working efficiently:** read local context before invoking tools; batch
independent reads and tests while keeping writes and dependent Git operations
sequential. Run focused checks while editing and the full unpinned gate before
committing. When altering lifecycle code, perform a real terminal smoke check
early — pure composition cannot validate it. Rewrite this hand-off whenever
scope changes, removing stale relative dates and distinguishing measured
results from the human validation still outstanding.

The chat summary at the close of S041 contains the complete efficiency review;
its durable elements are captured above.
