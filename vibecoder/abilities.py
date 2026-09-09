"""Abilities: things that spend or refill a boss fight's resources. T4 W10.

**Every ability costs something, and the cost is paid in the fight's own
currency.** T4's hazard list is blunt about why: *power creep dissolves the
boss engine.* T3 W6 made a fight cost something -- a bounded pool, a heal that
scales with how wrong the code was -- and an ability that hands repairs back
for free returns the boss to the pre-W6 state where fixing was unlimited. Exit
criterion 7 is the guard: every ability has a stated cost, and a fight with a
full loadout is **still losable**.

## What "losable" depends on

A fight is lost by failing a step with no repairs left. Hit points do not
enter into it -- a boss at full health is not a loss, it is a poor win. So the
dangerous ability is not one that damages the boss; it is one that *adds
repairs*, and `Refactor` is exactly that.

It is bounded by pricing it in **damage already dealt**. You may buy attempts
only with progress you have already made, so:

* a player failing the first step has dealt nothing and can buy nothing --
  which is precisely the player who would otherwise never lose;
* every purchase moves the boss back toward full, and once it is there the
  supply is gone.

That is the whole anti-creep argument, and `tests/test_abilities.py` tries to
build an unlosable fight with a full loadout and fails to.

## Costs are stated, not implied

Each ability carries a ``cost`` string written for the player. An ability
whose cost you have to infer from the bar moving is a difficulty setting
wearing a costume, which is the trajectory's phrase for the thing this must
not become.

Earning and equipping -- which class unlocks what, and at what mastery -- is
W11. This module is the abilities and their prices.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fight import Fight

#: What one refunded repair costs the boss, in health handed back. Priced
#: above a repair's own worst-case heal (10) would make it never worth using;
#: priced far below it would make it strictly better than being careful. Eight
#: sits just under, so buying an attempt is usually worse than not needing one.
REFACTOR_HP = 8

#: What banking one unspent repair is worth in damage. Deliberately less than
#: a repair's own damage reduction is worth: cashing out should be a decision
#: taken when the fight is already won, not a better way to fight it.
OVERCLOCK_DAMAGE = 4


class Ability:
    """One thing a player may do to a fight, and what it costs them.

    Subclasses state ``cost`` in words. `available` decides whether the fight
    can currently pay it, and `use` performs the trade and reports what it
    actually took -- *actually*, because every mutator on `Fight` clamps to
    what the fight can afford, and an ability that reported the price it asked
    for rather than the price it paid would be lying on the screen.
    """

    key: str = ""
    name: str = ""
    blurb: str = ""
    cost: str = ""

    def available(self, fight: Fight) -> bool:
        raise NotImplementedError

    def use(self, fight: Fight) -> str:
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return f"<{type(self).__name__} {self.key}>"


class Refactor(Ability):
    """Buy back a spent repair, by giving the boss health.

    The dangerous one, and the reason the whole module has a cost model: it is
    the only ability that touches the resource a fight is lost by running out
    of.
    """

    key = "refactor"
    name = "Refactor"
    blurb = "take a spent repair back"
    cost = f"the boss recovers {REFACTOR_HP}"

    def available(self, fight: Fight) -> bool:
        # Both halves matter. Nothing spent means nothing to take back, and
        # too little dealt means no progress to trade -- the second is what
        # keeps a player who is failing the first step from buying immunity.
        return fight.spent > 0 and (fight.dealt - fight._healed) >= REFACTOR_HP

    def use(self, fight: Fight) -> str:
        given = fight.concede(REFACTOR_HP)
        if not given:
            return "nothing to trade"
        returned = fight.refund(1)
        if not returned:
            return "nothing to take back"
        return f"one repair back; the boss recovers {given}"


class SteadyHand(Ability):
    """Spend a repair so that the *next* one hands the boss nothing.

    Worth it exactly when the next repair would be expensive -- code that
    passes nothing heals 10 -- and a waste when it would be cheap. That is the
    decision the ability exists to pose, and it is the same "being close is
    rewarded" argument the heal curve already makes, offered as a choice.
    """

    key = "steady"
    name = "Steady Hand"
    blurb = "the next repair heals the boss nothing"
    cost = "one repair from the pool"

    def available(self, fight: Fight) -> bool:
        # Two: one to pay with and one to protect. Spending the last repair to
        # make a repair you can no longer afford free is a trap, not a choice.
        return fight.repairs_left >= 2

    def use(self, fight: Fight) -> str:
        spent = fight.repair(accuracy=1.0)
        if spent is None:
            return "no repairs left"
        fight.waive_next_heal()
        return "the next repair costs the boss nothing"


class Overclock(Ability):
    """Cash every remaining repair in for damage, and keep none.

    The pool is emptied rather than reduced. A version that left one behind
    would be a free bonus; emptying it makes this a decision about whether the
    fight is already over.
    """

    key = "overclock"
    name = "Overclock"
    blurb = f"every repair left becomes {OVERCLOCK_DAMAGE} damage"
    cost = "every repair you have; you cannot repair again"

    def available(self, fight: Fight) -> bool:
        return fight.repairs_left > 0

    def use(self, fight: Fight) -> str:
        spent, damage = fight.bank_repairs(OVERCLOCK_DAMAGE)
        if not spent:
            return "no repairs to bank"
        return f"{spent} repairs became {damage} damage; the pool is empty"


#: Every ability, keyed. W11 decides which a player has earned; this is the
#: complete set they could be drawn from.
ALL: dict[str, Ability] = {
    ability.key: ability
    for ability in (Refactor(), SteadyHand(), Overclock())
}


def usable(fight: Fight, keys: "list[str] | tuple[str, ...]") -> list[Ability]:
    """The subset of ``keys`` this fight can currently pay for."""
    return [ALL[key] for key in keys if key in ALL and ALL[key].available(fight)]


# --------------------------------------------------------------------------
# Earning and equipping (T4 W11)
# --------------------------------------------------------------------------

"""
This is the **only** place T4's two layers are allowed to meet, and the
trajectory is precise about how: *they meet as a gate, never as an average.*

* Your **class** decides *which* abilities exist for you. It comes from how you
  write, and no amount of scoring changes it.
* Your **mastery** decides *whether* you have reached them yet. It comes from
  what you scored, and no amount of rewriting your code changes it.

The result is a set intersection -- `unlocked_by(class) & gates_met(mastery)`
-- and never an arithmetic combination. Exit criterion 8 forbids any screen
presenting a single number blending habits with mastery, and the cheapest way
to keep that true is for no such number to exist anywhere in the code path.
"""

from .mastery import Mastery


@dataclass(frozen=True)
class Gate:
    """What mastery an ability waits behind, stated in words.

    Counted in *confident* tags, never averaged into one figure. An average
    would let a player unlock something by being adequate at everything, which
    is not the same claim as having actually got good at some of it -- and
    would quietly reintroduce the single blended number criterion 8 exists to
    prevent, just on one side of the wall instead of across it.
    """

    tags: int
    at_least: float

    def met(self, mastery: Mastery) -> bool:
        strong = sum(1 for tag in mastery.confident_tags()
                     if mastery.value(tag) >= self.at_least)
        return strong >= self.tags

    def __str__(self) -> str:
        plural = "" if self.tags == 1 else "s"
        return f"{self.tags} tag{plural} measured at {self.at_least:.0%} or better"


#: Which abilities each class offers. **Every class offers exactly two**, so
#: that no class is better equipped than another -- the same rule W8 applies
#: to the classes themselves, extended to what they unlock. The pairing is
#: thematic, not a ranking: an Architect is not short of a Refactor, they have
#: a different two.
UNLOCKS: dict[str, tuple[str, ...]] = {
    "Comprehensionist": ("refactor", "overclock"),
    "Loopwright": ("refactor", "steady"),
    "Architect": ("steady", "overclock"),
    "Contractor": ("refactor", "steady"),
    "Streamwright": ("refactor", "overclock"),
    "Delegator": ("refactor", "overclock"),
}

#: What mastery each ability waits behind. Ordered by how much of a fight the
#: ability can swing: `Refactor` returns one attempt, `Overclock` decides the
#: rest of the fight in one move.
GATES: dict[str, Gate] = {
    "refactor": Gate(tags=1, at_least=0.50),
    "steady": Gate(tags=2, at_least=0.60),
    "overclock": Gate(tags=2, at_least=0.75),
}


def unlocked_by(class_name: "str | None") -> tuple[str, ...]:
    """Which abilities a class offers, before mastery is consulted.

    A player with no class gets none -- not as a penalty, but because
    abilities are *flavoured* by how you write and that is not yet known. It
    is answered by profiling a codebase, which is an invitation rather than a
    grind.
    """
    return UNLOCKS.get(class_name or "", ())


def earned(class_name: "str | None", mastery: Mastery) -> list[Ability]:
    """The abilities this player both has access to and has reached.

    An intersection, deliberately: `class` filters, `mastery` gates, and
    neither is weighted against the other. Two players with the same class and
    different mastery differ in *how many* they have; two with the same
    mastery and different classes differ in *which*. Nothing anywhere reduces
    the pair to a score.
    """
    return [
        ALL[key] for key in unlocked_by(class_name)
        if key in ALL and GATES[key].met(mastery)
    ]


def locked(class_name: "str | None", mastery: Mastery) -> list[tuple[Ability, Gate]]:
    """What this class offers that mastery has not reached yet, and why.

    Shown rather than hidden: an ability you cannot see is not a goal, and
    W7's rule -- the player can see why -- applies to a locked door as much as
    to a difficulty.
    """
    return [
        (ALL[key], GATES[key]) for key in unlocked_by(class_name)
        if key in ALL and not GATES[key].met(mastery)
    ]
