# HANDOFF.md — retrospective on the founding session

**Scope:** [S001](journal/2026-08-08-S001-core-loop.md) and
[S002](journal/2026-08-08-S002-presentation.md) — the session that built the
core loop (T1), the working agreement, the record system, and the presentation
layer (T6). **Composed:** 2026-10-01, which is 54 days after that work, against
a tree that has since run to S044.

**This is not the orientation document.** [`Hand_off.md`](Hand_off.md) is, and
it is current as of S044 — read that first for what is true now, which gates to
run, and what exists. This file does one narrower thing: it reviews and
critiques the founding session, and it has an advantage no retrospective
normally gets. Forty-two later sessions have since stress-tested every decision
made in it, so the criticism below is measured rather than guessed.

> **Naming:** two files now differ only by punctuation. `Hand_off.md` is the
> live entry point; `HANDOFF.md` is this retrospective. They do not collide on
> a case-insensitive filesystem, but the pair is confusing and renaming this to
> `docs/RETROSPECTIVE-S001-S002.md` would be an improvement. Left as asked.

---

## 1. Baseline when this was written

Checked before writing anything, per [CLAUDE.md](CLAUDE.md) §1. **It was red,
on a healthy tree**, and both failures were environmental:

| Failure | Cause | Resolution |
| --- | --- | --- |
| `test_provenance` ERROR | `sandbox.select(untrusted=True)` raises `SandboxUnavailable` with no bubblewrap or Docker on the host — N4 behaving correctly | now skips when no isolating backend exists |
| `test_living_docs_quote_the_real_test_count` ×3 | docs quote CI's 1487; discovery here finds 1463, because `test_sandbox_escape.load_tests` clones its attack cases per *available* backend | now skips when no isolating backend exists |

Neither was a defect in the tree. After both fixes:

```
python3.11 -m unittest discover -s tests   → Ran 1463 tests, OK (skipped=35)
python3.11 -m vibecoder.cli verify --seeds 3 → 54/54 reference runs clean
```

The second failure is mine, from S002. See **M-HANDOFF-1** below; the fix is
referenced from the test's own docstring so the next reader finds the reasoning
rather than just the skip.

---

## 2. What the founding session shipped

Three commits, from an empty repository (a `LICENSE` and nothing else):

| Area | Delivered |
| --- | --- |
| Engine | 11 modules: sandboxed runner, two-pass instrumentation, three-axis scoring, pure-`ast` profiler, style checkers, tip rules, session persistence, trace replay, CLI |
| Content | 6 levels across 2 worlds, each with a reference verified against every seeded variant |
| Agreement | [`CLAUDE.md`](CLAUDE.md) — 8 invariants, session protocol, definition of done |
| Records | `docs/trajectories/` (T1–T6), `journal/` with a fixed rubric, `data/` with schemas and an immutable baseline |
| Presentation | `ui.py` — capability detection, depth-invariant rendering, animation that degrades to a pipe |
| Tests | 194, stdlib `unittest`, zero third-party dependencies |

Two real bugs were found by running the system adversarially rather than
reading it: a naive O(n·m) solution scoring three stars off a 40 ms clock (M1),
and profiler pattern shares saturating at 100% and carrying no signal (M2).

## 3. How it held up

This is the part worth keeping, because it is evidence rather than opinion.

**What survived.** All eight invariants are still in `CLAUDE.md`, verbatim, 42
sessions later. One was added rather than any being removed: **N9** — code
entering the sandbox must declare where it came from — which came out of T2's
provenance work. The record system was not merely kept but used heavily: S003
through S044, nine trajectories, and the
[flight board](docs/trajectories/README.md) now carries per-waypoint state with
evidence links. `data/` immutability (N6) held under pressure — S041 recorded
implementation as a *new* session rather than editing S040 (D240), citing N6 as
the reason.

**What N7 bought.** Exit criteria written before the work, never amended to
match it, caught real things twice more. Landing T7 was expected to be
bookkeeping; checking its nine criteria one at a time found two with no
evidence and one that was simply false — the typing visualiser animated
identically whether or not `animate` was set.

**What broke.** Three things, all traceable to this session, all in §5.

---

## 4. Three places I could have operated more efficiently

**E1 — I blocked on a question in a non-interactive session.**
The opening prompt was truncated mid-sentence (`"using the following text
generate a"`). My first action was `AskUserQuestion`, which returned "did not
answer" because nothing could answer it, and I then proceeded on an assumption
anyway. A whole turn produced nothing. The right move was to do both in one
turn: state the assumption plainly and start building, because with a truncated
prompt the deliverable *is* the clarifying question — a working prototype gets
corrected faster than a menu gets answered.

**E2 — I paid the same doc-count coupling three times.**
The quoted test count went 127 → 131 → 194, and each step was a `sed` plus a
full suite re-run, because I was still adding tests after updating the number.
Counts are a release step: update them once, last, when the suite has stopped
moving. Better still, do not commit a number a test must then police — see
M-HANDOFF-1, which is the same mistake with a longer tail.

**E3 — I built 63 tests on an unvalidated harness.**
`tests/test_ui.py` was written in full against a helper that turned out to be
wrong in two ways: `io.StringIO.encoding` is not writable, and
`mock.patch.dict` rejects `None` values. Both surfaced only after the whole
file existed, so two debug cycles went into test scaffolding rather than the
code under test. One detection test first, confirming the fake stream behaves,
then fan out.

*Smaller instances of the same habit:* writing a baseline to
`data/baselines/` before creating the directory (one failed run), and adding an
`lru_cache` stub to `runner.py` that I removed minutes later without it ever
having done anything.

---

## 5. Three things I could have improved on

**I1 — I never played the game the way a player does.**
Every verification went through `--solution`, scoring a file from disk. The
interactive path — editor launch, the retry loop, `input()` handling, the
`play` command end to end — had no tests and was never once run. I reported the
core loop as complete on the strength of the path a player never takes.

Twenty sessions later, [S022](journal/2026-09-06-S022-actually-playable.md) is
titled *"I never once started a fight the way a player does"* and found the
boss fight unplayable: a wrong answer offered no repair, and the buffer never
grew to hold the next step. Same blind spot, same project, found later and
therefore more expensively. The honest reading is that `--solution` existed for
*my* convenience and I let it stand in for the product.

**I2 — I recorded Q6 instead of owning it, and it is still open.**
I measured a 78× spread in reference op counts — 76 for `w2-l3-wordfreq`, which
delegates to `re` and `Counter`, against 5,958 for `w2-l2-window` in pure
Python — concluded that op counts are not comparable across levels, noted that
wordfreq's Functional axis is close to unwinnable for readable code, wrote it
down, and shipped. It is still open today, and wordfreq still ships
miscalibrated.

Writing a defect down is not the same as owning it. A known-bad calibration
inside the scoring system — the thing the whole product claims to be about —
deserved either a fix or an explicit decision to accept it, not a question
mark. The record system made it *easy* to defer, which is its one failure mode
and worth naming.

**I3 — I built a reproducibility gate without pinning what it reproduces
against.**

Two instances, same root cause.

- Baselines record op counts and a test asserts they still reproduce, but I
  pinned neither the interpreter nor the sandbox backend.
  [S041's M61](journal/2026-09-28-S041-portable-runtime.md): 25 baseline
  failures under CPython 3.14, zero under 3.11. *"A reproducibility gate is
  only reproducible against the interpreter that produced it."*
- **M-HANDOFF-1** — the count guard I wrote in S002 assumed a deterministic
  test count. That held for exactly as long as the suite had no dynamically
  generated tests. T2's adversarial suite clones its cases per available
  sandbox backend, so the count became a property of the host. It has now
  produced a false red twice: once for a *pinned* backend, fixed in a later
  session, and once for *no* backend at all, which is what greeted me today and
  which I fixed in [`tests/test_records.py`](tests/test_records.py).

A gate whose result depends on the machine it runs on trains people to ignore
gates. That is the opposite of what N8 is for, and I introduced it while
writing N8.

---

## 6. Three suggestions for the next session

**S1 — Close T2. Do not open anything new.**
[T2](docs/trajectories/T2-sandbox.md) has been `IN FLIGHT` since its
2026-08-30 target — 32 days late — with W4 the only waypoint left, externally
blocked on a registered OAuth application and the client-versus-server
profiling decision. That decision is **Q5, open since S001**, it is the user's
to make, and it is one question. Exit criterion 5 cannot be finished without
W4's clone path, so T2 cannot land until it is answered.

Four trajectories are in flight at once (T2, T5, T8, T9) against the flight
board's own rule of one. Either get Q5 answered and finish T2, or mark it
`HOLDING` with the blocker named — the status vocabulary has that word for
exactly this situation, and using it is more honest than leaving it `IN FLIGHT`
while working elsewhere.

**S2 — Make the gates diagnose themselves before trusting N8 again.**
Today's baseline was red on a correct tree, and separating "your tree is
broken" from "your host differs from CI" took four commands. Add a preflight
that prints the interpreter version, the available sandbox backends, and the
expected test count for that combination. Cheap, and it converts a confusing
red into a one-line explanation. `Hand_off.md` §1 already carries this
knowledge as prose; prose is not a gate.

**S3 — Spend a session measuring rather than building.**
Q6 (cross-level op comparability) and Q3 (star thresholds are guesses) have
both been open since S001, both need play data, and neither has any. One
session that plays ten levels and records the score distribution would close
two founding questions and calibrate wordfreq.

The [journal index](journal/README.md) makes the case better than I can: across
the first twenty-three sessions the competency band was one `Analyse`, two
`Evaluate`, and twenty `Create`. The single session that spent its time judging
something already built — S022 — found two blocking bugs. **Before adding a
mechanism, check whether an existing one has an unanswered measurement.**

*Three practical tips, learned the hard way:*
- Run every gate as `python3.11`; the host default is 3.14 and the baselines
  are pinned to 3.11 (M61).
- Redirect the suite to a log and grep it. Piping a 55-second run through
  `tail -4` hides which test failed, which cost me a cycle today.
- Point `VIBECODER_HOME` at a scratch directory for anything that writes
  progress, or you will score against your own profile.

---

## 7. Handoff

- **State:** working tree is current `origin/main` plus two test fixes and this
  file. Both gates green under `python3.11`: 1463 tests (35 skipped, no
  isolating backend on this host), 54/54 reference runs. T1, T3, T4, T6, T7
  `LANDED`; T2, T5, T8, T9 `IN FLIGHT`. This branch was restarted from
  `origin/main` because its earlier pull request was already merged, so any
  pull request opened from it now is a new one.
- **Next action:** get **Q5** answered — does profiling run client-side or
  server-side once GitHub ingestion lands? It is one question to the user, it
  unblocks T2 W4, and T2 W4 is the last thing between T2 and `LANDED`.
- **Blockers:** Q5 (user decision, privacy consequence — do not decide it
  incidentally); a registered OAuth application for T2 W4; no bubblewrap or
  Docker on this host, so the adversarial suite runs narrowed and 35 tests skip.
- **Context required:** [`Hand_off.md`](Hand_off.md) for live orientation,
  before anything else. [`CLAUDE.md`](CLAUDE.md) for the invariants and the
  definition of done. [`docs/SCORING.md`](docs/SCORING.md) before touching any
  weight or curve. §5 above before trusting a baseline or a quoted count.
- **Latest full review:** [S044](journal/2026-09-28-S044-review.md).

No journal entry accompanies this file. The work it reviews is already recorded
as S001 and S002, and this session changed two tests rather than shipping a
waypoint; inventing an S045 to hold a retrospective would put a second record
in `data/` for work that already has one.
