"""Abilities, and the fight they must not dissolve. T4 W10.

Exit criterion 7: **every ability has a stated cost, and a fight with
abilities available is still losable.** The second half is the one with teeth,
and `TestAFightIsStillLosable` is an adversarial simulation rather than an
assertion: a player who cannot solve a step uses every ability as well as it
can be used, and still runs out.

T4's hazard names the failure exactly -- *power creep dissolves the boss
engine* -- so the interesting tests here are the ones that try to break it.
"""

import unittest

from vibecoder.abilities import (
    ALL,
    GATES,
    UNLOCKS,
    OVERCLOCK_DAMAGE,
    REFACTOR_HP,
    Overclock,
    Refactor,
    SteadyHand,
    earned,
    locked,
    unlocked_by,
    usable,
)
from vibecoder.fight import DEFAULT_REPAIRS, Fight
from vibecoder.mastery import Mastery


def fight_with_progress(steps: int = 3, cleared: int = 2) -> Fight:
    """A fight partway through, so there is damage dealt to trade."""
    fight = Fight(steps=steps)
    for index in range(cleared):
        fight.clear(index)
    return fight


class TestEveryAbilityStatesItsCost(unittest.TestCase):
    """The first half of criterion 7. An ability whose cost you have to infer
    from the bar moving is a difficulty setting wearing a costume."""

    def test_every_ability_has_a_cost_in_words(self):
        for key, ability in ALL.items():
            with self.subTest(ability=key):
                self.assertTrue(ability.cost)
                self.assertGreater(len(ability.cost), 8)

    def test_every_ability_has_a_name_and_a_blurb(self):
        for key, ability in ALL.items():
            with self.subTest(ability=key):
                self.assertTrue(ability.name)
                self.assertTrue(ability.blurb)

    def test_no_ability_is_free(self):
        """Each one must leave the fight measurably worse off somewhere:
        fewer repairs, or more boss health."""
        for key, ability in ALL.items():
            with self.subTest(ability=key):
                fight = fight_with_progress()
                fight.repair(0.5)
                before = (fight.repairs_left, fight.remaining)
                if not ability.available(fight):
                    continue
                ability.use(fight)
                after = (fight.repairs_left, fight.remaining)
                self.assertNotEqual(before, after)
                # Worse on at least one axis: fewer repairs or a healthier boss.
                self.assertTrue(
                    after[0] < before[0] or after[1] > before[1],
                    f"{key} cost nothing: {before} -> {after}",
                )


class TestRefactor(unittest.TestCase):
    def test_it_returns_a_spent_repair(self):
        fight = fight_with_progress()
        fight.repair(0.5)
        spent = fight.repairs_left
        Refactor().use(fight)
        self.assertEqual(fight.repairs_left, spent + 1)

    def test_it_gives_the_boss_health_back(self):
        fight = fight_with_progress()
        fight.repair(0.5)
        before = fight.remaining
        Refactor().use(fight)
        self.assertEqual(fight.remaining, before + REFACTOR_HP)

    def test_it_is_unavailable_with_nothing_spent(self):
        """Nothing to take back."""
        self.assertFalse(Refactor().available(fight_with_progress()))

    def test_it_is_unavailable_with_no_progress_to_trade(self):
        """The anti-creep rule: a player failing the first step has dealt
        nothing, and is exactly the one who would otherwise buy immunity."""
        fight = Fight(steps=3)
        fight.repair(0.5)
        self.assertEqual(fight.dealt, 0)
        self.assertFalse(Refactor().available(fight))

    def test_the_pool_can_never_exceed_its_starting_size(self):
        """A pool refillable past its start is not a pool."""
        fight = fight_with_progress()
        fight.repair(0.5)
        for _ in range(20):
            if Refactor().available(fight):
                Refactor().use(fight)
        self.assertLessEqual(fight.repairs_left, DEFAULT_REPAIRS)

    def test_the_supply_runs_out_as_the_boss_returns_to_full(self):
        """Every purchase moves the boss back toward full, and once it is
        there there is nothing left to sell."""
        fight = fight_with_progress()
        uses = 0
        for _ in range(50):
            fight.repair(0.5)
            if not Refactor().available(fight):
                break
            Refactor().use(fight)
            uses += 1
        self.assertGreater(uses, 0)
        self.assertFalse(Refactor().available(fight))


class TestSteadyHand(unittest.TestCase):
    def test_the_next_repair_heals_nothing(self):
        fight = fight_with_progress()
        SteadyHand().use(fight)
        before = fight.remaining
        fight.repair(accuracy=0.0)      # the worst case: a full 10 heal
        self.assertEqual(fight.remaining, before)

    def test_only_the_next_one(self):
        """"The next repair" must not quietly become "every repair"."""
        fight = fight_with_progress()
        SteadyHand().use(fight)
        fight.repair(accuracy=0.0)
        before = fight.remaining
        fight.repair(accuracy=0.0)
        self.assertGreater(fight.remaining, before)

    def test_it_costs_a_repair(self):
        fight = fight_with_progress()
        before = fight.repairs_left
        SteadyHand().use(fight)
        self.assertEqual(fight.repairs_left, before - 1)

    def test_it_needs_two_repairs_to_be_worth_using(self):
        """Spending the last repair to make a repair you can no longer afford
        free is a trap rather than a choice."""
        fight = Fight(steps=3, repairs=1)
        self.assertFalse(SteadyHand().available(fight))


class TestOverclock(unittest.TestCase):
    def test_it_converts_the_whole_pool(self):
        fight = fight_with_progress(cleared=0)
        Overclock().use(fight)
        self.assertEqual(fight.repairs_left, 0)

    def test_the_damage_is_what_was_advertised(self):
        fight = fight_with_progress(cleared=0)
        before = fight.remaining
        Overclock().use(fight)
        self.assertEqual(before - fight.remaining,
                         DEFAULT_REPAIRS * OVERCLOCK_DAMAGE)

    def test_it_leaves_nothing_behind(self):
        """A version that kept one repair would be a free bonus rather than a
        decision about whether the fight is already over."""
        fight = fight_with_progress(cleared=0)
        Overclock().use(fight)
        self.assertFalse(fight.can_repair)

    def test_it_is_unavailable_with_an_empty_pool(self):
        fight = Fight(steps=3, repairs=0)
        self.assertFalse(Overclock().available(fight))


class TestAFightIsStillLosable(unittest.TestCase):
    """Criterion 7's second half, and T4's power-creep hazard.

    Not an assertion but an attempt: a player who cannot solve the last step
    plays every ability as well as it can be played, and the question is
    whether the fight ever ends. If `Refactor` were free -- or priced in
    anything the fight cannot run out of -- these loops would not terminate,
    which is what makes them a guard rather than a restatement.
    """

    LIMIT = 500

    def grind(self, fight: Fight, keys) -> int:
        """Fail the last step forever, repairing and refactoring to survive.

        Returns the number of attempts survived. Terminating at all is the
        result under test.
        """
        attempts = 0
        while attempts < self.LIMIT:
            if fight.can_repair:
                fight.repair(accuracy=0.0)   # never learning, worst case
                attempts += 1
                continue
            options = usable(fight, keys)
            revived = False
            for ability in options:
                if ability.key == "refactor":
                    ability.use(fight)
                    revived = True
                    break
            if not revived:
                return attempts
        return -1        # never ran out: the hazard has happened

    def test_a_full_loadout_still_runs_out(self):
        fight = fight_with_progress(cleared=2)
        survived = self.grind(fight, list(ALL))
        self.assertGreater(survived, 0)
        self.assertNotEqual(survived, -1, "a fight with abilities never ended")

    def test_it_runs_out_even_after_a_nearly_perfect_fight(self):
        """The most resources a player can possibly arrive with: every step
        cleared first try, so the maximum damage is available to trade."""
        fight = Fight(steps=3)
        for index in range(3):
            fight.clear(index)
        survived = self.grind(fight, list(ALL))
        self.assertNotEqual(survived, -1)

    def test_abilities_buy_more_attempts_than_no_abilities(self):
        """The paired positive. If they bought nothing the fight would be
        trivially losable and the guard would prove nothing."""
        without = self.grind(fight_with_progress(cleared=2), [])
        with_them = self.grind(fight_with_progress(cleared=2), list(ALL))
        self.assertGreater(with_them, without)

    def test_the_boss_is_at_full_health_by_the_time_they_are_out(self):
        """What the extra attempts cost: every point of progress, sold back."""
        fight = fight_with_progress(cleared=2)
        self.grind(fight, list(ALL))
        self.assertEqual(fight.remaining, fight.hp)

    def test_a_player_failing_the_first_step_gets_no_reprieve_at_all(self):
        """No progress means nothing to trade, so the loadout changes nothing
        for the player who has achieved nothing."""
        bare = self.grind(Fight(steps=3), [])
        loaded = self.grind(Fight(steps=3), list(ALL))
        self.assertEqual(bare, loaded)


if __name__ == "__main__":
    unittest.main()


class TestEarningAndEquipping(unittest.TestCase):
    """T4 W11. The one place the two layers meet, and they meet as a gate.

    Class decides *which*, mastery decides *whether*, and nothing anywhere
    reduces the pair to a number -- which is exit criterion 8 held at the one
    seam that could break it.
    """

    def mastery_with(self, **tags) -> Mastery:
        mastery = Mastery()
        for tag, value in tags.items():
            for _ in range(30):        # well past the confidence threshold
                mastery.observe((tag,), value)
        return mastery

    # -- no class is better equipped than another -------------------------

    def test_every_class_offers_the_same_number(self):
        """The W8 rule extended: an Architect is not short of a Refactor,
        they have a different two."""
        counts = {len(keys) for keys in UNLOCKS.values()}
        self.assertEqual(counts, {2})

    def test_every_class_in_the_rules_exists(self):
        from vibecoder.profiler import CLASS_RULES

        self.assertEqual(set(UNLOCKS), {name for name, _, _ in CLASS_RULES})

    def test_every_unlocked_key_is_a_real_ability(self):
        for name, keys in UNLOCKS.items():
            for key in keys:
                with self.subTest(cls=name, ability=key):
                    self.assertIn(key, ALL)

    def test_every_ability_is_offered_by_someone(self):
        """An ability no class can reach is decoration."""
        offered = {key for keys in UNLOCKS.values() for key in keys}
        self.assertEqual(offered, set(ALL))

    # -- the gate ---------------------------------------------------------

    def test_nothing_is_earned_without_mastery(self):
        self.assertEqual(earned("Comprehensionist", Mastery()), [])

    def test_a_gate_opens_when_it_is_met(self):
        one = self.mastery_with(data=0.9)
        keys = [ability.key for ability in earned("Comprehensionist", one)]
        self.assertIn("refactor", keys)

    def test_a_harder_gate_needs_more(self):
        one = self.mastery_with(data=0.9)
        two = self.mastery_with(data=0.9, algorithms=0.9)
        self.assertNotIn("overclock",
                         [a.key for a in earned("Comprehensionist", one)])
        self.assertIn("overclock",
                      [a.key for a in earned("Comprehensionist", two)])

    def test_a_gate_counts_confident_tags_and_never_averages_them(self):
        """An average would let a player unlock something by being adequate at
        everything, which is a different claim -- and would reintroduce the
        blended number on one side of the wall."""
        broad = self.mastery_with(a=0.55, b=0.55, c=0.55, d=0.55, e=0.55)
        self.assertFalse(GATES["overclock"].met(broad))
        deep = self.mastery_with(a=0.9, b=0.9)
        self.assertTrue(GATES["overclock"].met(deep))

    def test_a_thinly_evidenced_tag_does_not_open_a_gate(self):
        mastery = Mastery()
        mastery.observe(("data",), 1.0)      # one run only
        self.assertFalse(GATES["refactor"].met(mastery))

    def test_every_gate_states_itself_in_words(self):
        for key, gate in GATES.items():
            with self.subTest(ability=key):
                self.assertIn("tag", str(gate))
                self.assertIn("%", str(gate))

    # -- a gate, never an average -----------------------------------------

    def test_mastery_never_changes_which_abilities_a_class_offers(self):
        """Half of criterion 8 at this seam: scoring more cannot hand you a
        different class's abilities."""
        for mastery in (Mastery(), self.mastery_with(a=0.99, b=0.99, c=0.99)):
            with self.subTest():
                self.assertEqual(unlocked_by("Architect"), ("steady", "overclock"))

    def test_the_class_never_changes_what_a_gate_requires(self):
        """The other half: rewriting your code cannot lower a bar."""
        before = str(GATES["overclock"])
        earned("Loopwright", self.mastery_with(a=0.9, b=0.9))
        earned("Delegator", self.mastery_with(a=0.1))
        self.assertEqual(str(GATES["overclock"]), before)

    def test_earned_is_exactly_the_intersection(self):
        mastery = self.mastery_with(a=0.9, b=0.9)
        for name, keys in UNLOCKS.items():
            with self.subTest(cls=name):
                expected = [k for k in keys if GATES[k].met(mastery)]
                self.assertEqual([a.key for a in earned(name, mastery)], expected)

    def test_two_classes_at_the_same_mastery_differ_only_in_which(self):
        mastery = self.mastery_with(a=0.9, b=0.9)
        comp = {a.key for a in earned("Comprehensionist", mastery)}
        arch = {a.key for a in earned("Architect", mastery)}
        self.assertNotEqual(comp, arch)
        self.assertEqual(len(comp), len(arch))

    def test_no_function_here_returns_a_combined_score(self):
        """Criterion 8 by signature: there is no number to display."""
        mastery = self.mastery_with(a=0.9, b=0.9)
        self.assertIsInstance(earned("Comprehensionist", mastery), list)
        self.assertIsInstance(unlocked_by("Comprehensionist"), tuple)

    # -- no class ---------------------------------------------------------

    def test_no_class_offers_nothing(self):
        self.assertEqual(unlocked_by(None), ())
        self.assertEqual(earned(None, self.mastery_with(a=0.99, b=0.99)), [])

    def test_an_unknown_class_name_is_not_an_error(self):
        """A profile written by a build with classes this one has never heard
        of must not crash the character sheet."""
        self.assertEqual(unlocked_by("Metaprogrammer"), ())

    # -- what is still locked ---------------------------------------------

    def test_locked_reports_what_is_missing_and_why(self):
        """An ability you cannot see is not a goal."""
        waiting = locked("Comprehensionist", self.mastery_with(data=0.9))
        keys = {ability.key for ability, _ in waiting}
        self.assertEqual(keys, {"overclock"})
        self.assertIn("75%", str(waiting[0][1]))

    def test_earned_and_locked_partition_what_the_class_offers(self):
        mastery = self.mastery_with(data=0.9)
        for name in UNLOCKS:
            with self.subTest(cls=name):
                have = {a.key for a in earned(name, mastery)}
                waiting = {a.key for a, _ in locked(name, mastery)}
                self.assertEqual(have | waiting, set(UNLOCKS[name]))
                self.assertEqual(have & waiting, set())
