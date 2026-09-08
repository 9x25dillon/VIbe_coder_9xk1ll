"""World 2, Level 2 - grouping, and the missing-data edge case that trips people.

The first level to opt in to T4 W2's difficulty parameter, and the one the
trajectory names as the example: gentler variants generate fewer rows with
fewer holes in them, harder ones generate more of both.

**At the default difficulty this level generates exactly what it generated
before the parameter existed.** That is a requirement rather than a nicety --
every recorded op-count baseline was measured there, and a level that shifted
under the default would quietly turn `data/baselines/` from evidence into
decoration. The ends are chosen so the midpoint lands on the old constants,
and the density is scaled as an integer percentage so the midpoint is exact
rather than 0.30000000000000004.
"""

from __future__ import annotations

import random

from ..models import Difficulty, Level, TestCase

REGIONS = ["north", "south", "east", "west"]


def _rows(rng: random.Random, count: int, *, missing: bool = False,
          rate: float = 0.3) -> list[dict]:
    """``count`` rows, ``rate`` of them missing an amount when ``missing``.

    One ``rng.random()`` per row whether or not it is used, so the draw
    sequence depends on the row count alone. Making the call conditional would
    make two variants with the same size but different densities diverge in
    every row after the first hole, for no reason a player could see.
    """
    rows = []
    for _ in range(count):
        row = {"region": rng.choice(REGIONS), "amount": rng.randint(1, 500)}
        if missing and rng.random() < rate:
            row["amount"] = None
        rows.append(row)
    return rows


def _expected(rows: list[dict]) -> dict:
    totals: dict[str, int] = {}
    for row in rows:
        if row["amount"] is None:
            continue
        totals[row["region"]] = totals.get(row["region"], 0) + row["amount"]
    return dict(sorted(totals.items()))


def make_tests(rng: random.Random, difficulty: Difficulty) -> list[TestCase]:
    cases = [
        TestCase("empty", [[]], expected={}),
        TestCase(
            "single_region",
            [[{"region": "north", "amount": 10},
              {"region": "north", "amount": 5}]],
            expected={"north": 15},
        ),
        TestCase(
            "all_amounts_missing",
            [[{"region": "east", "amount": None}]],
            expected={},
        ),
    ]
    # Scaled as whole percent so the midpoint is exactly 0.3, which is what
    # this level used before it opted in.
    rate = difficulty.scale(15, 45) / 100
    sizes = (
        (difficulty.scale(12, 28), False),
        (difficulty.scale(36, 84), True),
        # The big one is what separates a dict accumulation from a repeated
        # scan, so it grows fastest: an easy variant should still be solvable
        # badly, a hard one should not.
        (difficulty.scale(180, 420), True),
    )
    for size, missing in sizes:
        rows = _rows(rng, size, missing=missing, rate=rate)
        label = f"random_{size}{'_sparse' if missing else ''}"
        cases.append(TestCase(label, [rows], expected=_expected(rows)))
    return cases


STARTER = '''\
def totals_by_region(rows):
    """Sum `amount` per `region`, skipping rows where amount is None.

    Return a dict mapping region -> total, with keys in sorted order.
    Regions whose rows are all None must not appear in the result.
    """
    # Your code here
    return {}
'''

REFERENCE = '''\
from collections import defaultdict


def totals_by_region(rows):
    totals = defaultdict(int)
    for row in rows:
        if row["amount"] is not None:
            totals[row["region"]] += row["amount"]
    return dict(sorted(totals.items()))
'''

LEVEL = Level(
    id="w2-l2-groupby",
    world=2,
    world_title="Data Wrangler",
    index=2,
    title="Group and Total",
    brief=(
        "Aggregate a list of row dicts into per-region totals. Rows with a "
        "missing (None) amount are skipped entirely, and a region with no "
        "usable rows must not appear in the output. Return the dict with its "
        "keys in sorted order."
    ),
    func_name="totals_by_region",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=240.0,
    tags=("data", "tabular", "datastructures"),
    style_goals=(),
)
