# S028 — The selection policy, and the band that cannot hold

**Date:** 2026-09-08 · **Duration:** 01:15 · **Trajectory:** T4 ·
**Competency band:** `Evaluate` ·
**Data:** [`data/sessions/2026-09-08-S028.json`](../data/sessions/2026-09-08-S028.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A player's profile chooses how hard their next variant is | ✅ met |
| 2 | Every choice comes with the sentence that explains it, produced together | ✅ met |
| 3 | The 70–80% success band is measured, not asserted | ✅ met — 72% and 71% |
| 4 | The band is measured for all four simulated players the instrument check names | ⚠️ partial — two of four **cannot** be held, structurally (Q89) |
| 5 | The loop closes at the front door, not only in the simulation | ✅ met |

## What was built

**[`policy.py`](../vibecoder/policy.py)** turns a profile into a `Decision`: a
`Difficulty`, the source it came from, a one-sentence reason, and the numbers
that sentence was built from.

The reason is produced *with* the decision rather than after it. Exit
criterion 4 requires every choice to be explainable "with no hidden state",
and a policy that computes a number and has an explanation retrofitted has
exactly that — two code paths that can disagree, one of which the player sees.

### A tension inside T4, resolved by naming the source

The tag-sparsity hazard says to fall back to the Vibe Vector until a tag has
enough observations. The very next hazard says confusing "what you write" with
"what you are good at" is the most tempting and most wrong simplification
available. Both are right.

The resolution is that the two sources are used **one at a time and always
named**. Mastery whenever the level's tags have evidence; habits only as a
bounded prior (±0.15, so a wrong guess can never reach an extreme) when
nothing has been measured, and reported as coming from your code rather than
your scores. The moment mastery has evidence it wins outright — habits are
what we guess with before measuring, not a term averaged in forever. The
player is never shown a blend (criterion 8); they are shown which source was
used.

### The loop closes at the front door

Four clears of `w2-l2-groupby` raised mastery to 0.916, and the fifth run
opened with:

```
  [HARD] you have played data, datastructures, tabular enough for a read:
         you average 88% there, so this variant is hard
```

`reference_benchmark` went from 1042 ops to 1247 for the same level, because
it now takes the difficulty and it is part of the cache key. Benchmarking the
reference at the default while the player runs a hard variant would divide
their ops by a denominator from a smaller input, and the Functional axis would
punish them for a size the game chose.

## Evidence

Measured over 20 seeds × 50 simulated runs each, with the real `observation`,
the real `Mastery.observe` and the real policy — only the player is simulated.

| Simulated player | Success | In band (40 seeds) |
| --- | --- | --- |
| Improving | **72%** | 40/40 |
| Plateaued | **71%** | 38/40 |
| Always-correct | **100%** | 0/40 |
| Always-naive | **100%** | 0/40 |

```
STRETCH sweep, pooled over 40 seeds x 50 runs:
  0.00  ->  improving 70%   plateaued 70%
  0.10  ->  improving 72%   plateaued 71%     <- shipped
  0.30  ->  improving 74%   plateaued 74%
```

```
$ python3.11 -m unittest discover -s tests
Ran 1165 tests in 84.182s — OK

$ VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests
Ran 1141 tests in 67.461s — OK (skipped=6)

$ python3.11 -m vibecoder.cli verify --seeds 3
54/54 reference runs clean
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| Criterion 1: opposite profiles get measurably different variants on the same level id | `TestTwoPlayersGetDifferentVariants`, counting rows out of `tests_for` rather than the number the policy chose — a >100-row gap | verified |
| Criterion 3, for an improving player | pooled 72% over 20×50; 40/40 seeds inside 60–90% | verified |
| Criterion 3, for a plateaued player | pooled 71%; 38/40 seeds inside | verified |
| Criterion 3 **cannot** hold for always-correct or always-naive, because a correct solution passes at every difficulty | 100% success at every one of 40 seeds, for both | verified — the finding, not the criterion (M50) |
| Criterion 4: every decision explainable in one sentence, no hidden state | `TestTheDecisionNamesItsSource`, 7 cases; the reason and the number are built together | verified |
| A stronger player gets a harder variant | `test_a_stronger_player_gets_a_harder_variant` | verified |
| Only the level's own tags are read | `test_only_the_levels_own_tags_are_read` — being strong at `data` earns nothing on a `recursion` level | verified |
| Habits can never reach an extreme | `test_habits_can_never_reach_an_extreme`, bounded at ±0.15 | verified |
| A plateaued player settles rather than oscillating | span 0.084 over the last ten and the same over runs 20–30, so stationary noise rather than a growing spread; drift < 0.05 | verified |
| An improving player keeps being given harder work | the paired negative: mean drift +0.25 | verified |
| The reference is benchmarked on the same variant the player runs | `test_the_reference_is_benchmarked_on_the_same_variant`, plus `test_the_benchmark_cache_is_keyed_by_difficulty` | verified |
| The loop closes end to end | five real `play` runs from an empty `VIBECODER_HOME`: mastery 0.916, variant labelled HARD, benchmark 1042 → 1247 ops | verified |
| Whether 72% *feels* right to a person | nobody has played an adapted variant | `UNVERIFIED` |
| Whether the simulated players resemble real ones | they are a model, chosen from the instrument check's four names | `UNVERIFIED` |

## Misconceptions and corrections

### M49 — the offset was not the dial

**Believed:** That `STRETCH` — how far below their mastery a player's
difficulty sits — was the parameter that controlled the success rate, and
would need tuning to land the band. I wrote it with a comment calling it "the
dial to turn if the simulated band comes out wrong".

**Revealed by:** Sweeping it, because writing that comment obliged me to check
it. Success moves from **70% at zero offset to 74% at three times the shipped
value** — nearly flat across the whole plausible range.

**Corrected to:** The loop is self-correcting. Lowering difficulty raises the
observed result, which raises mastery, which raises difficulty back; the
offset cancels itself out. **The equilibrium success rate is set by the
observation weights in `mastery.py`** — accuracy 0.5, functional 0.3,
first-try 0.2 — not by anything in the policy. Anyone trying to move the band
should turn those, and `STRETCH` expresses an intent rather than controlling
an outcome. The module and the trajectory now both say so.

**Cost:** ~5 minutes, and it turned a comment that would have misled the next
session into a documented property.

**Generalisable:** In a feedback loop, a parameter's local effect is not its
effect. I reasoned about `STRETCH` one step at a time — lower difficulty,
higher success — and stopped before the step where mastery follows difficulty
back up. Sweeping a parameter is cheap; predicting it is where the error is.

### M50 — a band no policy can hold, and a simulation that nearly hid it

**Believed:** That the 60–90% success band could be met for all four simulated
players, and that failing to would mean the policy needed work.

**Revealed by:** Measuring. Always-correct and always-naive succeed **100% of
the time at every seed**, and no difficulty policy can change that — because
W2's dial scales *how much work an input demands*, not whether the answer is
right. That is the design, deliberately: it is why a level's hand-written edge
cases survive every difficulty. A correct solution passes at every input size,
so a player who always writes one is unreachable. "Naive" here means O(n²) and
**right** (M1 in [S001](2026-08-08-S001-core-loop.md), where a naive solution
scored 95.8), so it lands in the same place.

**Corrected to:** Criterion 3 is met for the two players who can fail and is
structurally unmeetable for the two who cannot. N7 forbids re-cutting a
criterion to match what was built, so it stands as written and this is the
finding against it (Q89). The policy is not idle for those players: the naive
one's low Functional score drags their mastery down and they settle at 0.61
against the ace's 0.90 — but being correct first time weighs 0.7 of the
observation, so mastery cannot fall below that floor however inefficient the
code is.

**The near-miss is the part worth recording.** My first simulation used
`cleared = reach >= 0.5`, a step function chosen to avoid seed dependence. It
made *every* player succeed 100%, including the plateaued one, which would
have looked like the same structural finding and was not — it was my model
being wrong. Two modelling errors, both found by asking why a number looked
odd rather than by a test:

- A threshold instead of a sample turns "70% likely to pass" into "always
  passes", which is exactly the signal the band measures.
- Functional scored as `efficiency × (1 − 0.3·difficulty)` penalised a
  *perfect* player at high difficulty. The real axis is measured against the
  reference running the **same** variant, so a perfect solution scores 100 at
  any size. Using `efficiency ** (1 + difficulty)` gives both axes the
  property their real counterparts have.

**Cost:** ~20 minutes, and it would have produced a confident, wrong finding
about the exit criterion.

**Generalisable:** A simulation is a model, and a model that produces a
striking result is the one to distrust first. The discipline that saved this
was that the simulated player's latent skill is invisible to the policy — but
that only stops the *policy* from cheating. Nothing stops the *model* from
being wrong, and the check for that is whether each of its terms has the
property the real thing has.

## Friction

`none` — the two findings both came from measuring things I had written down
as assumptions, which is the cheap direction.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D181 | The reason is produced with the decision, in the same object | Generate explanations in W7 from the stored numbers | Criterion 4 says "no hidden state". Two code paths that can disagree, one of which the player sees, is exactly that. | Yes |
| D182 | Mastery and habits are used one at a time and always named, never blended | Weighted average of the two, falling off as observations accumulate | The blend is what criterion 8 forbids and what T4's third hazard calls the most tempting wrong simplification. Naming the source lets the player judge the guess. | Yes |
| D183 | The habits prior is bounded at ±0.15 | Let familiarity drive the full range | Habits are a guess about performance, not a measurement of it. The worst a wrong prior may do is hand someone a slightly roomier or tighter first run. | Yes |
| D184 | `reference_benchmark` takes the difficulty, and it is in the cache key | Benchmark at the default and compare | Otherwise the Functional axis divides a player's ops by a denominator measured on a smaller input, and punishes them for a size the game chose. | No — it would be a scoring bug |
| D185 | The band is asserted pooled over 20 seeds, not on one run | Assert a single 50-run at a fixed seed | A single run has a standard error of ~6 points and sits two points from the band edge. That test passes today and fails on a Tuesday. | Yes |
| D186 | Criterion 3 stands as written, with the finding recorded against it | Re-cut it to "players who can fail"; drop the two players from the instrument check | N7. An exit criterion edited to match what was built destroys the only honest signal a trajectory has. | No — it is a record |

## Handoff

- **State:** T4 W1–W4 `LANDED`. A player's profile now chooses their variant's
  difficulty, with the reason attached, and the reference is benchmarked on
  the same variant. Exit criteria **1, 2, 4 and 5 are verified**; **3 is
  verified for the two simulated players who can fail and is structurally
  unmeetable for the two who cannot** (Q89). 1165 tests green unpinned, 1141
  pinned, `verify` clean on 54 reference runs.
- **⚠ Use Python 3.11 on this machine** — see M5 in S003. Unchanged.
- **Next action: T4 W5**, drill injection on the weakest tag. It is also the
  intended answer to Q88 — three tags have exactly one level each and can
  never reach the confidence threshold from ordinary play, so drills are what
  would give them evidence.
- **Blockers:** none for T4. T2 W4 remains blocked on a registered OAuth
  application.
- **Context required:** **M49 before tuning anything in this loop** — a
  parameter's local effect is not its effect, and the observation weights are
  what actually set the band. **M50 before trusting a simulation** — check
  each term has the property the real thing has. D184 before touching the
  benchmark. Q84 is still open and still the user's call, though it did not
  block W4: a boss carries tags and banks nothing.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q68 | Two events land on one line when it raises. Should the display merge them? | T3 | open |
| Q69 | `Timeline` holds `Step` objects for a live run and dicts for a recorded one | T3 | open |
| Q70 | An edit past step 400 fast-forwards against a truncated original | T3 | open |
| Q71 | Divergence rate over real play is measurable and uncollected | T3 | open |
| Q73 | Should the crash path show the expected value? | T3 | open |
| Q75 | Which of the remaining non-negotiables can be given a test? | T6 | open |
| Q76 | The heal curve and pool size were chosen by argument, not playtest | T3 | open |
| Q78 | Should the pane have a "replace this function" affordance? | T3 | open |
| Q81 | `score_submission` stores a computed `speed` for practice runs | T1 | open |
| Q82 | The score cannot see how wrong the code was before it was repaired | T3 | open |
| Q83 | Should "a starter fails the case the player watches" be a test? | T3 | open |
| Q84 | Is a boss part of world progression, or a side attraction? | T4 | open — did not block W4; still the user's call |
| Q85 | Nothing drives the whole editor through a pty | T7 | open |
| Q86 | No frame-timing histogram is recorded per session | T7 | open |
| Q87 | A level's tags all receive the same observation | T4 | open |
| Q88 | Three tags have exactly one level each and can never become confident | T4 | open — **W5 is the intended answer** |
| Q89 | **Exit criterion 3's band cannot hold for a player who always writes correct code.** W2's difficulty scales work, not correctness, so a correct solution passes at every size — by design. Either "success" means something other than "cleared" for a scored game (3 stars? a score threshold?), or the criterion needs a player who can actually fail. Which? | T4 | open — the user's call |
