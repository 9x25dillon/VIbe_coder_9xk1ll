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

    # Measured once, but the evidence has aged past being worth acting on
    # (T4 W6). Distinct from never having played it: the honest sentence is
    # "you did this, a while ago", and telling a returning player "nothing
    # measured yet" is true of the decayed model and false about their
    # history. Q91.
    stale = sorted(
        tag for tag in tags
        if tag in mastery and mastery[tag].updated_at
        and not mastery.confident(tag)
    )
    if stale:
        named = ", ".join(stale)
        return Decision(
            difficulty=Difficulty(),
            source="stale",
            reason=(
                f"you have played {named} before, but not recently enough for "
                f"the reading to still count, so this is a standard variant "
                f"while the game takes another look"
            ),
            evidence={
                "tags_gone_stale": stale,
                "last_seen": {tag: mastery[tag].updated_at for tag in stale},
                "note": "decayed out of confidence, not measured as weak",
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


# --------------------------------------------------------------------------
# Drills (T4 W5)
# --------------------------------------------------------------------------

#: A tag has to be measurably below the middle before it is worth drilling.
#: Above this the player is not struggling, and a drill offered to someone who
#: does not need one is noise that teaches them to ignore the next one.
DRILL_BELOW = 0.5

#: How many runs a drill is. Not a round number chosen by feel: after this
#: many observations the tag is `confident` again by definition, so a drill is
#: exactly long enough that the re-read at the end of it is worth acting on.
#: Any shorter and the game would be adapting to a drill it could not yet
#: measure the result of.
DRILL_LENGTH = MIN_OBSERVATIONS


@dataclass(frozen=True)
class Drill:
    """Repeated practice on the one tag the player is measurably weakest at.

    ``levels`` is the queue in order, already repeated out to `DRILL_LENGTH`.
    Ids rather than `Level` objects, so this module keeps depending on nothing
    but `models` and the caller resolves them against whatever registry it is
    holding.
    """

    tag: str
    levels: tuple[str, ...]
    reason: str
    evidence: dict = field(default_factory=dict)


def choose_drill(levels, mastery: Mastery) -> "Drill | None":
    """The drill this player needs, or ``None`` -- which is the common case.

    Only **confident** tags are eligible. Drilling a tag measured once would
    act on a single unlucky afternoon, which is the whole reason
    `MIN_OBSERVATIONS` exists; a player who has genuinely never met a tag needs
    to meet it, and that is the selection ordering's job rather than a drill's.

    Returning ``None`` rather than an empty drill, because "no drill" is an
    ordinary answer the caller has to phrase differently, not a degenerate
    queue it can render the same way.
    """
    weakest = None
    for tag in mastery.confident_tags():          # already weakest-first
        if mastery.value(tag) >= DRILL_BELOW:
            break                                  # sorted, so nothing weaker
        if any(tag in level.tags for level in levels):
            weakest = tag
            break

    if weakest is None:
        return None

    carrying = [level.id for level in levels if weakest in level.tags]
    # Cycled rather than repeated when there is more than one, so a drill on a
    # well-covered tag varies the shape of the problem instead of asking the
    # same question three times. With a single level it repeats -- and still
    # differs, because each run draws a new seed and a fresh difficulty.
    queue = tuple(carrying[index % len(carrying)] for index in range(DRILL_LENGTH))

    score = mastery.value(weakest)
    return Drill(
        tag=weakest,
        levels=queue,
        reason=(
            f"{weakest} is your weakest measured tag at {score:.0%}, so here "
            f"are {DRILL_LENGTH} runs on it"
        ),
        evidence={
            "tag": weakest,
            "mastery": round(score, 4),
            "observations": mastery[weakest].observations,
            "threshold": DRILL_BELOW,
            "levels_carrying_the_tag": carrying,
            # Said out loud because a one-level tag measures that level as
            # much as it measures the skill, and the drill cannot fix that.
            "distinct_levels": len(carrying),
        },
    )


# --------------------------------------------------------------------------
# What the model cannot tell you (T4 W7)
# --------------------------------------------------------------------------

def limits(levels, mastery: Mastery) -> list[str]:
    """The claims this model is *not* making, in the player's words.

    T4 W7 says the explanation surface is non-negotiable, and an explanation
    that only says what the game believes is half of one. These are the two
    places the numbers read as more precise than they are, and both are real
    properties of the model rather than caveats added for modesty:

    * **Every tag on a level moves together.** A level tagged
      ``("data", "algorithms")`` cannot say which of the two the player got
      right, so a tag score is about *content met*, not an isolated skill
      (Q87).
    * **A tag carried by one level measures that level.** Replaying it does
      build evidence -- enough to become confident -- but all of it is the
      same problem shape (Q88).

    Generated from the content rather than written down, so a level gaining a
    tag or a world gaining a level changes what the player is told without
    anyone remembering to edit a paragraph.
    """
    notes: list[str] = []

    multi = sorted({
        tag for level in levels if len(level.tags) > 1 for tag in level.tags
    })
    seen_multi = [tag for tag in multi if tag in mastery]
    if seen_multi:
        notes.append(
            "a level's tags all move together, so a score for "
            f"{', '.join(seen_multi[:3])} is about the levels that carry it "
            "rather than that skill on its own"
        )

    counts: dict[str, int] = {}
    for level in levels:
        for tag in level.tags:
            counts[tag] = counts.get(tag, 0) + 1
    thin = sorted(tag for tag, count in counts.items()
                  if count == 1 and tag in mastery)
    if thin:
        notes.append(
            f"{', '.join(thin)} " + ("is carried" if len(thin) == 1 else "are carried")
            + " by a single level, so the score measures that level as much "
            "as the skill"
        )

    return notes
