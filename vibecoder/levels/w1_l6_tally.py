"""World 1, Level 6 - the dictionary, and the bridge into World 2.

Counting into a dict is the last thing a beginner needs before World 2's data
work, which assumes dicts throughout. The level exists to make the "have I
seen this key before?" question explicit, because that is the step where
``dict.get(key, 0)`` stops being syntax and starts being useful.
"""

from __future__ import annotations

import random

from ..models import Level, TestCase

FRUIT = ["apple", "pear", "plum", "fig", "cherry", "peach"]


def _expected(items: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts


def make_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("repeats", [["a", "b", "a"]], expected={"a": 2, "b": 1}),
        TestCase("empty_list", [[]], expected={}),
        TestCase("all_unique", [["x", "y", "z"]], expected={"x": 1, "y": 1, "z": 1}),
        TestCase("all_the_same", [["q", "q", "q", "q"]], expected={"q": 4}),
    ]
    for index in range(3):
        picked = [rng.choice(FRUIT) for _ in range(rng.randint(5, 14))]
        cases.append(
            TestCase(f"random_{index}", [picked], expected=_expected(picked))
        )
    big = [rng.choice(FRUIT) for _ in range(500)]
    cases.append(TestCase("random_large", [big], expected=_expected(big)))
    return cases


STARTER = '''\
def tally(items):
    """Count how many times each item appears.

    Return a dict mapping each item to its count, for example:
        ["a", "b", "a"]  ->  {"a": 2, "b": 1}
    """
    # Your code here. dict.get(key, 0) is worth looking up.
    return {}
'''

REFERENCE = '''\
def tally(items):
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts
'''

LEVEL = Level(
    id="w1-l6-tally",
    world=1,
    world_title="First Steps",
    index=6,
    title="Count Each One",
    brief=(
        "Count how many times each item appears in the list and return a dict "
        "mapping each item to its count. An empty list gives an empty dict. "
        "Items that appear once still belong in the result, with a count of 1."
    ),
    func_name="tally",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    hints=(
        "Start with an empty dict. For each item, you need to ask whether "
        "you have seen it before.",
        "counts.get(item, 0) gives you the count so far, or 0 if this is "
        "the first time - so you never have to check separately.",
        "The whole body is: counts[item] = counts.get(item, 0) + 1, "
        "inside the loop.",
    ),
    par_seconds=360.0,
    tags=("basics", "datastructures"),
)
