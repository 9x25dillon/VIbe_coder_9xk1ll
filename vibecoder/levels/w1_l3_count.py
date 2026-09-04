"""World 1, Level 3 - a loop, a condition and a counter.

The first level where something is repeated. It is also the first with a large
variant, so that a solution doing needless work inside the loop has somewhere
to show up on the Functional axis.
"""

from __future__ import annotations

import random

from ..models import Level, TestCase


def _expected(numbers: list[int], limit: int) -> int:
    return sum(1 for n in numbers if n > limit)


def make_tests(rng: random.Random) -> list[TestCase]:
    """The empty list and the all/none cases will not appear by chance."""
    cases = [
        TestCase("mixed", [[1, 5, 9, 12], 5], expected=2),
        TestCase("empty_list", [[], 5], expected=0),
        TestCase("none_above", [[1, 2, 3], 10], expected=0),
        TestCase("all_above", [[11, 12, 13], 10], expected=3),
        TestCase("equal_is_not_above", [[5, 5, 5], 5], expected=0),
    ]
    small = [rng.randint(0, 40) for _ in range(15)]
    cases.append(TestCase("random_small", [small, 20], expected=_expected(small, 20)))
    # Large enough that wasted work inside the loop is measurable.
    big = [rng.randint(0, 1000) for _ in range(600)]
    cases.append(TestCase("random_large", [big, 500], expected=_expected(big, 500)))
    return cases


STARTER = '''\
def count_above(numbers, limit):
    """Return how many values in numbers are greater than limit.

    "Greater than" is strict: a value equal to limit does not count.
    """
    # Your code here. A counter starting at 0 and a for loop will do it.
    return 0
'''

REFERENCE = '''\
def count_above(numbers, limit):
    count = 0
    for number in numbers:
        if number > limit:
            count += 1
    return count
'''

LEVEL = Level(
    id="w1-l3-count",
    world=1,
    world_title="First Steps",
    index=3,
    title="Count What Matters",
    brief=(
        "Return how many numbers in the list are greater than the limit. "
        "Greater than is strict, so a value exactly equal to the limit does "
        "not count. An empty list has nothing above the limit."
    ),
    func_name="count_above",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=240.0,
    tags=("basics", "loops"),
)
