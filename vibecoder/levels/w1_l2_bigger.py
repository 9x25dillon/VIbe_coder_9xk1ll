"""World 1, Level 2 - a decision, and the values people forget to try.

Teaches ``if``/``else``. The hand-written cases are negatives and zero, which
are where a beginner's first comparison actually goes wrong -- initialising a
"biggest so far" to ``0`` is the classic version, and this level is where the
habit of trying a negative starts.

Note what ``equal_values`` does and does not prove. Returning either argument
on a tie gives the same number, so it cannot distinguish ``>`` from ``>=``;
it only pins that a tie returns the value rather than ``None`` or a crash.
The tie that genuinely discriminates arrives in level 5, where the answer is a
*position* rather than a value.
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
    hints=(
        "Compare them with > and return the winner. Two returns in one "
        "function is normal - the first one that runs is the one that wins.",
        "Watch the case where they are equal. Whichever branch you take, "
        "the answer is the same number, so you only need to be sure you "
        "return something.",
        "if a > b: return a, then on the next line return b.",
    ),
    par_seconds=120.0,
    tags=("basics", "conditionals"),
)
