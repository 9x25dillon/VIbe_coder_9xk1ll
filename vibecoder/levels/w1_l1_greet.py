"""World 1, Level 1 - the first function a person ever finishes.

This level teaches exactly one thing: a function gives a value back with
``return``. It is deliberately the smallest task in the game. A beginner who
has only ever printed things needs to feel the difference between printing and
returning once, and everything after this assumes it.
"""

from __future__ import annotations

import random

from ..models import Level, TestCase

NAMES = [
    "Ada", "Grace", "Alan", "Katherine", "Linus", "Barbara",
    "Edsger", "Radia", "Tim", "Margaret", "Ken", "Frances",
]


def _expected(name: str) -> str:
    return f"Hello, {name}!"


def make_tests(rng: random.Random) -> list[TestCase]:
    """Four hand-written cases plus randomised names.

    The hand-written ones are the cases randomness will not reliably produce:
    the empty string, a name with a space in it, and a single character.
    """
    cases = [
        TestCase("simple", ["Ada"], expected=_expected("Ada")),
        TestCase("empty_name", [""], expected=_expected("")),
        TestCase("two_words", ["Ada Lovelace"], expected=_expected("Ada Lovelace")),
        TestCase("one_letter", ["X"], expected=_expected("X")),
    ]
    for name in rng.sample(NAMES, 4):
        cases.append(TestCase(f"name_{name}", [name], expected=_expected(name)))
    return cases


STARTER = '''\
def greet(name):
    """Return a greeting for name.

    If name is "Ada", return exactly:  Hello, Ada!
    Mind the comma, the space and the exclamation mark.
    """
    # Your code here. Remember: return the text, do not print it.
    return ""
'''

REFERENCE = '''\
def greet(name):
    return f"Hello, {name}!"
'''

LEVEL = Level(
    id="w1-l1-greet",
    world=1,
    world_title="First Steps",
    index=1,
    title="Say Hello",
    brief=(
        "Return a greeting for the given name. If the name is Ada, the result "
        "should be exactly 'Hello, Ada!' - with the comma, the space and the "
        "exclamation mark. Return it; do not print it."
    ),
    func_name="greet",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=120.0,
    tags=("basics", "strings"),
)
