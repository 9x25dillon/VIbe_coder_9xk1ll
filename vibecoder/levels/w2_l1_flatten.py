"""World 2, Level 1 - recursion, with the depth cases that break naive attempts."""

from __future__ import annotations

import random

from ..models import Level, TestCase


def _nested(rng: random.Random, depth: int, width: int) -> list:
    if depth <= 0:
        return [rng.randint(0, 99) for _ in range(width)]
    out: list = []
    for _ in range(width):
        if rng.random() < 0.5:
            out.append(_nested(rng, depth - 1, max(1, width - 1)))
        else:
            out.append(rng.randint(0, 99))
    return out


def _expected(value: list) -> list:
    flat: list[int] = []
    for item in value:
        if isinstance(item, list):
            flat.extend(_expected(item))
        else:
            flat.append(item)
    return flat


def make_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("empty", [[]], expected=[]),
        TestCase("already_flat", [[1, 2, 3]], expected=[1, 2, 3]),
        TestCase("empty_nested", [[[], [[]], [[[]]]]], expected=[]),
        TestCase("mixed", [[1, [2, [3, [4]]], 5]], expected=[1, 2, 3, 4, 5]),
    ]
    for depth in (3, 5):
        data = _nested(rng, depth, 4)
        cases.append(TestCase(f"random_depth_{depth}", [data], expected=_expected(data)))
    return cases


STARTER = '''\
def flatten(items):
    """Flatten an arbitrarily nested list of integers into a flat list.

    Order is preserved. Empty sublists contribute nothing.
    Nesting depth is not bounded.
    """
    # Your code here
    return []
'''

REFERENCE = '''\
def flatten(items):
    flat = []
    for item in items:
        if isinstance(item, list):
            flat.extend(flatten(item))
        else:
            flat.append(item)
    return flat
'''

LEVEL = Level(
    id="w2-l1-flatten",
    world=2,
    world_title="Algorithm Architect",
    index=1,
    title="Flatten Anything",
    brief=(
        "Flatten an arbitrarily nested list of integers, preserving order. "
        "The depth is not fixed, so a solution written for two levels of "
        "nesting will fail."
    ),
    func_name="flatten",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=240.0,
    tags=("algorithms", "recursion"),
    style_goals=("uses_recursion",),
)
