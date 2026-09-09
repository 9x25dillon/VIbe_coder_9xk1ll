# Hand-off — 2026-09-08

Written for someone with no memory of today. Read this, then
[`CLAUDE.md`](CLAUDE.md) §1. Per-session detail is in [`journal/`](journal/)
S024–S037; this is the short version.

---

## Do this first, before writing any code

```bash
cd /home/kill/VIbe_coder_9xk1ll
python3.11 -m vibecoder.cli profile ~/some-project-you-wrote
python3.11 -m vibecoder.cli status
python3.11 -m vibecoder.cli status --why
python3.11 -m vibecoder.cli daily
python3.11 -m vibecoder.cli play w2-l2-groupby      # twice, and watch the difficulty move
```

**`python3.11`, not `python3`** — the system one is 3.14 (M5 in S003). A real
terminal, not a pipe, for anything with an editor in it.

### Why this is first, and not a nicety

**Thirteen waypoints shipped today and not one has been played by a person.**
Nobody has seen an adapted variant, a function class, an attribute sheet, an
ability, or a daily. That is **Q97**, and it is the largest gap in the project.

The evidence that it matters is in the record. Every finding in T3 that
changed the design came from the front door rather than the suite — an
unplayable fight (S022), a scorecard handing out free points (S024), a boss
no listing named (S025). Today added three of the same shape: a column that
drifts the moment colour is on (M53), a tag played once vanishing overnight
(M55), an empty codebase classified as a Loopwright (M54). All three were
found by *rendering* something, not by asserting about it.

T4's eight exit criteria are all verified. None of that verification involved
a human being.

---

## Where things stand

| | |
| --- | --- |
| Branch | `main`, clean, pushed |
| Gates | **1396 tests unpinned · 1372 pinned to bwrap · `verify` 54/54 · 0 escapes in a pipe** |
| Landed | T1, T3, T4, T6, T7 |
| In flight | **T2** (blocked) and **T5** (being worked) |

| ID | Status | Where it is |
| --- | --- | --- |
| T1 core loop | `LANDED` | — |
| T2 sandbox & ingestion | `IN FLIGHT` | W4 only, **externally blocked** on a registered OAuth application. Untouched since 2026-09-03 — not in flight in any sense involving flying. |
| T3 boss engine | `LANDED` | Two bosses, fights scored at 40/30/30 |
| T4 adaptive difficulty | `LANDED` | Eleven waypoints, all eight criteria, 26 days early |
| T5 community | `IN FLIGHT` | **W1 and W2 landed; W3 is next** |
| T6 presentation | `LANDED` | — |
| T7 interactive | `LANDED` | — |

---

## Three decisions waiting on the user

None has blocked a waypoint yet. **Q100 shapes W3**, so it is the one to ask
about first.

| # | Question | Why it matters |
| --- | --- | --- |
| **Q100** | **Speed cannot be verified by any server.** Wall-clock solve time is unfalsifiable, so a leaderboard ranking on it ranks a claim. T5's own hazard suggests dailies rank on **Accuracy + Functional only**, with Speed as a personal statistic. | Changes what a daily's headline number *means*. A scoring-weight decision, so §12 says ask. **W3 needs it.** |
| **Q89** | The 60–90% success band cannot hold for a player who always writes correct code — a finding against T4's **instrument check**, not its criterion 3 (see M57; I got this wrong first). | Either "success" means something other than "cleared" for a scored game, or the check needs a player who can fail. |
| **Q84** | Is a boss part of world progression, or a side attraction? It banks nothing, appears in no tally, nothing gates it. | T4 landed without needing it. It becomes real when achievements (T5 W7) exist. |

---

## Next: T5 W3, and read the hazards before designing it

Score submission with server-side re-verification — **the first thing in this
project that needs a server**.

- **A client-reported score is a claim, not a fact.** The server must re-run
  the submission, which is where T2's sandbox stops being about profiling
  other people's code and starts being about executing it on our own machine.
- **N1 applies.** A server means `http.server`, not a framework.
- **Criterion 5 is already held and must stay held.** The local board reaches
  for nothing and `daily.py` imports no package — a test asserts it. W3 is an
  **overlay on top of** the local path, never a source it degrades from.

### Do not go near W5 or W6 yet

The hard gate (T2 W1–W3 landed) *is* satisfied, and T5's own hazard says it is
**necessary and not sufficient**. A level is an *importable module*: loading it
runs its body, and `make_tests` is a callable invoked in the **parent** process
on every `tests_for()`. Both bypass `run_code` entirely, so
`Source.THIRD_PARTY` does not cover them. **Sharing a level needs a data format
before it needs a container.** See M12 in S006.

---

## Traps earned today

Eighteen misconceptions (M40–M57). These five generalise:

- **Ask what the empty case scores.** A predicate of the form *"at most X"* is
  satisfied by the empty set, by having never tried. An empty codebase was
  classified as a **Loopwright** on two signals it met by containing nothing.
  (M54 — M1's shape from the opposite direction.)
- **"This costs something" is not "this is bounded."** A cost limits an action
  only if the currency can run out *and* the thing being protected depends on
  it. Abilities priced in the boss's hit points would have been free, because
  HP cannot end a fight and is unspendable past full. (M56.)
- **A number nobody renders is a number nobody has checked.** Twelve decay
  tests passed while a tag played *once* vanished after half a day — every one
  used six observations. Tests are written by whoever wrote the code and
  inherit its blind spots; a display is the first consumer with different
  ones. (M55.)
- **Compute width before colour.** Padding a painted string pads the escape
  codes too, and the whole suite passes because every assertion runs against
  stripped text or a pipe. (M53.)
- **Quote a criterion; never paraphrase your own summary.** Twice today a
  summary drifted — once hiding an unmet criterion (M45), once *inventing* an
  unmeetable one and propagating it through four documents (M57). A summary
  drifts in whichever direction the summariser was worried about.

And one about method: **break your guard on purpose.** W10's losability test
only counts because removing `Refactor`'s cost made seven tests fail. A guard
that cannot fail is not a guard. (M46.)

---

## Architecture, in one breath

| Module | Holds | Imports |
| --- | --- | --- |
| `models.py` | Shapes: `Level`, `BossLevel`, `RunResult`, `ScoreBreakdown`, `Difficulty` | nothing |
| `fight.py` | Boss HP and the repair pool. Arithmetic only | nothing |
| `mastery.py` | Per-tag competency, the update rule, decay | **nothing** |
| `daily.py` | Date → today's challenge; streaks; the local board | **nothing** |
| `timeline.py` | History cursor and `compare` | nothing |
| `abilities.py` | What may spend a fight's resources, what it costs, the class/mastery gate | `fight`, `mastery` |
| `policy.py` | How hard the next variant is, what to drill, and why | `mastery`, `models` |
| `scoring.py` | `score_submission` for a level, `score_fight` for a boss | `models` |
| `profiler.py` | The Vibe Vector, the style signature, the **function class** | `models`, `ingest` |
| `_harness.py` | The child. **Never imports the package** (N2) | — |

The dependency-free modules are so on purpose: their rules are testable
without a sandbox, a child process or a profile on disk.

**T4's two layers meet in exactly one function — `abilities.earned` — and they
meet as a set intersection.** Exit criterion 8, no screen blending habits with
mastery into one number, is held by there being no such number computed
anywhere.

Full map: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Working notes

- **Pin bubblewrap for the inner loop.** `VIBECODER_SANDBOX=bwrap` is ~140 s;
  unpinned is ~230 s because Docker containers are cold. Run unpinned **once**
  before committing (N8), not repeatedly.
- **Update the quoted test counts *before* the final unpinned run.** Three
  files quote them — `README.md`, `CLAUDE.md`, this one — and
  `test_records.py` enforces it. Taking the number from the pinned run and
  editing first saves a redundant full-suite run per session. Not doing that
  today cost roughly forty minutes.
- A single module answers most questions in under a second:
  `python3.11 -m unittest tests.test_mastery`.
- `VIBECODER_HOME=/tmp/somewhere` for anything that writes player state.
- The record system (`journal/` + `data/sessions/`) is mandated by CLAUDE.md
  §8 and enforced by `tests/test_records.py`. Fourteen entries were written
  today and **it is a large share of the output** — if a session is short or
  mostly product work, say so and ask whether to compress it rather than
  silently paying the full cost.
