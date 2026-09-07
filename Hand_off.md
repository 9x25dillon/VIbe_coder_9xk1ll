# Hand-off — 2026-09-06

Written for someone with no memory of today. Read this, then
[`CLAUDE.md`](CLAUDE.md) §1. Per-session detail is in
[`journal/`](journal/) S019–S023; this is the short version.

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

**T3 (boss engine) is one waypoint from its exit criteria.** W1–W6 landed;
criteria 1–5 verified. W7 (boss scoring at 40/30/30) is the only thing left
before the criteria are met. `BOSS_WEIGHTS` has been defined and unused since
T3 was written.

| | |
| --- | --- |
| Branch | `main`, clean, pushed |
| Gates | 988 tests unpinned · 964 pinned to bwrap · `verify` 45/45 · 0 escapes in a pipe |
| Blocked | T2 W4 only, on a registered OAuth application |

Three trajectories hold `IN FLIGHT` against a rule saying exactly one should.
That is recorded on the flight board, not hidden.

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

## Decide these before writing W7

Scoring a fight whose best outcome is unreachable would bake the problem in.
All three are the user's call, not yours.

| # | Question |
| --- | --- |
| **Q80** | **`BOSS DOWN` is unreachable from the starters.** A starter must fail its own tests, and every failure costs a repair — so the flawless ending exists and normal play cannot get there. Options: the boss contract diverges from the level contract; the first repair is free; or `BOSS DOWN` simply is not for a first attempt. |
| **Q76** | The heal curve (10% ceiling) and the pool size (5) were chosen by argument, never playtested. What observation would say five is wrong? |
| **Q77** | W8 (a second boss fight) is a waypoint no exit criterion points at. Does T3 land without it, or does the criteria list have a gap? |

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

---

## Architecture, in one breath

| Module | Holds |
| --- | --- |
| `runner.py` | `LiveRun` — drives a child one line at a time; `edit()` is strategy A |
| `timeline.py` | History cursor **and** `compare` — pure, imports nothing |
| `repair.py` | The pane a player types a fix into. Reuses the T7 editor's `Buffer`/`KeyDecoder`/`KEYMAP`, but **not** `Editor` |
| `fight.py` | HP and the repair pool. Arithmetic only |
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
