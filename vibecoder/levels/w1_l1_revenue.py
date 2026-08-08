"""World 1, Level 1 - the doc's worked example, made playable."""

from __future__ import annotations

import random

from ..models import Level, TestCase

PRODUCTS = [
    "widget", "sprocket", "gasket", "flange", "bracket",
    "coupler", "bearing", "washer", "grommet", "shim",
]


def _sales(rng: random.Random, count: int) -> list[dict]:
    return [
        {
            "product": rng.choice(PRODUCTS),
            "price": round(rng.uniform(1.0, 60.0), 2),
            "quantity": rng.randint(1, 12),
        }
        for _ in range(count)
    ]


def _expected(sales: list[dict], threshold: float) -> float:
    return round(
        sum(s["price"] * s["quantity"] for s in sales if s["price"] > threshold), 2
    )


def make_tests(rng: random.Random) -> list[TestCase]:
    cases: list[TestCase] = []

    fixed = [
        {"product": "widget", "price": 25.0, "quantity": 2},
        {"product": "shim", "price": 5.5, "quantity": 100},
        {"product": "flange", "price": 20.0, "quantity": 3},
        {"product": "bearing", "price": 20.01, "quantity": 1},
    ]
    cases.append(
        TestCase("boundary_price", [fixed, 20.0], expected=_expected(fixed, 20.0))
    )
    cases.append(TestCase("empty_input", [[], 20.0], expected=0.0))

    nothing_qualifies = _sales(rng, 6)
    for row in nothing_qualifies:
        row["price"] = round(rng.uniform(1.0, 19.0), 2)
    cases.append(
        TestCase(
            "none_above_threshold",
            [nothing_qualifies, 20.0],
            expected=0.0,
        )
    )

    for size in (12, 400):
        data = _sales(rng, size)
        cases.append(
            TestCase(f"random_{size}", [data, 20.0], expected=_expected(data, 20.0))
        )

    return cases


STARTER = '''\
def total_revenue(sales, threshold):
    """Return total revenue for sales whose unit price is above threshold.

    Each sale is a dict with keys: product, price, quantity.
    Revenue for one sale is price * quantity.
    Round the result to 2 decimal places.
    """
    # Your code here
    return 0.0
'''

REFERENCE = '''\
def total_revenue(sales, threshold):
    return round(
        sum(s["price"] * s["quantity"] for s in sales if s["price"] > threshold), 2
    )
'''

LEVEL = Level(
    id="w1-l1-revenue",
    world=1,
    world_title="Data Wrangler",
    index=1,
    title="Revenue Above Threshold",
    brief=(
        "You have a list of dictionaries representing sales data. Return the "
        "total revenue (price * quantity) for products whose price is strictly "
        "greater than the given threshold, rounded to 2 decimal places."
    ),
    func_name="total_revenue",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=180.0,
    tags=("data", "tabular", "functional"),
    style_goals=("uses_generator_expr",),
)
