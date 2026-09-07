"""A cursor over execution history (T3 W3), and whether a re-run matches it (W5).

Stepping back is not running backwards. The steps already happened and are
already recorded, so going back is moving a cursor over a list — **no
re-execution, ever**. That is the whole waypoint, and it is worth stating as a
property rather than an implementation detail: nothing here calls anything, so
there is no side effect to replay, no non-determinism to worry about, and no
way for history to disagree with itself.

The subtlety is the *edge*. History has an end, and past that end sits a child
process still blocked mid-run. A cursor inside history is browsing; a cursor at
the edge is driving. Keeping those two ideas in one object, with one index,
is what stops "step forward" from meaning two different things depending on
state nobody is tracking.

`compare` is the other half of that idea. W4 resumes an edited run by
executing it again and fast-forwarding, so something has to check that the
fast-forwarded part really did happen the same way. Comparing two lists is
pure, which is why it lives here rather than next to the process that produced
them.

This module imports nothing from the package. It is a list and an integer, and
it should be testable without a sandbox, a child process, or a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Sequence


class Timeline:
    """Recorded steps, plus where the reader is looking.

    ``cursor`` is the index of the step currently in view. An empty timeline
    has a cursor of ``-1``, which reads as "before the beginning" and is the
    only position from which `forward` yields the first step.
    """

    def __init__(self, steps: Sequence[Any] = ()) -> None:
        self._steps: list[Any] = list(steps)
        self._cursor: int = len(self._steps) - 1

    # -- shape -------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._steps)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._steps)

    def __getitem__(self, index: int) -> Any:
        return self._steps[index]

    @property
    def steps(self) -> list[Any]:
        """A copy: history is not something a caller should be able to edit."""
        return list(self._steps)

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def current(self) -> Any | None:
        if 0 <= self._cursor < len(self._steps):
            return self._steps[self._cursor]
        return None

    @property
    def at_edge(self) -> bool:
        """Whether the cursor is on the newest step we hold.

        The caller uses this to decide whether stepping forward is *browsing*
        or *driving*. An empty timeline is at its edge, because the next step
        forward has to come from somewhere new either way.
        """
        return self._cursor >= len(self._steps) - 1

    @property
    def at_start(self) -> bool:
        return self._cursor <= 0

    # -- moving ------------------------------------------------------------

    def back(self) -> Any | None:
        """The previous step, or ``None`` at the beginning of history.

        Returns ``None`` rather than raising, and does **not** move the cursor
        when there is nowhere to go: a reader holding down a key at the start
        of a run should sit still, not accumulate an error.
        """
        if self._cursor <= 0:
            return None
        self._cursor -= 1
        return self._steps[self._cursor]

    def forward(self) -> Any | None:
        """The next step already in history, or ``None`` at the edge.

        ``None`` means "history has nothing more" -- which is the caller's cue
        to go and get a new step from wherever steps come from. It is not an
        error and it is not the end of the run.
        """
        if self._cursor >= len(self._steps) - 1:
            return None
        self._cursor += 1
        return self._steps[self._cursor]

    def append(self, step: Any) -> Any:
        """Record a new step and move the cursor onto it.

        Appending always jumps to the edge. A new step arriving while the
        reader is browsing the past would otherwise leave the cursor pointing
        at unrelated history, and the reader would see the view stay still
        while the run moved -- which reads as a hang.
        """
        self._steps.append(step)
        self._cursor = len(self._steps) - 1
        return step

    def rewind(self) -> None:
        self._cursor = 0 if self._steps else -1

    def seek(self, index: int) -> Any | None:
        """Move to an absolute position, clamped to what exists."""
        if not self._steps:
            return None
        self._cursor = max(0, min(index, len(self._steps) - 1))
        return self._steps[self._cursor]


# --------------------------------------------------------------------------
# Divergence (T3 W5)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Divergence:
    """The first step at which a re-run stopped matching what already happened.

    Strategy A resumes an edited run by executing it again from the top and
    fast-forwarding to where the player was. That is only honest if somebody
    checks that the fast-forwarded part actually matched -- otherwise the
    engine is presenting a different execution as a continuation of the one
    the player watched, which is exactly what T3's exit criterion 4 forbids.
    """

    index: int
    original: Any
    replayed: Any | None
    reason: str

    def __str__(self) -> str:
        return self.reason


def signature(step: Any) -> tuple[str, tuple[tuple[str, str], ...]]:
    """What has to match for two steps to be the same thing happening.

    The function and the values it can see -- deliberately **not** the line
    number. The player has just edited the file, so the text has moved; a
    statement sliding from line 7 to line 8 because a guard clause was added
    above it is not the program behaving differently, and reporting it as
    divergence would fire on almost every edit and teach a player to ignore
    the warning.

    The cost of leaving it out is a false negative: two adjacent statements
    with identical locals are indistinguishable here. That is the cheaper
    error, because a missed divergence still shows up as the run visibly not
    doing what the history says, whereas a detector that cries wolf is
    switched off.

    Accepts a `Step` or a plain recorded dict, because history holds one or
    the other depending on where it came from (Q69).
    """
    if isinstance(step, dict):
        func = step.get("func", "")
        values = step.get("locals") or {}
    else:
        func = getattr(step, "func", "")
        values = getattr(step, "locals", None) or {}
    return str(func), tuple(sorted((str(k), str(v)) for k, v in values.items()))


def compare(original: Sequence[Any], replayed: Sequence[Any],
            *, upto: int | None = None) -> Divergence | None:
    """Where `replayed` first stops agreeing with `original`, or ``None``.

    Only the first ``upto`` steps are compared, because that is the part a
    resumed run claims to have reproduced. Everything after the edit point is
    *supposed* to differ -- that is what the player changed the code for.

    Running out of replayed steps early counts. A re-run that returns before
    reaching the line the player was looking at has not reproduced the prefix
    either, and saying nothing would leave them at a position that no longer
    exists.
    """
    limit = len(original) if upto is None else min(upto, len(original))
    for index in range(limit):
        if index >= len(replayed):
            return Divergence(
                index, original[index], None,
                f"the re-run stopped after {len(replayed)} step(s), "
                f"before reaching step {limit}",
            )
        was, now = signature(original[index]), signature(replayed[index])
        if was == now:
            continue
        if was[0] != now[0]:
            detail = f"ran {now[0]}() where it had run {was[0]}()"
        else:
            detail = f"reached {now[0]}() with different values"
        return Divergence(
            index, original[index], replayed[index],
            f"step {index + 1} {detail}",
        )
    return None
