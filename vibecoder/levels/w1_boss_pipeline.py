"""World 1's boss: a three-step data pipeline.

The first boss exists as much to exercise the format as to be played. It is
deliberately made of small, ordinary functions -- parse, filter, summarise --
because the interesting part of a boss is that the steps *link*, and a boss
whose individual steps are hard would test the wrong thing at this point in
the campaign.

Step three calls both earlier functions, which is what makes this a fight
rather than three unrelated levels in a row.
"""

from __future__ import annotations

import random

from ..models import BossLevel, BossStep, TestCase

RAW = [
    "widget,25.0,2",
    "sprocket,3.5,10",
    "gasket,12.25,4",
    "flange,60.0,1",
    "bracket,0.99,250",
]


def _rows(rng: random.Random, count: int) -> list[str]:
    names = ["widget", "sprocket", "gasket", "flange", "bracket", "shim"]
    return [
        f"{rng.choice(names)},{round(rng.uniform(0.5, 80.0), 2)},{rng.randint(1, 40)}"
        for _ in range(count)
    ]


def _parsed(lines: list[str]) -> list[dict]:
    out = []
    for line in lines:
        name, price, quantity = line.split(",")
        out.append(
            {"name": name, "price": float(price), "quantity": int(quantity)}
        )
    return out


# --------------------------------------------------------------------------
# Step 1 - parse
# --------------------------------------------------------------------------

def make_parse_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("worked_example", [list(RAW)], expected=_parsed(RAW)),
        TestCase("empty_input", [[]], expected=[]),
        TestCase(
            "single_row",
            [["shim,1.5,3"]],
            expected=[{"name": "shim", "price": 1.5, "quantity": 3}],
        ),
        TestCase(
            "integer_price_stays_a_float",
            [["gasket,7,2"]],
            expected=[{"name": "gasket", "price": 7.0, "quantity": 2}],
        ),
    ]
    for size in (12, 60):
        rows = _rows(rng, size)
        cases.append(TestCase(f"random_{size}", [rows], expected=_parsed(rows)))
    return cases


PARSE = BossStep(
    id="parse",
    title="Parse the feed",
    brief=(
        "Each line is 'name,price,quantity'. Turn a list of lines into a list "
        "of dicts with keys name, price and quantity. Price is a float and "
        "quantity is an int -- the strings arrive as text and must not stay "
        "that way."
    ),
    func_name="parse_rows",
    starter='''\
def parse_rows(lines):
    """Turn 'name,price,quantity' lines into dicts."""
    rows = []
    for line in lines:
        name, price, quantity = line.split(",")
        rows.append({
            "name": name,
            "price": float(price),
            "quantity": int(quantity),
        })
        return rows
    return rows
''',
    reference='''\
def parse_rows(lines):
    """Turn 'name,price,quantity' lines into dicts."""
    rows = []
    for line in lines:
        name, price, quantity = line.split(",")
        rows.append({
            "name": name,
            "price": float(price),
            "quantity": int(quantity),
        })
    return rows
''',
    make_tests=make_parse_tests,
    hints=(
        "Each line splits into exactly three pieces on a comma.",
        "float() and int() turn the text into numbers.",
        "Build one dict per line and append it to a list you return.",
    ),
)


# --------------------------------------------------------------------------
# Step 2 - filter
# --------------------------------------------------------------------------

def _kept(rows: list[dict], floor: float) -> list[dict]:
    return [r for r in rows if r["price"] >= floor]


def make_filter_tests(rng: random.Random) -> list[TestCase]:
    parsed = _parsed(RAW)
    cases = [
        TestCase("worked_example", [parsed, 10.0], expected=_kept(parsed, 10.0)),
        TestCase("empty_input", [[], 10.0], expected=[]),
        TestCase(
            "boundary_is_kept",
            [[{"name": "a", "price": 10.0, "quantity": 1}], 10.0],
            expected=[{"name": "a", "price": 10.0, "quantity": 1}],
        ),
        TestCase(
            "nothing_qualifies",
            [[{"name": "a", "price": 1.0, "quantity": 1}], 10.0],
            expected=[],
        ),
    ]
    for size in (12, 60):
        rows = _parsed(_rows(rng, size))
        cases.append(
            TestCase(f"random_{size}", [rows, 20.0], expected=_kept(rows, 20.0))
        )
    return cases


FILTER = BossStep(
    id="filter",
    title="Drop the cheap stock",
    brief=(
        "Given parsed rows and a price floor, return only the rows priced at "
        "or above the floor. The floor itself counts as qualifying."
    ),
    func_name="above_floor",
    starter='''\
def above_floor(rows, floor):
    """Keep rows priced at or above `floor`."""
    return [row for row in rows if row["price"] > floor]
''',
    reference='''\
def above_floor(rows, floor):
    """Keep rows priced at or above `floor`."""
    return [row for row in rows if row["price"] >= floor]
''',
    make_tests=make_filter_tests,
    hints=(
        "'At or above' means >=, not >.",
        "A comprehension with an if does this in one line.",
    ),
    style_goals=("uses_comprehension",),
)


# --------------------------------------------------------------------------
# Step 3 - summarise, using both of the above
# --------------------------------------------------------------------------

def _summary(lines: list[str], floor: float) -> dict:
    kept = _kept(_parsed(lines), floor)
    return {
        "count": len(kept),
        "revenue": round(sum(r["price"] * r["quantity"] for r in kept), 2),
    }


def make_summary_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("worked_example", [list(RAW), 10.0], expected=_summary(RAW, 10.0)),
        TestCase("empty_input", [[], 10.0], expected={"count": 0, "revenue": 0.0}),
        TestCase(
            "nothing_qualifies",
            [["shim,1.0,5"], 10.0],
            expected={"count": 0, "revenue": 0.0},
        ),
        TestCase(
            "single_row",
            [["gasket,10.0,3"], 10.0],
            expected={"count": 1, "revenue": 30.0},
        ),
    ]
    for size in (12, 60):
        rows = _rows(rng, size)
        cases.append(
            TestCase(f"random_{size}", [rows, 20.0], expected=_summary(rows, 20.0))
        )
    return cases


SUMMARY = BossStep(
    id="summary",
    title="Report the damage",
    brief=(
        "Put it together. Given raw lines and a price floor, return "
        "{'count': n, 'revenue': total} for the rows that qualify, where "
        "revenue is price * quantity summed and rounded to 2 decimal places. "
        "Use the two functions you already wrote."
    ),
    func_name="summarise",
    starter='''\
def summarise(lines, floor):
    """Parse, filter, and report count and revenue."""
    kept = above_floor(parse_rows(lines), floor)
    return {
        "count": len(kept),
        "revenue": round(sum(r["price"] for r in kept), 2),
    }
''',
    reference='''\
def summarise(lines, floor):
    """Parse, filter, and report count and revenue."""
    kept = above_floor(parse_rows(lines), floor)
    return {
        "count": len(kept),
        "revenue": round(sum(r["price"] * r["quantity"] for r in kept), 2),
    }
''',
    make_tests=make_summary_tests,
    uses=("parse_rows", "above_floor"),
    hints=(
        "You already have parse_rows and above_floor. Call them.",
        "revenue is price * quantity for every row that survived the filter.",
        "round(total, 2) at the end, not on each row.",
    ),
)


BOSS = BossLevel(
    id="w1-boss-pipeline",
    world=1,
    world_title="First Contact",
    index=99,
    title="The Feed",
    brief=(
        "A supplier feed arrives as raw text and nobody downstream can read "
        "it. Build the pipeline in three moves: parse it, filter it, and "
        "report what survived. Each move is checked before the next unlocks."
    ),
    steps=(PARSE, FILTER, SUMMARY),
    par_seconds=900.0,
    tags=("data", "tabular", "text"),
)
