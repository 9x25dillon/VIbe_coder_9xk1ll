# Scoring

Read this before changing any weight, curve or threshold. Every number below
was chosen for a reason, and the reasons are more load-bearing than the numbers.

## The three axes

Each is computed independently on a 0–100 scale. They measure genuinely
different things and must not be conflated.

| Axis | Measures | Source |
| --- | --- | --- |
| **Accuracy** | Fraction of hidden tests passed | Test outcomes |
| **Speed** | *Human* time from opening the level to the first fully-passing submission | Wall clock, versus the level's par |
| **Functional** | How efficiently the code executes, against the reference solution | Traced op count and peak memory |

The distinction that matters most: **Speed is how long *you* took, not how long
your code took.** Runtime efficiency belongs to the Functional axis. Conflating
them would mean a fast-to-write but slow-running solution scored twice for the
same property.

## Weights

```python
LEVEL_WEIGHTS = Weights(accuracy=0.50, speed=0.25, functional=0.25)
BOSS_WEIGHTS  = Weights(accuracy=0.40, speed=0.30, functional=0.30)
```

Accuracy dominates because a wrong answer is not a solution — no amount of
elegance rescues it. Boss fights shift weight toward speed and efficiency
because by then correctness is assumed and the challenge is execution under
pressure.

`Weights.__post_init__` asserts the three sum to 1.0, so a typo becomes an
exception rather than a silently rescaled score.

## Curves

### Accuracy

```
100 × passed / total
```

Nothing clever. A fatal run (syntax error, missing function, timeout) scores 0.

### Speed — hyperbolic decay past par

```
elapsed ≤ par  →  100
elapsed > par  →  100 × par / elapsed
```

| Time | Score |
| --- | --- |
| At or under par | 100 |
| 2× par | 50 |
| 4× par | 25 |
| 10× par | 10 |

Two properties are deliberate. **Nothing is gained by beating par**, so the
axis never rewards rushing at the expense of the other two. And the curve
**never reaches zero**, so a slow solve is always worth something — a learner
who takes an hour has still learned the thing.

Speed is only awarded once the level is actually solved. An unsolved level
scores 0 here regardless of elapsed time; otherwise opening a level and giving
up quickly would pay.

### Functional — ratio against the reference

```
ops_ratio = min(1, reference_ops / your_ops)
mem_ratio = min(1, reference_peak / your_peak)
score     = 100 × (0.7 × ops_ratio + 0.3 × mem_ratio)
```

Matching the reference is full marks. Beating it is capped rather than rewarded
— that is what bonuses are for — but the cap also protects players against a
reference that happens to be slightly suboptimal.

Ops are weighted above memory (0.7 / 0.3) because line-execution count is the
more stable signal; `tracemalloc` peak is noisy for small workloads.

**A submission with zero accuracy scores zero here, always.** Without that
rule, `def solve(): return None` would score full marks on efficiency.

## Bonuses

Multiplicative on the weighted subtotal:

| Bonus | Rate | Condition |
| --- | --- | --- |
| `first_try` | +10% | All tests passed on submission #1 |
| `elegance` | +5% | Every declared style goal satisfied |
| `clean_first_run` | +5% | Submission #1 had no syntax error or crash |

All three require a full pass. The maximum achievable total is therefore
**120**, not 100 — deliberately uncapped, because capping would make first-try
success worthless to a strong player and invert the incentive it exists to
create.

## Stars

| Stars | Total |
| --- | --- |
| ★☆☆ | ≥ 60 |
| ★★☆ | ≥ 80 |
| ★★★ | ≥ 95 |

These thresholds are **guesses** pending real play data — recorded as open
question Q3 against [T4](trajectories/T4-adaptive.md).

## Practice mode

Scoring a file from disk (`--solution` without `--elapsed`) has no honest solve
time: the clock started moments ago regardless of how long the player actually
worked. Awarding 100 for that is an exploit, and it was a real bug — a naive
O(n·m) solution earned three stars before it was fixed (see
[M1 in S001](../journal/2026-08-08-S001-core-loop.md#m1--scoring-a-file-from-disk-can-reuse-the-interactive-timing-path)).

So practice mode:

1. drops the Speed axis entirely,
2. renormalises accuracy and functional to sum to 1.0, preserving their 2:1
   ratio (0.667 / 0.333), and
3. does **not** bank the result to the profile.

A front-end that genuinely tracks solve time passes `--elapsed <seconds>` and
gets a fully ranked run.

The general principle, worth keeping: **an axis that cannot be measured
honestly must not be scored.** Faking a value is worse than dropping one.

## Global score

```
total = Σ (per-level best × world multiplier)
world multiplier = 1.0 + 0.1 × (world − 1)
```

Recomputed from per-level bests on every save rather than incremented, so
replaying a level badly can never lower a banked total.

A **streak** of consecutive 3-star clears compounds at `1.0 + 0.1 × streak`,
capped at 2.0×. Anything short of 3 stars resets it.

## Boss fights: hit points and repairs (T3 W6)

A fight has two resources on top of the three axes, and their numbers belong
here with the rest. How the fight is *scored* is the section after this one.

| Number | Value | Why |
| --- | --- | --- |
| Starting HP | `100` | Round, so the bar reads as a percentage without anyone being told it is one |
| Per-step damage | `100 / steps`, cumulatively rounded | The damages sum to **exactly** 100, so a flawless fight lands on `0` rather than on `1` |
| Repairs per fight | `5` | Enough to survive a bad step or two, not enough to brute-force three. That band is what makes the pool a decision rather than a formality |
| Damage after a repair | `× 0.5`, compounding | Steep on purpose: a second repair on one step leaves it worth a quarter, which stops "fix it until it passes" scoring like solving it |
| Heal per repair | up to `10%` of starting HP, scaled by `1 − accuracy` | See below. This is the number that carries the mechanic |

### The heal is the mechanic

Spending a repair does two things: it reduces the damage that step will deal,
**and it hands the boss back health scaled by how wrong the code was.**

```
heal = 100 × 0.10 × (1 − accuracy)
```

Accuracy here is the fraction of *that step's own tests* the code passed at the
moment it failed — measured by an ordinary run against the whole set, not by
the single case the player watched execute.

The direction is deliberate and it is the same argument the Functional axis
rests on: **being close is rewarded.**

| What you repaired | Accuracy | Boss recovers |
| --- | --- | --- |
| Nearly right | 90% | 1 |
| Half working | 50% | 5 |
| A guess | 0% | 10 |

A player who ships something almost correct and patches it keeps nearly all of
their damage. A player who repairs a guess watches the bar climb back. Over a
five-repair pool the difference between those two players is roughly half the
boss's health, which is the gap the mechanic exists to create.

### Why repairs do not simply cost HP

Two alternatives were considered and rejected. Making a repair cost *player*
HP adds a fail state to a game where nothing else can beat you. Making the
damage reduction the only cost leaves the pool as a statistic rather than a
resource — and a bounded resource is the thing [T4](trajectories/T4-adaptive.md)
W10's abilities can meaningfully act on.

`BOSS DOWN` is therefore reserved for HP actually reaching zero, which only a
fight with nothing spent can do. Everyone else clears the boss and leaves it
standing, and is told the difference. Clearing and acing are separate
outcomes, which is the same distinction stars draw for an ordinary level.

### `BOSS DOWN` is a mastery ending, not a first-run one (Q80)

This follows from two rules that were written independently and only collide
in a fight. A starter [must fail its own tests](LEVEL_AUTHORING.md), so it
cannot hand out a free step; and every failure costs a repair, which halves
that step's damage. Both are right on their own. Together they put zero out of
reach of anyone playing from the starters.

The floor was measured rather than argued, on `w1-boss-pipeline`:

| Step | Starter accuracy | Heal | Damage | HP |
| --- | --- | --- | --- | --- |
| `parse` | 50% (3/6) | +5 | −16 | 89 |
| `filter` | 83% (5/6) | +2 | −17 | 74 |
| `summary` | 33% (2/6) | +7 | −16 | **65** |

The heal is *not* what puts zero out of reach — it costs 14 of the missing 35.
The compounding damage halving costs the other 51. So making the first repair
free of its heal would move the floor to 51 and change nothing about
reachability; only a repair that costs literally nothing reaches zero, and
that makes the flawless ending the *default* outcome rather than the rare one.

The resolution is to leave the mechanic alone and be honest about what the
ending is for: **`BOSS DOWN` is what you come back for.** You reach it by
returning with a solution that passes every step first time, which is the same
shape as replaying a level for a third star. A first run is graded by the
scorecard below, not by whether it reached an ending it could not reach.

## Boss fights: the scorecard (T3 W7)

A fight is scored on the same three axes as a level, at `BOSS_WEIGHTS`
(40/30/30), and shown in the same layout — a player should not have to learn a
second card to read one. Four things differ, and each has a reason.

**Accuracy is pooled across every step's cases**, not averaged per step. That
keeps the axis to the one definition it has everywhere else — the fraction of
hidden tests passed. Averaging percentages would let a step with four cases
weigh as much as one with forty, which is a second definition wearing the same
name.

**Functional is averaged per step, and a step that passed nothing scores
zero.** This is the opposite choice, and it is not an inconsistency: each step
has its own reference, so the comparison is per step by construction. Pooling
ops across the fight was tried first and was wrong in a way worth recording. A
fight abandoned on step one never defines the later functions, so they execute
nothing; against the reference's total that reads as *less work*, the ratio
caps at 1.0, and the scorecard printed a confident **100.0 on Functional for a
fight that had achieved almost nothing.** Free points on an axis measuring work
never done — M1's shape, caught by running the front door rather than by the
arithmetic.

**Speed excludes the engine's own slow motion.** A live fight's wall clock is
mostly the engine deliberately waiting between lines so the run can be watched.
Counting it would score a display setting: the same fight played identically at
`--speed 0.1` and `--speed 2.0` would earn different marks. The engine measures
what it slept and subtracts it, leaving the time the player was actually in
control — reading the trace, and typing in the repair pane. A fight with no
honest clock at all (checking a file rather than playing) drops the axis and
renormalises, exactly as practice mode does, and reports `speed = 0.0` rather
than a value nothing measured.

**Hit points are not an input to the score.** HP and repairs already price how
wrong the code was, through the heal curve. Feeding them into the score as well
would score one property twice, which is the mistake the three axes exist to
avoid. The pool reaches the score once, through the `first_try` bonus — which
for a fight means every step cleared with nothing spent. The bar is reported
beside the score, not folded into it.

Bonuses are the level's three, read for a fight: `first_try` (no repair spent),
`elegance` (every step's declared style goals met), and `clean_first_run` (no
step's opening attempt died with a fatal error, as opposed to merely answering
wrongly).

## Worked example

From the design document, and reproducible today:

```
$ vibecoder play w2-l3-join --solution naive_join.py --seed 1

  accuracy    100.0   ← 5/5 tests pass
  functional   33.1   ← 49,590 ops against a 2,184-op reference
  TOTAL        89.3   [★★☆]
```

The submission is *correct*. It is also doing 22.7× the work. Being told both
things at once is the entire point of the system — and the reason the Functional
axis exists rather than a simple pass/fail.
