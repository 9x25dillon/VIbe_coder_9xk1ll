"""World 1, Level 2 - a decision, and the boundary nobody thinks about.

Teaches ``if``/``else``. The interesting part is the tie: a beginner writes
``>`` without considering equality, and the hand-written equal-values case is
what turns that into a lesson rather than an intermittent mystery.
"""

from __future__ import annotations

import random

from ..models import Level, TestCase


def _expected(a: int, b: int) -> int:
    return a if a >= b else b


def make_tests(rng: random.Random) -> list[TestCase]:
    """Hand-written boundaries first: equal values, negatives, zero."""
    cases = [
        TestCase("first_is_bigger", [9, 4], expected=9),
        TestCase("second_is_bigger", [4, 9], expected=9),
        TestCase("equal_values", [7, 7], expected=7),
        TestCase("negatives", [-9, -4], expected=-4),
        TestCase("zero_and_negative", [0, -3], expected=0),
    ]
    for index in range(4):
        a = rng.randint(-500, 500)
        b = rng.randint(-500, 500)
        cases.append(TestCase(f"random_{index}", [a, b], expected=_expected(a, b)))
    return cases


STARTER = '''\
def larger(a, b):
    """Return whichever of a and b is larger.

    If they are equal, return that value.
    """
    # Your code here
    return 0
'''

REFERENCE = '''\
def larger(a, b):
    if a >= b:
        return a
    return b
'''

LEVEL = Level(
    id="w1-l2-bigger",
    world=1,
    world_title="First Steps",
    index=2,
    title="Pick the Larger",
    brief=(
        "Return whichever of the two numbers is larger. If both numbers are "
        "the same, return that value. The numbers can be negative, and they "
        "can be zero."
    ),
    func_name="larger",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=120.0,
    tags=("basics", "conditionals"),
)
