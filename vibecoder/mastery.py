"""What the player is good at, per content tag. T4 W1 and W3.

**This is not the Vibe Vector, and the two must never be averaged.** The
vector measures *how you write*, read statically from your own code. This
measures *what you score*, from runs you actually played. T4's hazard list
names conflating them as the most tempting and most wrong simplification
available in the trajectory, and exit criterion 8 forbids any screen showing a
single number blending them. Keeping them in separate modules with no import
between them is the cheapest enforcement available.

Like [`fight.py`](fight.py), this module **imports nothing**. It is arithmetic
over a small amount of state, so the rules are testable without a sandbox, a
level, or a profile on disk -- and the update rule takes plain numbers rather
than a `ScoreBreakdown` so that staying dependency-free costs the caller one
line instead of costing this module its independence.

## Why an explicit model rather than a learned one

The design document called for "machine-learning based on user performance".
With a handful of levels and one player there is no training set: a model
would be fitting noise, and -- worse -- would be impossible to explain when it
made a bad call. T4 W7 requires every difficulty decision to be explainable in
one sentence with no hidden state, which an exponentially-weighted average of
three named terms can do and a fitted model cannot. Learn something
statistically once there is data worth learning from, and measure this first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Where a tag sits before anything has been observed. The middle, because an
#: unplayed tag is *unknown*, not bad -- starting at zero would tell a new
#: player they are weak at everything on the evidence of nothing.
UNSEEN = 0.5

#: Runs on a tag before its estimate may drive a decision. T4's tag-sparsity
#: hazard calls for this directly: with 14 tags across 12 levels several tags
#: have exactly one level, so a single lucky or unlucky run would otherwise
#: steer content on its own. Below this the caller falls back to the Vibe
#: Vector, which is what `confident` exists to make impossible to forget.
MIN_OBSERVATIONS = 3

#: How far each run moves the estimate. T4 specifies ~0.3, and the value is
#: doing two jobs at once: high enough that recent evidence dominates a stale
#: rating, low enough that one bad afternoon does not erase a month. It also
#: bounds the per-level step change, which is the trajectory's first hazard --
#: a death spiral in either direction needs a step size big enough to run away
#: with, and 0.3 caps a single run's influence at under a third of the gap.
ALPHA = 0.3

#: What an observation is made of. Accuracy dominates because a wrong answer
#: is not competence; functional efficiency is the second signal because doing
#: the work well is the thing the game is actually about; first-try is a small
#: bonus rather than a third of the weight, because it is the noisiest of the
#: three and the easiest to game by re-reading the brief before submitting.
#:
#: These are **not** the three scoring axes and must not be kept in step with
#: them. Speed is deliberately absent: solve time measures a session, not a
#: competence, and a player interrupted by a phone call is not worse at
#: recursion afterwards.
ACCURACY_WEIGHT = 0.5
FUNCTIONAL_WEIGHT = 0.3
FIRST_TRY_WEIGHT = 0.2


def observation(accuracy: float, functional: float, first_try: bool) -> float:
    """One run, reduced to a single 0..1 competence signal.

    ``accuracy`` and ``functional`` are the 0..100 axis values a run scored.
    Plain numbers rather than a `ScoreBreakdown`, so this module stays
    importless -- and so that a caller cannot pass a *boss* breakdown by
    accident and have it silently mean the same thing, which is a live
    question rather than a hypothetical one (Q84).
    """
    return max(0.0, min(1.0,
        ACCURACY_WEIGHT * (max(0.0, min(100.0, accuracy)) / 100.0)
        + FUNCTIONAL_WEIGHT * (max(0.0, min(100.0, functional)) / 100.0)
        + FIRST_TRY_WEIGHT * (1.0 if first_try else 0.0)
    ))


@dataclass
class TagMastery:
    """One tag's competency estimate, and the evidence behind it.

    ``value`` alone cannot be read honestly, which is why ``observations``
    sits beside it and every accessor pairs them. A tag at ``0.5`` after four
    runs is a measurement; a tag at ``0.5`` after none is the absence of one,
    and they must not be shown or acted on as the same thing.
    """

    value: float = UNSEEN
    observations: int = 0
    #: ISO-8601 UTC, set whenever `value` moves. Empty until then. T4 W6's
    #: decay needs to know *when* the evidence was gathered, not only what it
    #: said, and a field added later would be empty for exactly the returning
    #: players decay exists to re-assess.
    updated_at: str = ""

    def __post_init__(self) -> None:
        # Clamped rather than trusted: this round-trips through a JSON file the
        # player is invited to inspect, and a value outside 0..1 would
        # propagate into every comparison that reads it.
        self.value = max(0.0, min(1.0, float(self.value)))
        self.observations = max(0, int(self.observations))

    @property
    def confident(self) -> bool:
        """Whether this estimate has enough evidence to act on."""
        return self.observations >= MIN_OBSERVATIONS

    @property
    def seen(self) -> bool:
        """Whether anything has been observed at all."""
        return self.observations > 0

    def to_json(self) -> dict[str, Any]:
        return {
            "value": round(self.value, 4),
            "observations": self.observations,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "TagMastery":
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Mastery:
    """Per-tag competency, updated after every ranked run.

    Reading is total: asking for a tag never invents an entry. That keeps
    "have I seen this tag" answerable, which `confident` and T4 W4's selection
    policy both depend on.
    """

    tags: dict[str, TagMastery] = field(default_factory=dict)

    # -- reading -----------------------------------------------------------

    def __getitem__(self, tag: str) -> TagMastery:
        """The estimate for ``tag``, or a fresh unseen one. Never stored."""
        return self.tags.get(tag, TagMastery())

    def __contains__(self, tag: str) -> bool:
        return tag in self.tags

    def __len__(self) -> int:
        return len(self.tags)

    def value(self, tag: str) -> float:
        return self[tag].value

    def confident(self, tag: str) -> bool:
        return self[tag].confident

    def known_tags(self) -> list[str]:
        """Tags with any evidence at all, weakest first.

        Ordered here so a caller wanting the weakest tag -- T4 W5's drill
        injection -- does not re-derive the ordering and get the tie rule
        subtly different. Ties break on the tag name, so the result is stable
        across runs rather than dependent on dict insertion order.
        """
        return sorted(
            (tag for tag, entry in self.tags.items() if entry.seen),
            key=lambda tag: (self.tags[tag].value, tag),
        )

    def confident_tags(self) -> list[str]:
        """Tags with enough evidence to act on, weakest first."""
        return [tag for tag in self.known_tags() if self.tags[tag].confident]

    # -- updating ----------------------------------------------------------

    def observe(self, tags: "list[str] | tuple[str, ...]", observed: float,
                *, at: str = "") -> dict[str, float]:
        """Move every tag toward ``observed``. Returns what each one moved by.

        The move is exponentially weighted --
        ``value += ALPHA * (observed - value)`` -- so recent evidence
        dominates without a single bad run erasing history, and the step is
        bounded by construction, which is what keeps the first hazard's death
        spiral from being reachable in one level.

        **Every tag on the level gets the same observation**, which is a real
        limitation and not a rounding of one: a level tagged
        ``("data", "algorithms")`` cannot tell which of the two the player
        actually got right. The estimate is therefore about *content the
        player met*, not about an isolated skill, and W7's explanation has to
        say so rather than implying a precision the model does not have.

        Returns the deltas so a caller can explain the update without
        recomputing it, which is the whole of T4 W7's requirement that there
        be no hidden state.
        """
        observed = max(0.0, min(1.0, observed))
        moves: dict[str, float] = {}
        for tag in tags:
            entry = self.tags.setdefault(tag, TagMastery())
            before = entry.value
            entry.value = max(0.0, min(1.0, before + ALPHA * (observed - before)))
            entry.observations += 1
            if at:
                entry.updated_at = at
            moves[tag] = round(entry.value - before, 6)
        return moves

    # -- serialisation -----------------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {tag: entry.to_json() for tag, entry in sorted(self.tags.items())}

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "Mastery":
        if not isinstance(data, dict):
            return cls()
        return cls(
            tags={
                tag: TagMastery.from_json(entry)
                for tag, entry in data.items()
                if isinstance(entry, dict)
            }
        )
