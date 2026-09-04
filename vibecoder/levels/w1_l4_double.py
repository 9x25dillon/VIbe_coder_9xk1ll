"""World 1, Level 4 - building a new list instead of changing one.

The lesson underneath the task is that the input is left alone and a new list
comes back. This is also where the comprehension is introduced as a style
goal: the player has just written the loop by hand in level 3, so the idiom
lands as a shortening of something they already understand rather than as
syntax to memorise.
"""

from __future__ import annotations

import random

from ..models import Level, TestCase


def _expected(numbers: list[int]) -> list[int]:
    return [n * 2 for n in numbers]


def make_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("simple", [[1, 2, 3]], expected=[2, 4, 6]),
        TestCase("empty_list", [[]], expected=[]),
        TestCase("single_item", [[7]], expected=[14]),
        TestCase("negatives_and_zero", [[-3, 0, 4]], expected=[-6, 0, 8]),
    ]
    small = [rng.randint(-50, 50) for _ in range(12)]
    cases.append(TestCase("random_small", [small], expected=_expected(small)))
    big = [rng.randint(-1000, 1000) for _ in range(500)]
    cases.append(TestCase("random_large", [big], expected=_expected(big)))
    return cases


STARTER = '''\
def double_all(numbers):
    """Return a NEW list with every value doubled.

    The list you are given must not be changed.
    """
    # Your code here
    return []
'''

REFERENCE = '''\
def double_all(numbers):
    return [number * 2 for number in numbers]
'''

LEVEL = Level(
    id="w1-l4-double",
    world=1,
    world_title="First Steps",
    index=4,
    title="Double Everything",
    brief=(
        "Return a new list containing every number from the input doubled, in "
        "the same order. The original list must not be modified. An empty "
        "list gives back an empty list."
    ),
    func_name="double_all",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=240.0,
    tags=("basics", "lists"),
    style_goals=("uses_comprehension",),
)
