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

## Worked example

From the design document, and reproducible today:

```
$ vibecoder play w1-l3-join --solution naive_join.py --seed 1

  accuracy    100.0   ← 5/5 tests pass
  functional   33.1   ← 49,590 ops against a 2,184-op reference
  TOTAL        89.3   [★★☆]
```

The submission is *correct*. It is also doing 22.7× the work. Being told both
things at once is the entire point of the system — and the reason the Functional
axis exists rather than a simple pass/fail.
