"""World 1, Level 5 - keeping track of the best one seen so far.

The "best so far" variable is the first genuinely non-obvious pattern in the
game: it has to be initialised to something, and the tie rule decides whether
the comparison is ``>`` or ``>=``. Both mistakes are caught by hand-written
cases rather than by luck.
"""

from __future__ import annotations

import random

from ..models import Level, TestCase

WORDS = [
    "cat", "orbit", "sky", "elephant", "run", "keyboard", "tea",
    "mountain", "ink", "harbour", "fig", "telescope", "owl", "river",
]


def _expected(words: list[str]) -> str:
    longest = ""
    for word in words:
        if len(word) > len(longest):
            longest = word
    return longest


def make_tests(rng: random.Random) -> list[TestCase]:
    """The tie and the empty list are the two cases that decide the design."""
    cases = [
        TestCase("clear_winner", [["a", "bbb", "cc"]], expected="bbb"),
        TestCase("empty_list", [[]], expected=""),
        TestCase("tie_keeps_the_first", [["cat", "dog"]], expected="cat"),
        TestCase("single_word", [["solo"]], expected="solo"),
        TestCase("empty_strings", [["", "", "x"]], expected="x"),
    ]
    for index in range(3):
        picked = rng.sample(WORDS, rng.randint(4, 8))
        cases.append(
            TestCase(f"random_{index}", [picked], expected=_expected(picked))
        )
    big = [rng.choice(WORDS) for _ in range(400)]
    cases.append(TestCase("random_large", [big], expected=_expected(big)))
    return cases


STARTER = '''\
def longest_word(words):
    """Return the longest word in the list.

    If two words are the same length, return the one that appears first.
    If the list is empty, return "".
    """
    # Your code here. Keep track of the best word you have seen so far.
    return ""
'''

REFERENCE = '''\
def longest_word(words):
    longest = ""
    for word in words:
        if len(word) > len(longest):
            longest = word
    return longest
'''

LEVEL = Level(
    id="w1-l5-longest",
    world=1,
    world_title="First Steps",
    index=5,
    title="The Longest Word",
    brief=(
        "Return the longest word in the list. If two words tie for longest, "
        "return whichever appears first. If the list is empty, return an "
        "empty string."
    ),
    func_name="longest_word",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=300.0,
    tags=("basics", "loops", "strings"),
)
