# Hand-off — 2026-09-08

Written for someone with no memory of today. Read this, then
[`CLAUDE.md`](CLAUDE.md) §1. Per-session detail is in
[`journal/`](journal/) S019–S024; this is the short version.

---

## Run it first

```bash
cd /home/kill/VIbe_coder_9xk1ll && python3.11 -m vibecoder.cli boss w1-boss-pipeline --live
```

**`python3.11`, not `python3`** — the system one is 3.14 (M5 in S003). A real
terminal, not a pipe, or the repair editor never opens. No install, no
dependencies, no setup: verified from an empty `VIBECODER_HOME`.

Do this **before** reading further. Today's two worst bugs were both invisible
from the test suite and obvious within ninety seconds of playing (M38).

---

## Where things stand

**T3 (boss engine) is `LANDED`** as of 2026-09-08, twelve days inside its
target. W1–W8 shipped and all six exit criteria have evidence. There are two
boss fights: `w1-boss-pipeline` (a pipeline — parse, filter, report) and
`w2-boss-ledger` (a chain — index, aggregate, rank, each step calling the one
before it).

Building the second one found what six criteria could not: **bosses appeared
in no listing**, so the only way to reach one was to already know its id.
`vibecoder levels` and `levels --map` now name both and print the command.

| | |
| --- | --- |
| Branch | `main`, clean, pushed |
| Gates | 1281 tests unpinned · 1257 pinned to bwrap · `verify` 54/54 · 0 escapes in a pipe |
| Blocked | T2 W4 only, on a registered OAuth application |

**One** trajectory holds `IN FLIGHT`, which is what the rule says: T2, late
and blocked on W4 rather than being worked. T7 landed on 2026-09-08 — and
landing it was *not* the bookkeeping the previous hand-off (this document,
one session ago) called it. Two of its nine criteria had no evidence and one
was false. See M45.

---

## What a boss fight is now

Your code runs one line at a time in a real interpreter. When a step fails —
**by crashing *or* by answering wrongly**, both matter — the run pauses and an
editor opens on the offending line. You fix it and the fight carries on.

The fight costs something:

- The boss has **100 HP**. Per-step damages sum to exactly 100, so a flawless
  fight lands on 0. That exactness is what exit criterion 5 rests on.
- You have **5 repairs**. Spending one halves that step's damage, and **heals
  the boss by `10% × (1 − accuracy)`** — so patching nearly-right code costs
  almost nothing and repairing a guess hands back 10.
- `BOSS DOWN` means HP actually reached 0. `BOSS SURVIVES` means you cleared
  every step and it is still standing. Both exit 0.

Numbers and reasoning: [`SCORING.md`](docs/SCORING.md#boss-fights-hit-points-and-repairs-t3-w6).
Player's view: [`docs/PLAYING.md`](docs/PLAYING.md).

---

## How a fight is scored (T3 W7, shipped)

A fight ends with a scorecard in the same layout a level uses, at
`BOSS_WEIGHTS` (40/30/30). Four things differ from a level, each for a reason
written down in [`SCORING.md`](docs/SCORING.md#boss-fights-the-scorecard-t3-w7):

- **Accuracy is pooled** across every step's cases; **Functional is averaged
  per step**, and a step that passed nothing scores zero. That asymmetry is
  not sloppiness — pooling ops produced a fight that scored **100.0 on
  Functional having achieved almost nothing** (M40).
- **Speed excludes the engine's own slow motion.** Otherwise `--speed 0.1`
  and `--speed 2.0` score identical play differently.
- **Hit points are not an input.** The heal curve already prices how wrong the
  code was; scoring it again would score one property twice.

## Still open, and still the user's call

| # | Question |
| --- | --- |
| **Q76** | The heal curve (10% ceiling) and the pool size (5) were chosen by argument, never playtested. Every number on the new scorecard joins them. What observation would say five is wrong? |
| **Q81** | `score_submission` banks a computed `speed` for practice runs, from a clock that started when the file was read. The UI hides it; the stored record does not. `score_fight` was written not to. Should the level path match, and what about already-banked runs? |
| **Q82** | The score cannot see how wrong the code was *before* repair — a cleared fight is 100% accurate whether patched from 90% or from a guess. Only HP distinguishes them. Is side-by-side enough? |

**Q80 is answered.** `BOSS DOWN` is unreachable from the starters and that is
now the design: it is a mastery ending, reached by coming back with a solution
that passes every step first time. The floor was *measured* at exactly 65, and
that measurement changed the question — the heal costs only 14 of the missing
35 HP, the compounding damage halving costs the other 51. So every "make the
first repair cheaper" option was a dial, not an answer.

---

## Traps, earned today

- **Do not verify against a fixture and call it verified.** Three sessions
  shipped "verified" work using `--solution broken.py`, a file written for the
  purpose, whose bug was a crash. The starter fails by *answering wrongly*,
  which is how most code fails, and that path had no repair at all. Run the
  front door. (M38 — and it is M1's shape for the third time.)
- **Do not trust an invariant that has no test.** `docs/UI.md` and `CLAUDE.md`
  both said `ui.py` was the only module emitting an escape sequence. It had
  been false since T7 shipped. (M36. Q75 asks which other prose rules can be
  given a test; three were added today.)
- **Measure a number before writing it down.** Test counts, trace lengths,
  bar counts — each guessed one cost a red run. (M37.)
- **Do not pin level text in a test.** A test asserting `"return []"` broke
  the session after it was written, for a change the user asked for. Assert
  the property. (M39.)
- **Free points on an axis have now happened five times.** Every one was found
  by reading what a *bad* run printed, never by the suite — a test written by
  whoever wrote the bug asserts the same wrong thing. (M40, and M1's shape
  again.)
- **`redirect_stdout` does not capture a scorecard.** `UI` binds `sys.stdout`
  at import, so it catches the prints and misses every gauge. Use
  `everything_printed()` in `test_cli_output.py`. (M42.)
- **Read the criteria, not the board.** Two trajectories in two sessions had
  criteria recorded as met that nobody had checked — a boss no listing named,
  and a visualiser that animated when told not to. Both checks took minutes;
  both beliefs had stood for weeks. (M43, M45.)
- **An assertion of absence passes hardest when the feature is gone.** Any
  test of the form "X does not happen" needs a sibling proving X is still
  reachable. (M46.)

---

## Architecture, in one breath

| Module | Holds |
| --- | --- |
| `runner.py` | `LiveRun` — drives a child one line at a time; `edit()` is strategy A |
| `timeline.py` | History cursor **and** `compare` — pure, imports nothing |
| `repair.py` | The pane a player types a fix into. Reuses the T7 editor's `Buffer`/`KeyDecoder`/`KEYMAP`, but **not** `Editor` |
| `fight.py` | HP and the repair pool. Arithmetic only |
| `scoring.py` | `score_submission` for a level, `score_fight` for a boss. Depends on `models.py` and nothing else |
| `_harness.py` | The child. **Never imports the package** (N2) |

The child blocks while a player thinks, and its budget counts executing time
only — which is what makes opening an editor at a pause point safe.

Full map: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Working notes

- The unpinned suite takes ~80s; pinned to bwrap ~55s. Use
  `VIBECODER_SANDBOX=bwrap` for the inner loop, unpinned before a commit (N8).
- A single module (`python3.11 -m unittest tests.test_fight`) answers most
  questions in under a second. Reach for that first.
- The record system (`journal/` + `data/sessions/`) is mandated by CLAUDE.md
  §8 and `tests/test_records.py` enforces it. **The user has flagged that it
  consumes a disproportionate share of output.** If a session is short or
  mostly product work, say so and ask whether to compress it rather than
  silently paying the full cost.
