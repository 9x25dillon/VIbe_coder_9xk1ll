"""World 1, Level 2 - grouping, and the missing-data edge case that trips people."""

from __future__ import annotations

import random

from ..models import Level, TestCase

REGIONS = ["north", "south", "east", "west"]


def _rows(rng: random.Random, count: int, *, missing: bool = False) -> list[dict]:
    rows = []
    for _ in range(count):
        row = {"region": rng.choice(REGIONS), "amount": rng.randint(1, 500)}
        if missing and rng.random() < 0.3:
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


def make_tests(rng: random.Random) -> list[TestCase]:
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
    for size, missing in ((20, False), (60, True), (300, True)):
        rows = _rows(rng, size, missing=missing)
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
    id="w1-l2-groupby",
    world=1,
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
