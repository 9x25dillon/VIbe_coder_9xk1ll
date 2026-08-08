"""World 2, Level 2 - sliding window. O(n*k) passes; O(n) is the point."""

from __future__ import annotations

import random

from ..models import Level, TestCase


def _expected(values: list[int], k: int) -> int:
    if k <= 0 or k > len(values):
        return 0
    window = sum(values[:k])
    best = window
    for i in range(k, len(values)):
        window += values[i] - values[i - k]
        best = max(best, window)
    return best


def make_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("window_larger_than_input", [[1, 2], 5], expected=0),
        TestCase("zero_window", [[1, 2, 3], 0], expected=0),
        TestCase("whole_list", [[1, 2, 3], 3], expected=6),
        TestCase("all_negative", [[-5, -2, -9, -1], 2], expected=-7),
    ]
    for size, k in ((30, 4), (2000, 50)):
        values = [rng.randint(-100, 100) for _ in range(size)]
        cases.append(
            TestCase(f"random_{size}_k{k}", [values, k], expected=_expected(values, k))
        )
    return cases


STARTER = '''\
def max_window_sum(values, k):
    """Return the largest sum of any k consecutive values.

    Return 0 when k is 0, negative, or larger than the list.
    Values may be negative, so the answer may be negative too.
    """
    # Your code here
    return 0
'''

REFERENCE = '''\
def max_window_sum(values, k):
    if k <= 0 or k > len(values):
        return 0
    window = sum(values[:k])
    best = window
    for i in range(k, len(values)):
        window += values[i] - values[i - k]
        best = max(best, window)
    return best
'''

LEVEL = Level(
    id="w2-l2-window",
    world=2,
    world_title="Algorithm Architect",
    index=2,
    title="Sliding Window",
    brief=(
        "Find the largest sum of k consecutive values. Recomputing each window "
        "from scratch is O(n*k) and will pass the tests; sliding the window is "
        "O(n) and is what the Functional axis rewards. Mind the empty and "
        "all-negative cases."
    ),
    func_name="max_window_sum",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=300.0,
    tags=("algorithms", "numeric"),
    style_goals=(),
)
