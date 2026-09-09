"""The daily challenge: the same puzzle for everyone, with no server. T5 W1.

One level, one variant seed, derived from the date alone. Two people who have
never met and cannot reach a network get the same problem, which is what makes
a shared challenge possible before any of T5's backend exists.

## `hash()` would not have worked

The waypoint is written as ``hash(date)`` -> variant, and that is the one thing
this must not do. Python randomises `hash` for `str` per process unless
`PYTHONHASHSEED` is pinned, so the same date produces a different answer on
every *run* -- exit criterion 1 asks for two machines to agree and `hash` does
not manage two invocations on one. Measured before writing this module:

    $ for i in 1 2 3; do python3 -c "print(hash('2026-09-08'))"; done
    -7723537222559262413
    -7920657940426615118
     1873428733625979326

`hashlib.sha256` is specified, stable across builds and platforms, and in the
standard library, so it costs nothing (N1).

## What "deterministic" is scoped to

A daily is determined by **the date and the set of levels in this build**.
Adding a level changes which one a past date selects, and that is unavoidable
without pinning a catalogue snapshot into the code -- which would then rot
against the levels that actually exist. The criterion is about two machines
agreeing, and two machines running the same build do.

## This module imports nothing

Like `fight.py` and `mastery.py`. It is handed the level ids rather than
reaching for the registry, so the selection is testable against any catalogue,
including the empty one and a hand-built pair.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

#: How the digest is split. The first eight bytes pick the level, the next
#: eight pick the variant, so the two are independent -- a date that lands on
#: the same level as another does not thereby land on the same seed.
_LEVEL_BYTES = slice(0, 8)
_SEED_BYTES = slice(8, 16)

#: Keeps a generated seed inside a range that reads like the hand-picked ones
#: elsewhere and cannot overflow anything downstream. `random.Random` accepts
#: any int; this is for the human who has to read it in a bug report.
SEED_MODULUS = 1_000_000


@dataclass(frozen=True)
class Daily:
    """One day's challenge. Frozen: everyone gets exactly this.

    ``difficulty`` is deliberately absent. A daily is the *same puzzle for
    everyone*, so it cannot be adapted to a player -- T4's whole selection
    policy is bypassed here, and exit criterion 1 is the reason. That is not
    an oversight in the model; it is what a shared challenge means.
    """

    date: str
    level_id: str
    seed: int


def digest(text: str) -> bytes:
    """A hash that is the same in every process, build and platform."""
    return hashlib.sha256(text.encode("utf-8")).digest()


def choose(date: str, level_ids: "list[str] | tuple[str, ...]") -> "Daily | None":
    """The challenge for ``date``, or ``None`` when there is nothing to choose.

    ``level_ids`` are sorted before indexing, so the answer depends on *which*
    levels exist and never on the order a registry happened to return them --
    an ordering bug elsewhere would otherwise silently change what everyone
    plays today.
    """
    catalogue = sorted(level_ids)
    if not catalogue:
        return None

    raw = digest(date)
    level = int.from_bytes(raw[_LEVEL_BYTES], "big") % len(catalogue)
    seed = int.from_bytes(raw[_SEED_BYTES], "big") % SEED_MODULUS
    return Daily(date=date, level_id=catalogue[level], seed=seed)


# --------------------------------------------------------------------------
# History and the local board (T5 W2)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Attempt:
    """One completed daily, as it was actually played.

    **The level and seed are stored, not re-derived** (Q99). `choose` depends
    on the build's level catalogue, so adding a level changes which one a past
    date selects -- and a history that recomputed yesterday would quietly
    rewrite what you played. A board comparing two builds would then be
    comparing two puzzles while showing one date.

    ``ranked`` marks the first completed run of a date. A daily is one shot at
    the same problem as everyone else, so later replays are recorded and
    counted but never replace the score that counts. That is enforceable
    without a server, which is the whole point of W2.
    """

    date: str
    level_id: str
    seed: int
    total: float
    stars: int
    ranked: bool = True
    at: str = ""


def streak(dates: "list[str] | tuple[str, ...]", today: str) -> int:
    """Consecutive days played, counting back from ``today``.

    A streak that survives a gap is not a streak, and one that requires today
    to have been played would read as broken every morning -- so it counts
    back from today if today is present and from yesterday otherwise. Pure
    string arithmetic on ISO dates, so it needs no `datetime` and no clock.
    """
    played = set(dates)
    if not played:
        return 0

    from datetime import date as _date, timedelta

    try:
        cursor = _date.fromisoformat(today)
    except ValueError:
        return 0

    if today not in played:
        cursor -= timedelta(days=1)

    count = 0
    while cursor.isoformat() in played:
        count += 1
        cursor -= timedelta(days=1)
    return count


def board(attempts: "list[Attempt] | tuple[Attempt, ...]", limit: int = 10
          ) -> list[Attempt]:
    """The ranked attempts, best first. Local, and complete on its own.

    Exit criterion 5 says leaderboards must remain usable offline, degrading
    to local-only. This *is* the local one: it reads a list and reaches for
    nothing. W3's server becomes an overlay on top rather than the source, so
    "offline" is the default path rather than a fallback that has to be
    remembered.

    Only ranked attempts appear. A replay is real and is kept, but a board
    that let you grind the same date would be measuring persistence.
    """
    ranked = [attempt for attempt in attempts if attempt.ranked]
    return sorted(ranked, key=lambda a: (-a.total, a.date))[:limit]
