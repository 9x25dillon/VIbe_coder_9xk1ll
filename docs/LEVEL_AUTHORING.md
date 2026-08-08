# Authoring a level

A level is one file in `vibecoder/levels/` exposing a module-level `LEVEL`.
Drop the file in and it is discovered, listed, playable, and covered by the
contract tests. There is no registry to edit.

## Minimum viable level

```python
"""World 3, Level 1 - one line on what this level teaches."""

from __future__ import annotations

import random

from ..models import Level, TestCase


def make_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("empty", [[]], expected=0),          # edge case
        TestCase("single", [[5]], expected=5),        # edge case
    ]
    values = [rng.randint(1, 100) for _ in range(50)] # generated variant
    cases.append(TestCase("random_50", [values], expected=sum(values)))
    return cases


STARTER = '''\
def total(values):
    """Return the sum of values."""
    # Your code here
    return 0
'''

REFERENCE = '''\
def total(values):
    return sum(values)
'''

LEVEL = Level(
    id="w3-l1-total",
    world=3,
    world_title="Your World Name",
    index=1,
    title="Total",
    brief="Return the sum of a list of integers. Empty list returns 0.",
    func_name="total",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=120.0,
    tags=("numeric",),
    style_goals=(),
)
```

## The contract

`tests/test_levels.py` enforces all of this against every level automatically.
A level that violates any of it fails the suite.

| Rule | Why |
| --- | --- |
| `id` is unique and matches `w<world>-l<index>-<slug>` | Ids appear in save files and are cited in journal entries |
| `brief` is longer than 40 characters | A brief that does not explain the task is a bug report waiting to happen |
| Both `starter` and `reference` define `func_name` | Otherwise the harness reports `MissingFunction` |
| The **starter must fail** its own tests | A starter that passes hands out free stars |
| The **reference must pass** every variant | This is the gate that stops a broken level shipping |
| The reference must satisfy the level's own `style_goals` | A goal the reference cannot meet is a goal no player can |
| A seed reproduces its variant exactly | Replays and baselines depend on determinism |
| Different seeds produce different data | Otherwise replayability is cosmetic |
| At least 4 test cases per variant | Fewer makes the accuracy axis too coarse — one failure swings it 25% |
| `tags` is non-empty | Tags drive vibe-based recommendation |

## Test data must be JSON-serialisable

Tests cross a process boundary as JSON, so arguments and expected values must
be JSON types. Two consequences:

- **You cannot pass a custom object into a submission.** Model the input as
  dicts and lists. Every level so far has been natural to express this way.
- **Tuples come back as lists.** The harness normalises tuples to lists, sets to
  sorted lists, and compares floats with `math.isclose`, so a submission
  returning `(1, 2)` matches an expected `[1, 2]`.

## Designing good variants

The generated cases are what make a level replayable, so they carry the weight.

**Always hand-write the edge cases.** Empty input, single element, everything
filtered out, boundary values, a `None` in the data. These are where learners
actually fail, and randomness will not reliably produce them.

**Size at least one variant large enough to matter.** The Functional axis needs
a case where an inefficient solution actually costs something. A 12-element
input cannot distinguish O(n) from O(n²); a 400-element one can. Compare
`w1-l3-join`, whose large case is the entire reason the level exists.

**Keep the shape constant across seeds.** Seed 2 should be the same puzzle with
different data, not a different puzzle. A player who learns the level should not
be ambushed by a variant that changes the rules.

## Choosing a reference solution

The reference sets the bar every player is measured against on the Functional
axis, so it is a difficulty dial, not an afterthought.

**Write the solution a competent Python developer would write** — not the most
clever one available. If your reference does everything in C, a readable
pure-Python solution scores terribly and the level punishes clarity.

This is a live open question. Measured references currently span **76 ops**
(`w2-l3-wordfreq`, which delegates to `re` and `collections.Counter`) to
**5,958 ops** (`w2-l2-window`, pure Python). Op counts are therefore *not*
comparable across levels, and the wordfreq level is unusually harsh. See Q6 in
[S001](../journal/2026-08-08-S001-core-loop.md#open-questions).

## Style goals

Optional constraints that earn the +5% elegance bonus. Declared as a tuple of
checker names from `style.CHECKERS`:

```python
style_goals=("uses_generator_expr",)
```

Available: `uses_comprehension`, `uses_generator_expr`, `no_explicit_loop`,
`uses_enumerate`, `uses_recursion`, `single_return`, `has_type_hints`,
`has_docstring`.

Goals are checked against the target function only, so a helper elsewhere in the
file cannot satisfy one. Use them to teach a specific idiom the level is built
around — not to enforce a house style.

## Setting par time

`par_seconds` is how long a competent player should need. Current levels run
120–360 s. Err generous: the Speed curve gives full marks at or under par and
decays gently, so a slightly loose par costs little, while a tight one makes the
axis feel punitive and teaches nothing.

## Before you commit

```bash
python3 -m vibecoder.cli verify --seeds 5 -v   # references against variants
python3 -m unittest discover -s tests          # the full contract
python3 -m vibecoder.cli play w3-l1-total      # actually play it
```

The third one is not optional. Contract tests confirm a level is *well-formed*;
only playing it tells you whether it is any good.
