"""How hard to make the next variant, and why. T4 W4.

The policy answers one question -- *given what we know about this player, how
hard should this level's variant be?* -- and it answers it with a `Decision`
that carries the reason alongside the number.

**The reason is not decoration and is not deferred to W7.** Exit criterion 4
requires every difficulty decision to be explainable in one sentence "with no
hidden state", and a policy that computes a number and has an explanation
retrofitted afterwards has exactly that: two code paths that can disagree, one
of which the player sees. Producing both together is what makes the sentence
true rather than plausible.

## Two sources, never blended

T4 contains a tension worth naming rather than smoothing over. The
tag-sparsity hazard says to *fall back to the Vibe Vector* until a tag has
enough observations. The very next hazard says confusing "what you write" with
"what you are good at" is the most tempting and most wrong simplification
available. Both are right, and the resolution is that the two sources are used
**one at a time and always named**:

* **Mastery** -- what you scored, on levels you played. Used whenever the
  level's tags have enough observations to be worth acting on.
* **Habits** -- what your codebase looks like. A *prior*, used only when there
  is no mastery evidence at all, bounded so it can never reach either extreme,
  and always reported as coming from your code rather than your scores.

A player is never shown a number blending the two (criterion 8); they are
shown which one was used. The moment mastery has evidence, it wins outright --
habits are what we guess with before we have measured anything, not a term we
average in forever.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .mastery import MIN_OBSERVATIONS, Mastery
from .models import Difficulty, VibeVector

#: Where the policy aims to put the player, as a share of runs that go well.
#: T4 W4 asks for 70-80%; the midpoint is the target and the band is what
#: exit criterion 3 measures against.
TARGET_SUCCESS = 0.75

#: How far *below* a player's mastery the difficulty sits. Matching difficulty
#: to mastery exactly would put every run at the player's edge, which is a
#: coin flip rather than the 75% the band asks for. A tenth of the scale is
#: the starting value; it is measured in `tests/test_policy.py` rather than
#: asserted, and it is the dial to turn if the simulated band comes out wrong.
STRETCH = 0.1

#: The most a codebase's familiarity may move the starting difficulty. Bounded
#: hard on purpose: habits are a prior, not a measurement, and a player whose
#: code is full of comprehensions has not thereby demonstrated they are good
#: at them. +-0.15 keeps the guess inside the standard band, so the worst a
#: wrong prior can do is hand someone a slightly roomier or tighter first run.
HABIT_NUDGE = 0.15


@dataclass(frozen=True)
class Decision:
    """A chosen difficulty, the source it came from, and the sentence for it.

    ``evidence`` carries the numbers the sentence was built from, so a caller
    can show the working rather than asking the player to trust the prose.
    That is the difference criterion 4 draws between an explanation and a
    label.
    """

    difficulty: Difficulty
    #: ``mastery``, ``habits`` or ``default`` -- which source decided this.
    source: str
    reason: str
    evidence: dict = field(default_factory=dict)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def choose_difficulty(
    tags: "tuple[str, ...] | list[str]",
    mastery: Mastery,
    vibe: VibeVector | None = None,
) -> Decision:
    """Pick a variant difficulty for a level carrying ``tags``.

    Reads only the tags the level actually declares. A player who is strong on
    ``data`` gets no credit for it on a ``recursion`` level, which is the whole
    reason mastery is per tag rather than a single number.
    """
    tags = list(tags)

    confident = [tag for tag in tags if mastery.confident(tag)]
    if confident:
        scores = [mastery.value(tag) for tag in confident]
        average = _mean(scores)
        # Rounded because this number reaches the player in a sentence,
        # and because a bound stated as +-0.15 should not be missed by
        # 2e-17 of float noise.
        level = round(average - STRETCH, 4)
        named = ", ".join(sorted(confident))
        return Decision(
            difficulty=Difficulty(level),
            source="mastery",
            reason=(
                f"you have played {named} enough for a read: "
                f"you average {average:.0%} there, so this variant is "
                f"{Difficulty(level).band}"
            ),
            evidence={
                "tags_used": sorted(confident),
                "tags_ignored": sorted(set(tags) - set(confident)),
                "mean_mastery": round(average, 4),
                "stretch": STRETCH,
            },
        )

    if vibe is not None and tags:
        # No mastery evidence, so guess from the code the player brought.
        # Familiarity is a share of the level's tags, not of the codebase's,
        # because the question is "is this level's material familiar" and not
        # "how broad is this codebase".
        known = set(vibe.tags)
        familiarity = len(set(tags) & known) / len(tags)
        level = round(0.5 + HABIT_NUDGE * (familiarity * 2 - 1), 4)
        shown = ", ".join(sorted(set(tags) & known)) or "none of it"
        return Decision(
            difficulty=Difficulty(level),
            source="habits",
            reason=(
                f"you have not played these tags enough to measure, so this "
                f"is a guess from your codebase, which shows {shown}"
            ),
            evidence={
                "tags_seen_in_your_code": sorted(set(tags) & known),
                "familiarity": round(familiarity, 4),
                "nudge": HABIT_NUDGE,
                "note": "from what you write, not what you have scored",
            },
        )

    return Decision(
        difficulty=Difficulty(),
        source="default",
        reason=(
            "nothing measured yet and no profile to guess from, so this is "
            "the standard variant"
        ),
        evidence={
            "tags": sorted(tags),
            "observations_needed": MIN_OBSERVATIONS,
        },
    )
