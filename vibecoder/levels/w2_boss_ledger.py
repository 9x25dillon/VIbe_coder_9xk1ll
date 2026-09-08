"""World 2's boss: assembling an algorithm out of three linked moves.

Where [W1's boss](w1_boss_pipeline.py) is a *pipeline* — parse, filter, report,
each move a shape change — this one is an **assembly**. Index, aggregate, rank:
three moves that only work because each is built on the one before it, which is
what World 2 spends three levels teaching.

The chain is genuinely a chain, and that is the difference from W1. There, only
the last step called anything (`summarise` used both predecessors, and the
middle step stood alone). Here every link is real: `totals_by_customer` calls
`index_prices`, and `top_spenders` calls `totals_by_customer`. A player who
solves step two by scanning the product list for every order will *pass* — and
watch the Functional axis charge them for it, which is exactly the lesson
`w2-l3-join` exists to teach, now with a boss attached.

## Everything here is integer arithmetic, on purpose

Prices are whole cents. That is not decoration: a total assembled in one order
by the reference and in another by the player must compare equal, and floats
make that a question about summation order rather than about the algorithm.
Rounding tolerance is a different lesson than this boss is teaching, so the
opportunity to need it was removed rather than managed.
"""

from __future__ import annotations

import random

from ..models import BossLevel, BossStep, TestCase

#: The worked example, shared by all three steps so the fight reads as one
#: story rather than three unrelated datasets. `A-100` appears twice — a
#: restock — which is the whole point of step one.
PRODUCTS = [
    {"sku": "A-100", "price": 250},
    {"sku": "B-200", "price": 1200},
    {"sku": "C-300", "price": 75},
    {"sku": "A-100", "price": 300},
]

ORDERS = [
    {"customer": "ada", "sku": "A-100", "quantity": 2},
    {"customer": "grace", "sku": "B-200", "quantity": 1},
    {"customer": "ada", "sku": "C-300", "quantity": 4},
    {"customer": "linus", "sku": "Z-999", "quantity": 5},
    {"customer": "grace", "sku": "C-300", "quantity": 8},
]

SKUS = ["A-100", "B-200", "C-300", "D-400", "E-500", "F-600", "G-700", "H-800"]
CUSTOMERS = ["ada", "grace", "alan", "edsger", "barbara", "radia", "margaret"]


def _products(rng: random.Random, count: int) -> list[dict]:
    """A product list with deliberate duplicate skus.

    The sku pool is smaller than any interesting ``count``, so restocks happen
    by construction rather than by luck — a generated case that never repeated
    a sku would not exercise the rule step one is about.
    """
    return [
        {"sku": rng.choice(SKUS), "price": rng.randint(25, 5000)}
        for _ in range(count)
    ]


def _orders(rng: random.Random, count: int) -> list[dict]:
    """Orders over the same sku pool, with roughly one in eight unknown.

    The unknown sku is what makes "skip it" a rule rather than a footnote, and
    generating it here means the large cases test it too.
    """
    return [
        {
            "customer": rng.choice(CUSTOMERS),
            "sku": rng.choice(SKUS) if rng.random() > 0.125 else "Z-999",
            "quantity": rng.randint(0, 12),
        }
        for _ in range(count)
    ]


def _index(products: list[dict]) -> dict:
    return {p["sku"]: p["price"] for p in products}


def _totals(orders: list[dict], products: list[dict]) -> dict:
    prices = _index(products)
    totals: dict[str, int] = {}
    for order in orders:
        if order["sku"] not in prices:
            continue
        cost = prices[order["sku"]] * order["quantity"]
        totals[order["customer"]] = totals.get(order["customer"], 0) + cost
    return totals


def _top(products: list[dict], orders: list[dict], n: int) -> list[dict]:
    totals = _totals(orders, products)
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return [{"customer": name, "total": total} for name, total in ranked[:n]]


# --------------------------------------------------------------------------
# Step 1 - index
# --------------------------------------------------------------------------

def make_index_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("worked_example", [list(PRODUCTS)], expected=_index(PRODUCTS)),
        TestCase("empty_catalogue", [[]], expected={}),
        TestCase(
            "single_product",
            [[{"sku": "A-100", "price": 250}]],
            expected={"A-100": 250},
        ),
        TestCase(
            "a_restock_supersedes_the_original",
            [[{"sku": "A-100", "price": 250}, {"sku": "A-100", "price": 300}]],
            expected={"A-100": 300},
        ),
        TestCase(
            "distinct_skus_all_survive",
            [[{"sku": "A-100", "price": 250}, {"sku": "B-200", "price": 75}]],
            expected={"A-100": 250, "B-200": 75},
        ),
    ]
    for size in (12, 80):
        products = _products(rng, size)
        cases.append(
            TestCase(f"random_{size}", [products], expected=_index(products))
        )
    return cases


INDEX = BossStep(
    id="index",
    title="Index the catalogue",
    brief=(
        "The catalogue is a list of {'sku': str, 'price': int} and prices are "
        "whole cents. Turn it into a {sku: price} lookup. A sku can appear "
        "more than once -- that is a restock, and the LAST price for a sku is "
        "the one that counts."
    ),
    func_name="index_prices",
    starter='''\
def index_prices(products):
    """Build a {sku: price} lookup from the catalogue."""
    index = {}
    for product in products:
        if product["sku"] not in index:
            index[product["sku"]] = product["price"]
    return index
''',
    reference='''\
def index_prices(products):
    """Build a {sku: price} lookup from the catalogue."""
    return {product["sku"]: product["price"] for product in products}
''',
    make_tests=make_index_tests,
    hints=(
        "A restock should overwrite, not be ignored. Which way round is the "
        "starter doing it?",
        "Assigning the same key twice keeps the second value -- that is the "
        "behaviour you want, not one to guard against.",
        "A dict comprehension over the products does the whole thing, and it "
        "gets the last-wins rule for free.",
    ),
    style_goals=("uses_comprehension",),
)


# --------------------------------------------------------------------------
# Step 2 - aggregate, using the index
# --------------------------------------------------------------------------

def make_totals_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase(
            "worked_example",
            [list(ORDERS), list(PRODUCTS)],
            expected=_totals(ORDERS, PRODUCTS),
        ),
        TestCase("no_orders", [[], list(PRODUCTS)], expected={}),
        TestCase(
            "one_order_one_customer",
            [
                [{"customer": "ada", "sku": "A-100", "quantity": 3}],
                [{"sku": "A-100", "price": 250}],
            ],
            expected={"ada": 750},
        ),
        TestCase(
            "two_orders_accumulate",
            [
                [
                    {"customer": "ada", "sku": "A-100", "quantity": 3},
                    {"customer": "ada", "sku": "B-200", "quantity": 1},
                ],
                [{"sku": "A-100", "price": 250}, {"sku": "B-200", "price": 100}],
            ],
            expected={"ada": 850},
        ),
        TestCase(
            "an_unknown_sku_is_skipped_entirely",
            [
                [{"customer": "linus", "sku": "Z-999", "quantity": 5}],
                [{"sku": "A-100", "price": 250}],
            ],
            expected={},
        ),
        TestCase(
            "a_zero_quantity_order_still_counts_the_customer",
            [
                [{"customer": "ada", "sku": "A-100", "quantity": 0}],
                [{"sku": "A-100", "price": 250}],
            ],
            expected={"ada": 0},
        ),
    ]
    for products, orders in ((12, 40), (40, 300)):
        catalogue = _products(rng, products)
        book = _orders(rng, orders)
        cases.append(
            TestCase(
                f"random_{products}x{orders}",
                [book, catalogue],
                expected=_totals(book, catalogue),
            )
        )
    return cases


TOTALS = BossStep(
    id="totals",
    title="Total up the spend",
    brief=(
        "Given orders -- {'customer': str, 'sku': str, 'quantity': int} -- and "
        "the catalogue, return {customer: total_spend}. An order costs price "
        "* quantity. Skip an order whose sku is not in the catalogue: a "
        "customer whose every order is unknown does not appear at all. Use "
        "the lookup you just built -- scanning the catalogue for each order "
        "passes, and the Functional axis will charge you for it."
    ),
    func_name="totals_by_customer",
    starter='''\
def totals_by_customer(orders, products):
    """Sum price * quantity per customer, skipping unknown skus."""
    prices = index_prices(products)
    totals = {}
    for order in orders:
        if order["sku"] not in prices:
            continue
        cost = prices[order["sku"]] * order["quantity"]
        totals[order["customer"]] = cost
    return totals
''',
    reference='''\
def totals_by_customer(orders, products):
    """Sum price * quantity per customer, skipping unknown skus."""
    prices = index_prices(products)
    totals = {}
    for order in orders:
        if order["sku"] not in prices:
            continue
        cost = prices[order["sku"]] * order["quantity"]
        totals[order["customer"]] = totals.get(order["customer"], 0) + cost
    return totals
''',
    make_tests=make_totals_tests,
    uses=("index_prices",),
    hints=(
        "Watch one customer's total as the loop runs. Does it grow, or does "
        "it get replaced?",
        "A second order from the same customer has to add to what is already "
        "there.",
        "totals.get(customer, 0) gives you the running total to add to, with "
        "0 for a customer you have not seen yet.",
    ),
)


# --------------------------------------------------------------------------
# Step 3 - rank, using the totals
# --------------------------------------------------------------------------

def make_top_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase(
            "worked_example",
            [list(PRODUCTS), list(ORDERS), 1],
            expected=_top(PRODUCTS, ORDERS, 1),
        ),
        TestCase("no_orders", [list(PRODUCTS), [], 3], expected=[]),
        TestCase(
            "n_of_zero_returns_nothing",
            [list(PRODUCTS), list(ORDERS), 0],
            expected=[],
        ),
        TestCase(
            "n_beyond_the_customer_count_returns_everyone",
            [
                [{"sku": "A-100", "price": 100}],
                [
                    {"customer": "ada", "sku": "A-100", "quantity": 3},
                    {"customer": "grace", "sku": "A-100", "quantity": 1},
                ],
                9,
            ],
            expected=[
                {"customer": "ada", "total": 300},
                {"customer": "grace", "total": 100},
            ],
        ),
        TestCase(
            "a_tie_is_broken_by_customer_name",
            [
                [{"sku": "A-100", "price": 100}],
                [
                    {"customer": "grace", "sku": "A-100", "quantity": 2},
                    {"customer": "ada", "sku": "A-100", "quantity": 2},
                ],
                2,
            ],
            expected=[
                {"customer": "ada", "total": 200},
                {"customer": "grace", "total": 200},
            ],
        ),
        TestCase(
            "only_the_leader_when_n_is_one",
            [
                [{"sku": "A-100", "price": 100}],
                [
                    {"customer": "ada", "sku": "A-100", "quantity": 1},
                    {"customer": "grace", "sku": "A-100", "quantity": 5},
                ],
                1,
            ],
            expected=[{"customer": "grace", "total": 500}],
        ),
    ]
    for products, orders, n in ((12, 40, 3), (40, 300, 5)):
        catalogue = _products(rng, products)
        book = _orders(rng, orders)
        cases.append(
            TestCase(
                f"random_{products}x{orders}",
                [catalogue, book, n],
                expected=_top(catalogue, book, n),
            )
        )
    return cases


TOP = BossStep(
    id="top",
    title="Name the biggest spenders",
    brief=(
        "Put it together. Given the catalogue, the orders and a number n, "
        "return the top n customers as [{'customer': str, 'total': int}, ...] "
        "ordered by total descending. Break a tie with the customer name, "
        "ascending. Fewer than n customers means return them all."
    ),
    func_name="top_spenders",
    starter='''\
def top_spenders(products, orders, n):
    """The n biggest spenders, highest total first."""
    totals = totals_by_customer(orders, products)
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return [{"customer": name, "total": total} for name, total in ranked]
''',
    reference='''\
def top_spenders(products, orders, n):
    """The n biggest spenders, highest total first."""
    totals = totals_by_customer(orders, products)
    ranked = sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"customer": name, "total": total} for name, total in ranked[:n]
    ]
''',
    make_tests=make_top_tests,
    uses=("totals_by_customer",),
    hints=(
        "The order is right. Count what comes back and compare it to n.",
        "'Top n' means the first n of the ranking, not the whole ranking.",
        "ranked[:n] slices it, and it already does the right thing when "
        "there are fewer than n customers.",
    ),
    style_goals=("uses_comprehension",),
)


BOSS = BossLevel(
    id="w2-boss-ledger",
    world=2,
    world_title="Data Wrangler",
    index=99,
    title="The Ledger",
    brief=(
        "A quarter of orders and a catalogue that has been restocked twice. "
        "Finance wants the biggest spenders by Friday. Assemble it in three "
        "moves -- index the catalogue, total the spend, rank the result -- "
        "and each move is built on the one before it."
    ),
    steps=(INDEX, TOTALS, TOP),
    par_seconds=1200.0,
    tags=("data", "datastructures", "algorithms"),
)
