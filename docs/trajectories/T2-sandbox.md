# T2 — Trusted execution & codebase ingestion

**Design phase:** 1 · **Status:** `CLEARED` · **Target:** 2026-08-30 ·
**Depends on:** T1 (`LANDED`)

## Heading

T1's sandbox protects the game from the player's mistakes. It does not protect
the player from anyone else's code, and it must, because two features in the
design ship untrusted Python across a trust boundary: **daily challenges**
(T5 serves code we generate to machines we do not control) and the **community
level editor** (T5 serves code *other players wrote* to a player's machine).
The moment either lands, `_harness.py` becomes a remote code execution vector.

T2 also opens the second half of the Vibe Profiler. Today it reads a local
path; the design calls for GitHub OAuth and `.zip` upload, which means ingesting
repositories that may be large, hostile, or not really Python at all.

The ordering matters: ingestion without a real sandbox is the same bug with a
wider aperture, so W1–W3 land before W4.

## Waypoints

| ID | Waypoint | Notes |
| --- | --- | --- |
| W1 | Container-backed runner behind the existing `run_code` signature | The interface stays; only the transport changes. `_harness.py` becomes the in-container entrypoint. |
| W2 | Network namespace off, read-only rootfs, non-root user, seccomp profile | A submission must not be able to reach the network or the host filesystem. |
| W3 | Untrusted-source flag on `run_code`, forcing the container path | Local play may keep the fast subprocess path; anything from a third party may not. |
| W4 | GitHub OAuth ingestion: device flow, repo listing, shallow clone, profile, discard | Never persist source. Persist only the derived Vibe Vector. |
| W5 | `.zip` upload path with a decompression bomb guard | Size, entry-count, and path-traversal limits before anything is written. |
| W6 | Ingestion limits: file count, total bytes, per-file bytes, wall-clock budget | A 2 GB monorepo must degrade to a partial profile, not a hang. |
| W7 | Vibe Vector versioning and migration | The schema will change; profiles must survive it. |

## Exit criteria

1. A submission that attempts an outbound connection fails with a network
   error, and the attempt is recorded.
2. A submission that attempts to read outside its working directory fails.
3. A fork bomb, a 10 GB allocation and a `while True` are each contained, with
   the parent process unaffected and a diagnosable error returned.
4. A zip bomb (≤1 MB compressed, ≥1 GB expanded) is rejected before expansion.
5. A repository is profiled end to end, with no source retained on disk
   afterwards — verified by inspecting the working directory post-run.
6. Profiling a 5,000-file repository completes within its budget or returns a
   partial profile flagged as partial. It does not hang.
7. Every T1 test still passes against the container runner.

## Known hazards

- **Container startup dominates runtime for a 50 ms submission.** A warm pool
  is the standard answer and the standard source of state-leak bugs between
  runs. Prefer a cold container per untrusted run until measurement forces the
  issue.
- **OAuth scope creep.** The profiler needs to *read* code. Requesting anything
  beyond read-only repository access is unjustifiable and will be treated as a
  defect, not a convenience.
- **Ingestion is a privacy surface.** Source code is the most sensitive thing a
  developer owns. The design commitment is that source is never persisted and
  never leaves the machine doing the analysis. That has to be verifiable, not
  merely stated — hence exit criterion 5.
- **`sys.settrace` inside a container still costs ~2× runtime.** Budgets need
  to account for the second instrumented pass.

## Instrument checks

- An adversarial test suite (`tests/test_sandbox_escape.py`) that asserts each
  escape attempt fails. It must run in CI, not by hand.
- Ingestion timing histogram across repositories of 10 / 100 / 1,000 / 5,000
  files.
- A post-ingestion assertion that the workspace is empty.
