# Hand_off.md — for the next session

**Written:** 2026-09-28, end of S041 · **Trajectory in flight:** T8 (desktop) ·
**Read after** the newest [`journal/`](journal/) entry and
[`docs/trajectories/T8-desktop.md`](docs/trajectories/T8-desktop.md).

This file is a fast on-ramp. It does not replace the working agreement in
[`CLAUDE.md`](CLAUDE.md) or the record system — it points at them.

---

## 1. The one thing that will bite you first

**Run every gate as `python3.11`, not `python3`.** This host's `python3` is
**3.14.7**; the op-count baselines in `data/baselines/` were recorded on
**3.11.15**. Op counts are interpreter-dependent, so under `python3` the suite
shows ~25 spurious failures that are *not* broken code. Confirmed this session.

```bash
VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests   # ~40s inner loop, green
python3.11 -m vibecoder.cli verify --seeds 3
```

If you ever intend to re-record a baseline, do it deliberately and only under
3.11 — never let 3.14's numbers become the recorded truth.

## 2. State as of now

- **T8 W1 (portable runtime transport) is implemented and committed.** The
  Unix-only `select` streaming in `runner.py` is replaced by
  `vibecoder/_process.py` (`Process`): reader threads, bounded output, a parent
  watchdog that fires during silent native calls, and process-tree cleanup.
  Windows resource limits live in `vibecoder/_windows_job.py` (ctypes, no C
  extension). `term.py` degrades without POSIX `termios`/`tty`.
- **Green:** `test_portability` (17 ok, 1 Windows-only skip); full suite under
  `python3.11` pinned to bwrap = **1413 run, OK, 7 skipped** (unpinned discovery
  = **1437**).
- **Records reconciled:** S040 = discovery/ADR (docs only), S041 = this
  implementation. `data/` is immutable (N6), so S040 was not edited.

## 3. What is NOT proven yet (do not claim these)

- Windows/macOS packaged execution. No native runner in this environment.
- `tools/desktop/bundle_runtime.py` / `launcher.py` / `smoke.py` are written but
  **unexercised**: the standalone CPython download needs network (fails with
  `URLError` here) and a native host.
- The unpinned multi-backend escape sweep (docker included) was not re-run this
  session — only bubblewrap.

## 4. Next action (T8 W1 exit criterion 1)

On a Windows runner and a macOS runner, with network:

```bash
python3 tools/desktop/bundle_runtime.py     # fetch + relocate a private CPython
python3 tools/desktop/smoke.py              # level exec + live pause/repair on the bundle
```

Record actual per-platform startup/exec latency and the runtime hash. No native
CI link, signature, or human-play note ⇒ the corresponding gate is not complete.

## 5. Invariants most in play here

- **N9 provenance:** `run_code` takes a `Source`; third-party source must raise
  `SandboxUnavailable` rather than run on a nonisolating backend, *even under an
  explicit pin*. `_backend_for` enforces this; keep it that way.
- **N1 no deps**, including the desktop tooling and tests.
- **N4:** the sandbox is an isolation boundary, never described as security.
- **`runner.run_code` is the seam** (ARCHITECTURE): `_process.Process` sits
  underneath it; keep the signature stable.

## 6. Carry-over context (key decisions & open assumptions)

- **D240:** implementation recorded as a separate session (S041), not an edit of
  S040 — records are immutable.
- **D241:** threads + bounded queue for pipes, chosen over `select`, because
  Windows cannot `select` anonymous pipes.
- **Assumption still unverified:** that a *bundled* CPython (not a frozen app)
  can launch the standalone `_harness.py` on Windows/macOS. This is the crux of
  W1 and has no native evidence yet.
- **Assumption still unverified:** boss runs are not banked (Q84); the desktop
  product adds no boss persistence without a separate storage decision.
- **Open:** Q103 — which native runners + signing identity supply the platform
  evidence for T8 W1/W4.

## 7. Session review carried forward (S041)

**Vocabulary to make our shorthand tighter** (use these in prompts; I will too):

- **Idempotent** — an operation that produces the same result no matter how many
  times it runs. Say "make the bank step idempotent" and I know you mean a
  re-submit must not double-score. Directly relevant to T8 W2's transactional
  progress.
- **Provenance** — the recorded origin of a thing, used to decide how much to
  trust it. It is already this repo's word for "where did this code come from,
  and may it run on the player's machine" (N9). Saying "watch provenance here"
  scopes a whole class of review in one word.

See the chat summary at the end of S041 for the full efficiency review; the
durable pieces are captured above.
