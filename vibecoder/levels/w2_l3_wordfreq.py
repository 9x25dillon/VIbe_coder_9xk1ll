"""World 2, Level 3 - text normalisation plus a tie-break rule people miss."""

from __future__ import annotations

import random
import re

from ..models import Level, TestCase

VOCAB = [
    "the", "runner", "compiles", "vector", "loop", "stack", "heap",
    "trace", "frame", "byte", "opcode", "vibe",
]

_WORD = re.compile(r"[a-z']+")


def _expected(text: str, n: int) -> list:
    counts: dict[str, int] = {}
    for word in _WORD.findall(text.lower()):
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [list(pair) for pair in ranked[:n]]


def _text(rng: random.Random, words: int) -> str:
    parts = []
    for _ in range(words):
        word = rng.choice(VOCAB)
        if rng.random() < 0.2:
            word = word.upper()
        parts.append(word)
        if rng.random() < 0.1:
            parts.append(rng.choice([",", ".", "!", "--"]))
    return " ".join(parts)


def make_tests(rng: random.Random) -> list[TestCase]:
    cases = [
        TestCase("empty", ["", 3], expected=[]),
        TestCase("punctuation_only", ["... !! --", 3], expected=[]),
        TestCase(
            "case_folded",
            ["Vibe vibe VIBE loop", 2],
            expected=[["vibe", 3], ["loop", 1]],
        ),
        TestCase(
            "alphabetical_tiebreak",
            ["zebra apple apple zebra mango", 3],
            expected=[["apple", 2], ["zebra", 2], ["mango", 1]],
        ),
        TestCase("n_larger_than_vocab", ["one two", 10],
                 expected=[["one", 1], ["two", 1]]),
    ]
    for words in (50, 800):
        text = _text(rng, words)
        cases.append(TestCase(f"random_{words}", [text, 5], expected=_expected(text, 5)))
    return cases


STARTER = '''\
def top_words(text, n):
    """Return the n most frequent words as [word, count] pairs.

    Words are lowercase runs of letters and apostrophes; everything else is a
    separator. Sort by descending count, then alphabetically for ties.
    Return fewer than n pairs if the text has fewer distinct words.
    """
    # Your code here
    return []
'''

REFERENCE = '''\
import re
from collections import Counter

_WORD = re.compile(r"[a-z']+")


def top_words(text, n):
    counts = Counter(_WORD.findall(text.lower()))
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [list(pair) for pair in ranked[:n]]
'''

LEVEL = Level(
    id="w2-l3-wordfreq",
    world=2,
    world_title="Algorithm Architect",
    index=3,
    title="Top Words",
    brief=(
        "Count word frequencies in a block of text and return the top n as "
        "[word, count] pairs. Words are case-folded runs of letters and "
        "apostrophes. Ties break alphabetically - that rule is the one most "
        "submissions get wrong."
    ),
    func_name="top_words",
    starter=STARTER,
    reference=REFERENCE,
    make_tests=make_tests,
    par_seconds=360.0,
    tags=("text", "regex", "datastructures", "algorithms"),
    style_goals=(),
)
