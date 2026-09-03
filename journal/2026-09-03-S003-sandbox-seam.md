# S003 — The transport seam

**Date:** 2026-09-03 · **Duration:** — · **Trajectory:** T2 ·
**Competency band:** `Create` ·
**Data:** [`data/sessions/2026-09-03-S003.json`](../data/sessions/2026-09-03-S003.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | `run_code` can execute under an isolating backend without its signature changing | ✅ met |
| 2 | `_harness.py` stays the single child entrypoint on every transport (N2) | ✅ met |
| 3 | Every T1 test passes on every backend — T2 exit criterion 7 | ✅ met |
| 4 | Untrusted code cannot silently fall back to the host process | ✅ met |
| 5 | Which backends a machine offers is inspectable without reading code | ✅ met |

## What was built

[`vibecoder/sandbox.py`](../vibecoder/sandbox.py) is the seam
[ARCHITECTURE.md](../docs/ARCHITECTURE.md) has been promising since T1. It holds
the whole of the answer to *where does this code run*, and nothing else. A
backend answers exactly one question — given the harness script, what argv
spawns it? — and `runner.py` keeps everything it already had: building the
payload, enforcing the wall clock, parsing the reply. The seam is that narrow on
purpose. A transport that could also shape the result would be a transport that
could change a score.

Three backends implement it. `SubprocessBackend` is the Phase 0 path, unchanged
and still the default for local play. `BwrapBackend` assembles a filesystem
rather than inheriting one: the interpreter's own prefix and the shared
libraries it links against, each read-only, plus a tmpfs working directory that
evaporates with the process. The player's home directory and `/etc` are not
absent-by-permission, they are absent-by-mount. `DockerBackend` reaches the same
properties through a container for hosts that have a daemon but no bubblewrap.

**Bubblewrap leads, and Docker is the fallback rather than the other way
round.** The trajectory's own hazard note says container startup dominates
runtime for a 50 ms submission, and measurement agreed loudly: the same suite
takes 5.4 s under bubblewrap and 40.8 s under Docker, an 8.8× tax paid per run
for identical isolation properties. Bubblewrap also needs no daemon and no root,
which matters because the daemon on this machine was inactive and disabled at
the start of the session. The hazard note goes on to recommend a warm pool as
the standard answer; it is also the standard source of state leaks between runs,
and a leak here is one player's code seeing another's. Cold every time, until
measurement forces the issue on a machine that only has Docker.

`select()` refuses rather than degrades. A `VIBECODER_SANDBOX` that names a
backend which cannot run raises `SandboxUnavailable`, and `untrusted=True` with
no isolating backend available raises too. A quiet fallback to the host process
is precisely the failure this module exists to prevent, and it is the kind that
shows up as a security incident rather than a test failure.

`run_code` gained one keyword, `untrusted=False`. Nothing passes `True` yet —
wiring it to community levels and daily challenges is W3's waypoint. The flag
exists now because the seam is meaningless without the thing it selects on, and
because W3 should be a one-line change at each call site rather than a
re-architecture.

## Evidence

```
$ python3 -m unittest discover -s tests
Ran 213 tests in 4.617s — OK

$ VIBECODER_SANDBOX=bwrap python3 -m unittest discover -s tests
Ran 213 tests in 5.351s — OK

$ VIBECODER_SANDBOX=docker python3 -m unittest discover -s tests
Ran 213 tests in 40.752s — OK

$ python3 -m vibecoder.cli verify --seeds 3
18/18 reference runs clean

$ python3 -m vibecoder.cli sandbox | grep -c $'\033'
0
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| Every T1 test passes on the isolating transports (exit criterion 7) | 213 green under `bwrap`; 213 green under `docker` | verified |
| Isolation costs almost nothing under bubblewrap | 4.617 s → 5.351 s, +16% | verified |
| Isolation costs a great deal under Docker | 4.617 s → 40.752 s, 8.8× | verified |
| A submission cannot reach the network | `tests/test_sandbox.py::TestIsolatedExecution::test_the_network_is_unreachable` | verified |
| A submission cannot see the host home directory | `...::test_the_players_home_directory_is_not_visible` | verified |
| Op counts do not depend on the transport | `...::test_the_result_matches_the_untrusted_path` | verified |
| A pinned but unavailable backend raises | `...::test_pinning_an_unavailable_backend_raises` | verified |
| The new CLI output stays depth-invariant | `sandbox \| grep -c $'\033'` → 0 | verified |
| Full containment of a fork bomb / 10 GB allocation (criterion 3) | not attempted | `UNVERIFIED` — W2 |
| seccomp profile, non-root uid mapping | not attempted | `UNVERIFIED` — W2 |

## Misconceptions and corrections

### M5 — A red baseline means a regression

**Believed:** The suite failing on this machine meant something in the repository
was broken, and had to be fixed before any new work started (CLAUDE.md §1.3).

**Revealed by:** Six failures, all `test_recorded_op_counts_still_reproduce`, all
reporting *fewer* operations than the baseline — 1364 against 2184 for
`w1-l3-join`. A regression that made the reference solution do less work while
still passing is not a plausible shape of bug. The baseline file records
`python_version: 3.11.15`; the machine's interpreter is 3.14.7.

**Corrected to:** Op counts are a property of the interpreter, not only of the
code. CPython changed how the constructs in those two levels compile between
3.11 and 3.14, and the instrumentation faithfully reported the new number.
Installing 3.11.15 turned the suite green with no source change at all.

**Cost:** ~15 minutes, all of it before touching any code — which is the
outcome the rule is designed to produce. The rule said stop and diagnose, and
stopping is what distinguished an environment mismatch from a regression.
Rule N1 deserves some credit here too: with no dependency pins to chase, the
interpreter was the only variable left.

### M6 — `docker version` proves the daemon is reachable

**Believed:** A backend probe could ask `docker version --format
'{{.Server.Version}}'` and trust a zero exit status.

**Revealed by:** The probe reported the Docker backend available while
`/var/run/docker.sock` did not exist. The command exits 0 and prints `29.7.2`
regardless — the client answers for the server when the server is absent.

**Corrected to:** `docker info --format '{{.ServerVersion}}'`, which prints an
empty string when the daemon is unreachable, plus a `_probe_ok` hook so a
backend can demand more than an exit status. The generalisable form: a CLI that
wraps a daemon will often report on itself when the daemon is gone, so probe
for a value only the daemon can supply.

**Cost:** ~10 minutes. Caught before shipping, but only because the daemon
happened to be down — on a healthy machine this would have shipped as a probe
that returns `True` unconditionally and fails at the worst moment.

## Friction

- The Docker daemon was `inactive` **and** `disabled` at session start, and
  starting it needs a password the session does not have. It became active
  partway through, which is what made `DockerBackend` testable at all. Had it
  stayed down, W1 would have landed with the Docker path written but unverified.
- Deciding the minimal bubblewrap bind set took several probe cycles. Binding
  `/` read-only works immediately and is wrong — it satisfies "read-only
  rootfs" while leaving exit criterion 2 (no reads outside the working
  directory) failing, since the whole host is still readable. The narrow bind
  set had to be found empirically because the interpreter's shared-library
  dependencies are distribution-specific.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D11 | Bubblewrap is the primary isolating backend; Docker is the fallback | Docker only, as T2 W1 words it; bubblewrap only | 8× less overhead for the same properties, no daemon, no root. The trajectory says "container-backed"; the exit criteria describe isolation properties, and those are what got built | yes — ordering is one tuple in `BACKENDS` |
| D12 | A backend contributes argv and nothing else | Backends own the whole run/parse cycle | A transport that shapes the result is a transport that can change a score | no — it is the shape of the seam |
| D13 | An unavailable pinned backend raises instead of falling back | Warn and downgrade | A silent downgrade to the host process is the exact failure the module exists to prevent | yes |
| D14 | One cold container per Docker run, no warm pool | Warm pool for latency | The trajectory's own hazard note: pools leak state between runs, and here that means across players | yes |
| D15 | `untrusted` is a `run_code` keyword, defaulting to `False` | A separate `run_untrusted` function | Keeps one code path under test; W3 becomes a one-line change per call site | yes |

## Handoff

- **State:** T2 W1 `LANDED`. `vibecoder/sandbox.py` is the transport seam;
  `run_code` keeps its signature and gains `untrusted=`. 213 tests green on the
  subprocess, bubblewrap and Docker backends, `verify` clean on 18 reference
  runs. Exit
  criterion 7 is met; criteria 1 and 2 have early evidence but belong to W2.
  T1 and T6 remain `LANDED`; the engine is unchanged.
- **⚠ Use Python 3.11 on this machine.** The system interpreter is 3.14.7 and
  produces six baseline failures that are not regressions — see M5. `uv run
  --python 3.11 --no-project python3 ...` is what every command above was run
  under. Settle Q11 before this bites someone else.
- **Next action:** T2 W2 — seccomp profile, non-root uid mapping, and
  `tests/test_sandbox_escape.py`, which is the Fri 28 Aug gate and must run in
  CI rather than by hand. The bubblewrap flags already deny the network and the
  host filesystem; W2 is what turns that from an observation into an asserted,
  adversarial guarantee.
- **Blockers:** none for W2 or W3. T2 W4 still needs a registered OAuth
  application and the client-versus-server profiling decision.
- **Context required:** the hazard list in
  [T2](../docs/trajectories/T2-sandbox.md) before touching backend ordering;
  M6 above before writing any availability probe; N4 before describing any of
  this as complete isolation.

**Out of trajectory:** work on a full-screen interactive TUI with a live code
editor and typing visualiser began this session at the user's request. It does
not map to a T2 waypoint. It is being tracked as T7 and recorded separately;
this entry covers only W1.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q11 | Op counts are interpreter-version-bound (M5). Should the project pin an interpreter, record a per-version baseline, or compare within a tolerance? A pin contradicts "runs anywhere a Python 3.10+ interpreter does"; a tolerance weakens the guard that caught M5 in the first place | T2 | open |
| Q12 | The Docker image is pinned by tag (`python:3.11-slim`), which is mutable. Pin by digest, or accept the drift given that the harness is stdlib-only? | T2 | open |
| Q13 | Bubblewrap's bind set is derived from `sys.base_prefix` at call time. Does that hold for a frozen or statically linked interpreter, or does the backend need to declare itself unavailable there? | T2 | open |
