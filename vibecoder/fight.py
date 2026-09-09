"""One boss fight's resources (T3 W6).

A boss has HP, and clearing a step damages it. The damages are arranged to sum
to exactly the starting HP, so a fight cleared without a single repair takes it
to precisely zero — which is exit criterion 5 read literally: **HP reaches zero
only when every step passes.** The criterion is one-directional and is left
that way. Passing every step does not have to zero the boss, and once repairs
are in play it usually will not.

## Repairs are the other resource, and they are not HP

A repair is bounded, and spending one does two things:

- **It reduces the damage that step will deal.** A step solved on the third
  attempt should not be worth what a step solved outright is worth.
- **It heals the boss, by an amount that depends on how wrong the code was.**
  This is the part that makes the pool interesting rather than a counter. The
  heal scales with `1 - accuracy`, so repairing code that was nearly right
  costs the boss almost nothing, and repairing code that failed every case
  hands it a real recovery.

The direction matters and is deliberate: **being close is rewarded.** A player
who ships something almost correct and patches it keeps most of their damage;
a player who repairs a guess watches the bar go back up. That is the whole
game's thesis — it scores how you write, not whether you eventually arrived —
pointed at a boss fight.

## What this module will not do

Nothing here executes anything, draws anything, or reads a clock. It is
arithmetic over a small amount of state, so the rules are testable without a
sandbox, a child process or a terminal — and so that when T4 picks the pool up
as something an ability can refill, there is a plain object to refill.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: A boss starts here and the per-step damages sum to exactly this. Round, so
#: that a bar reads as a percentage without anyone having to be told it is one.
DEFAULT_HP = 100

#: Repairs a player gets for the whole fight. Five is enough to recover from a
#: bad step or two and not enough to brute-force three of them, which is the
#: band that makes the pool a decision rather than a formality. It is a
#: starting value on the `Fight`, not a constant anyone reads directly,
#: because T4's abilities exist to change it.
DEFAULT_REPAIRS = 5

#: What a step still deals after one repair, compounding. Halving is steep on
#: purpose: the second repair on one step is worth a quarter, which is what
#: stops "fix it until it passes" from scoring like solving it.
REPAIR_DAMAGE_SHARE = 0.5

#: The most one repair can heal, as a share of starting HP — reached only by
#: repairing code that passed nothing at all. Ten percent means a full pool
#: spent on guesswork hands back half the boss, and a pool spent on
#: near-misses hands back almost none.
MAX_HEAL_SHARE = 0.10


def split_damage(total: int, parts: int) -> list[int]:
    """Integer damages that sum to exactly ``total``.

    Cumulative rounding rather than ``total // parts`` with the remainder
    dropped on the last step: it keeps the steps as equal as integers allow,
    and the sum is exact by construction rather than by a correction applied
    afterwards. Exactness is the point — criterion 5 is an ``== 0``, and a
    rounding crumb left behind would make a won fight look unwon.
    """
    if parts < 1:
        raise ValueError("a boss needs at least one step")
    edges = [round(total * index / parts) for index in range(parts + 1)]
    return [edges[i + 1] - edges[i] for i in range(parts)]


@dataclass(frozen=True)
class Repair:
    """What one repair cost, for a caller that wants to show it."""

    healed: int
    accuracy: float
    remaining: int

    def __str__(self) -> str:
        if not self.healed:
            return "repaired — the boss recovers nothing"
        return f"repaired — the boss recovers {self.healed}"


@dataclass
class Fight:
    """The resources of one boss fight in progress.

    ``steps`` is how many the boss has; everything else has a starting value
    an ability could later change.
    """

    steps: int
    hp: int = DEFAULT_HP
    repairs: int = DEFAULT_REPAIRS

    _damage: list[int] = field(init=False, repr=False)
    _spent_on: dict[int, int] = field(init=False, repr=False)
    _dealt: int = field(init=False, default=0, repr=False)
    _healed: int = field(init=False, default=0, repr=False)
    _spent: int = field(init=False, default=0, repr=False)
    _pending: int = field(init=False, default=0, repr=False)
    #: Set by an ability; the next repair heals the boss nothing. Consumed on
    #: use rather than lingering, so "the next one" means exactly one.
    _heal_waived: bool = field(init=False, default=False, repr=False)

    def __post_init__(self) -> None:
        if self.steps < 1:
            raise ValueError("a boss needs at least one step")
        if self.hp < 1:
            raise ValueError("a boss needs some hit points")
        self._damage = split_damage(self.hp, self.steps)
        self._spent_on = {}

    # -- the boss ----------------------------------------------------------

    @property
    def remaining(self) -> int:
        """Hit points left, never below zero and never above the start.

        Clamped at both ends rather than allowed to drift: a bar that reads
        ``-3`` or ``104`` is a bug the player has to interpret.
        """
        return max(0, min(self.hp, self.hp - self._dealt + self._healed))

    @property
    def down(self) -> bool:
        return self.remaining == 0

    @property
    def dealt(self) -> int:
        """Damage actually dealt so far.

        Public because T4 W10's abilities are priced in it: the only thing a
        player may buy extra attempts with is progress they have already made,
        which is what stops the pool being refillable from nothing.
        """
        return self._dealt

    @property
    def cleared(self) -> int:
        return len(self._spent_on)

    @property
    def finished(self) -> bool:
        """Every step passed. Not the same as `down`, once repairs are spent."""
        return self.cleared == self.steps

    # -- the pool ----------------------------------------------------------

    @property
    def repairs_left(self) -> int:
        return max(0, self.repairs - self._spent)

    @property
    def spent(self) -> int:
        return self._spent

    @property
    def can_repair(self) -> bool:
        return self.repairs_left > 0

    @property
    def flawless(self) -> bool:
        """Every step cleared, nothing spent. The only way to reach zero."""
        return self.finished and self._spent == 0

    @property
    def first_try(self) -> int:
        """Steps cleared without spending anything on them."""
        return sum(1 for used in self._spent_on.values() if used == 0)

    def spent_on(self, index: int) -> int:
        """Repairs spent on a cleared step, or on the one in progress."""
        if index in self._spent_on:
            return self._spent_on[index]
        return self._pending

    # -- playing -----------------------------------------------------------

    def damage_for(self, index: int) -> int:
        """What clearing step ``index`` would deal, as things stand.

        Reads the repairs already spent on it, so a caller can show the cost
        of a repair *before* the step is cleared rather than only after.
        """
        base = self._damage[index]
        used = self.spent_on(index)
        return int(round(base * (REPAIR_DAMAGE_SHARE ** used)))

    def heal_for(self, accuracy: float) -> int:
        """What a repair would hand back, at this accuracy.

        Separate from `repair` so a caller can warn before spending. Rounded
        up from a non-zero share, because a heal that displays as ``0`` while
        the bar moves is worse than a heal of one.
        """
        miss = max(0.0, min(1.0, 1.0 - accuracy))
        exact = self.hp * MAX_HEAL_SHARE * miss
        if exact <= 0:
            return 0
        return max(1, int(round(exact)))

    def repair(self, accuracy: float = 0.0) -> Repair | None:
        """Spend one repair. ``None`` when there are none left.

        Returning ``None`` rather than raising, because running out is an
        ordinary end to a fight and the caller has to say so either way. When
        it returns ``None`` **nothing has changed** — no heal, no spend — so a
        caller that forgets to check has not silently half-applied one.
        """
        if not self.can_repair:
            return None
        self._spent += 1
        self._pending += 1
        if self._heal_waived:
            # Consumed here rather than at the ability's call site, so "the
            # next repair" cannot quietly become "every repair from now on".
            self._heal_waived = False
            healed = 0
        else:
            healed = self.heal_for(accuracy)
        self._healed += healed
        return Repair(healed=healed, accuracy=accuracy,
                      remaining=self.repairs_left)

    # -- what an ability may do (T4 W10) -----------------------------------
    #
    # These exist so `abilities.py` never reaches into the private fields
    # above. Every one of them can *only* move the fight in a direction some
    # cost has already paid for; the pricing lives with the abilities, and the
    # arithmetic that must stay consistent lives here.

    def refund(self, count: int = 1) -> int:
        """Hand back spent repairs. Returns how many were actually returned.

        Bounded by what was spent, because a pool that can be refilled past
        its starting size is not a pool. This is the method the power-creep
        hazard is about, which is why it cannot mint anything on its own.
        """
        count = max(0, min(count, self._spent))
        self._spent -= count
        return count

    def concede(self, hp: int) -> int:
        """Give the boss health back. Returns how much it actually took.

        Capped at the damage dealt so far: you can only return what you took.
        A fight that has dealt nothing cannot concede anything, which is
        exactly the player -- failing the first step -- who would otherwise
        buy their way out of ever losing.
        """
        hp = max(0, min(hp, self._dealt - self._healed))
        self._healed += hp
        return hp

    def waive_next_heal(self) -> None:
        """The next repair hands the boss nothing back."""
        self._heal_waived = True

    def bank_repairs(self, per_repair: int) -> tuple[int, int]:
        """Spend every remaining repair as damage. Returns (spent, damage).

        The pool is emptied, not reduced: this is the ability that trades the
        whole rest of the fight for immediate progress, and leaving a repair
        behind would make it a free bonus instead of a decision.
        """
        available = self.repairs_left
        if available <= 0:
            return (0, 0)
        self._spent += available
        damage = available * per_repair
        self._dealt += damage
        return (available, damage)

    def clear(self, index: int) -> int:
        """Mark a step passed and deal its damage. Returns what it dealt.

        Clearing a step twice deals nothing the second time. A caller that
        retries a step after a repair would otherwise damage the boss once per
        attempt, which is the opposite of what the pool is for.
        """
        if index in self._spent_on:
            return 0
        damage = self.damage_for(index)
        self._spent_on[index] = self._pending
        self._pending = 0
        self._dealt += damage
        return damage
