"""World 1, Level 3 - the level the functional axis was designed to teach.

A nested-loop join passes every test and still scores badly, because the
reference builds a lookup dict first. This is the clearest demonstration in the
game that correctness is only half of a level.
"""

from __future__ import annotations

import random

from ..models import Level, TestCase

NAMES = [
    "ada", "grace", "alan", "edsger", "barbara", "donald", "linus",
    "guido", "ken", "dennis", "margaret", "radia",
]


def _dataset(rng: random.Random, users: int, events: int) -> tuple[list, list]:
    user_rows = [
        {"id": i, "name": rng.choice(NAMES) + str(i)} for i in range(1, users + 1)
    ]
    event_rows = [
        {"user_id": rng.randint(1, users + 2), "action": rng.choice(["click", "view"])}
        for _ in range(events)
    ]
    return user_rows, event_rows


def _expected(users: list, events: list) -> list:
    lookup = {u["id"]: u["name"] for u in users}
    return [
        {"name": lookup[e["user_id"]], "action": e["action"]}
        for e in events
        if e["user_id"] in lookup
    ]


def make_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("no_events", [[{"id": 1, "name": "ada"}], []], expected=[]),
        TestCase("no_users", [[], [{"user_id": 1, "action": "click"}]], expected=[]),
        TestCase(
            "unmatched_event_dropped",
            [
                [{"id": 1, "name": "ada"}],
                [{"user_id": 1, "action": "click"},
                 {"user_id": 99, "action": "view"}],
            ],
            expected=[{"name": "ada", "action": "click"}],
        ),
    ]
    # The large case is what separates a dict lookup from a nested scan.
    for users, events in ((8, 20), (60, 400)):
        user_rows, event_rows = _dataset(rng, users, events)
        cases.append(
            TestCase(
                f"random_{users}x{events}",
                [user_rows, event_rows],
                expected=_expected(user_rows, event_rows),
            )
        )
    return cases


STARTER = '''\
def join_events(users, events):
    """Attach each event to its user's name.

    users:  [{"id": int, "name": str}, ...]
    events: [{"user_id": int, "action": str}, ...]

    Return [{"name": str, "action": str}, ...] in the original event order.
    Events whose user_id matches no user are dropped.
    """
    # Your code here
    return []
'''

REFERENCE = '''\
def join_events(users, events):
    lookup = {u["id"]: u["name"] for u in users}
    return [
        {"name": lookup[e["user_id"]], "action": e["action"]}
        for e in events
        if e["user_id"] in lookup
    ]
'''

LEVEL = Level(
    id="w1-l3-join",
    world=1,
    world_title="Data Wrangler",
    index=3,
    title="Join Without the Nested Loop",
    brief=(
        "Join events to users by id, preserving event order and dropping events "
        "with no matching user. A nested loop will pass every test - the "
        "Functional axis is where it will cost you."
    ),
    func_name="join_events",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=300.0,
    tags=("data", "datastructures", "algorithms"),
    style_goals=("uses_comprehension",),
)
