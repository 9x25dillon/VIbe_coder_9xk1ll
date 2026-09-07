"""Boss HP and the repair pool (T3 W6).

Arithmetic over a small amount of state, so all of it runs without a sandbox,
a child process or a terminal. The rules are the waypoint; the drawing is
`test_cli_output`'s problem and the engine is `test_stepping`'s.

The property worth stating first: **the per-step damages sum to exactly the
starting HP.** T3's exit criterion 5 is an `== 0`, so a rounding crumb left
behind anywhere in here would make a won fight look unwon.
"""

import unittest

from vibecoder.fight import (
    DEFAULT_HP,
    DEFAULT_REPAIRS,
    Fight,
    MAX_HEAL_SHARE,
    REPAIR_DAMAGE_SHARE,
    split_damage,
)


class TestTheDamageAddsUp(unittest.TestCase):
    def test_it_sums_to_the_total_however_it_divides(self):
        for parts in range(1, 33):
            with self.subTest(parts=parts):
                self.assertEqual(sum(split_damage(100, parts)), 100)

    def test_it_sums_for_awkward_totals_too(self):
        for total in (7, 13, 99, 100, 251, 1000):
            for parts in (2, 3, 5, 7, 11):
                with self.subTest(total=total, parts=parts):
                    self.assertEqual(sum(split_damage(total, parts)), total)

    def test_the_steps_are_as_equal_as_integers_allow(self):
        damages = split_damage(100, 3)
        self.assertEqual(max(damages) - min(damages), 1)

    def test_a_boss_needs_at_least_one_step(self):
        with self.assertRaises(ValueError):
            split_damage(100, 0)


class TestAFlawlessFight(unittest.TestCase):
    """Exit criterion 5, in the direction it actually constrains."""

    def test_clearing_every_step_reaches_exactly_zero(self):
        for steps in range(1, 13):
            with self.subTest(steps=steps):
                fight = Fight(steps=steps)
                for index in range(steps):
                    fight.clear(index)
                self.assertEqual(fight.remaining, 0)

    def test_zero_is_reached_only_by_clearing_everything(self):
        fight = Fight(steps=4)
        for index in range(3):
            fight.clear(index)
            self.assertGreater(fight.remaining, 0)
        fight.clear(3)
        self.assertEqual(fight.remaining, 0)

    def test_the_order_steps_are_cleared_in_does_not_matter(self):
        fight = Fight(steps=5)
        for index in (3, 0, 4, 1, 2):
            fight.clear(index)
        self.assertTrue(fight.down)

    def test_a_flawless_fight_says_so(self):
        fight = Fight(steps=3)
        for index in range(3):
            fight.clear(index)
        self.assertTrue(fight.flawless)
        self.assertEqual(fight.first_try, 3)

    def test_an_unfinished_fight_is_not_flawless(self):
        fight = Fight(steps=3)
        fight.clear(0)
        self.assertFalse(fight.flawless)


class TestARepairCosts(unittest.TestCase):
    def test_it_reduces_what_that_step_deals(self):
        fight = Fight(steps=2)
        full = fight.damage_for(0)
        fight.repair(1.0)
        self.assertEqual(fight.damage_for(0), round(full * REPAIR_DAMAGE_SHARE))

    def test_repairs_compound_on_one_step(self):
        fight = Fight(steps=2)
        full = fight.damage_for(0)
        fight.repair(1.0)
        fight.repair(1.0)
        self.assertEqual(
            fight.damage_for(0), round(full * REPAIR_DAMAGE_SHARE ** 2)
        )

    def test_a_repair_on_one_step_does_not_touch_another(self):
        fight = Fight(steps=3)
        untouched = fight.damage_for(1)
        fight.repair(1.0)
        fight.clear(0)
        self.assertEqual(fight.damage_for(1), untouched)

    def test_a_repaired_fight_cannot_reach_zero(self):
        """Which is the point: finishing and acing are different outcomes."""
        fight = Fight(steps=3)
        fight.repair(0.5)
        for index in range(3):
            fight.clear(index)
        self.assertTrue(fight.finished)
        self.assertFalse(fight.down)
        self.assertGreater(fight.remaining, 0)

    def test_it_comes_out_of_the_pool(self):
        fight = Fight(steps=2, repairs=3)
        fight.repair(1.0)
        self.assertEqual(fight.repairs_left, 2)
        self.assertEqual(fight.spent, 1)

    def test_a_step_cleared_after_a_repair_is_not_a_first_try(self):
        fight = Fight(steps=2)
        fight.repair(1.0)
        fight.clear(0)
        fight.clear(1)
        self.assertEqual(fight.first_try, 1)
        self.assertEqual(fight.spent_on(0), 1)
        self.assertEqual(fight.spent_on(1), 0)


class TestTheHealScalesWithAccuracy(unittest.TestCase):
    """The direction is the design: being close is rewarded. Repairing code
    that was nearly right costs the boss almost nothing; repairing a guess
    hands it a real recovery."""

    def test_perfect_accuracy_heals_nothing(self):
        self.assertEqual(Fight(steps=2).heal_for(1.0), 0)

    def test_nothing_passing_heals_the_most(self):
        fight = Fight(steps=2)
        self.assertEqual(fight.heal_for(0.0), round(DEFAULT_HP * MAX_HEAL_SHARE))

    def test_being_closer_always_costs_less(self):
        fight = Fight(steps=2)
        heals = [fight.heal_for(a / 10) for a in range(11)]
        self.assertEqual(heals, sorted(heals, reverse=True))

    def test_a_near_miss_still_costs_something_rather_than_nothing(self):
        """A heal that displays as 0 while the bar moves is worse than 1."""
        self.assertEqual(Fight(steps=2).heal_for(0.99), 1)

    def test_the_heal_actually_reaches_the_boss(self):
        fight = Fight(steps=2)
        fight.clear(0)
        before = fight.remaining
        cost = fight.repair(0.0)
        self.assertEqual(fight.remaining, before + cost.healed)

    def test_accuracy_outside_zero_to_one_is_clamped(self):
        fight = Fight(steps=2)
        self.assertEqual(fight.heal_for(2.0), 0)
        self.assertEqual(fight.heal_for(-1.0), fight.heal_for(0.0))

    def test_healing_never_exceeds_the_starting_health(self):
        fight = Fight(steps=2, repairs=20)
        for _ in range(20):
            fight.repair(0.0)
        self.assertEqual(fight.remaining, DEFAULT_HP)

    def test_the_repair_reports_what_it_cost(self):
        cost = Fight(steps=2).repair(0.25)
        self.assertEqual(cost.accuracy, 0.25)
        self.assertGreater(cost.healed, 0)
        self.assertIn("recovers", str(cost))

    def test_a_free_repair_reads_as_one(self):
        self.assertIn("nothing", str(Fight(steps=2).repair(1.0)))


class TestRunningOut(unittest.TestCase):
    def test_the_pool_is_bounded(self):
        fight = Fight(steps=2, repairs=2)
        self.assertIsNotNone(fight.repair(0.0))
        self.assertIsNotNone(fight.repair(0.0))
        self.assertIsNone(fight.repair(0.0))

    def test_a_refused_repair_changes_nothing(self):
        """A caller that forgets to check must not have half-applied one."""
        fight = Fight(steps=2, repairs=1)
        fight.repair(0.0)
        state = (fight.remaining, fight.spent, fight.damage_for(0))
        self.assertIsNone(fight.repair(0.0))
        self.assertEqual((fight.remaining, fight.spent, fight.damage_for(0)), state)

    def test_can_repair_says_so_before_it_is_tried(self):
        fight = Fight(steps=2, repairs=1)
        self.assertTrue(fight.can_repair)
        fight.repair(0.0)
        self.assertFalse(fight.can_repair)

    def test_a_fight_can_start_with_no_repairs_at_all(self):
        fight = Fight(steps=2, repairs=0)
        self.assertFalse(fight.can_repair)
        self.assertIsNone(fight.repair(0.0))

    def test_repairs_left_never_goes_negative(self):
        fight = Fight(steps=2, repairs=1)
        for _ in range(5):
            fight.repair(0.0)
        self.assertEqual(fight.repairs_left, 0)


class TestClearingIsIdempotent(unittest.TestCase):
    def test_clearing_a_step_twice_deals_nothing_the_second_time(self):
        """A retry after a repair would otherwise damage the boss once per
        attempt, which is the opposite of what the pool is for."""
        fight = Fight(steps=3)
        first = fight.clear(0)
        self.assertGreater(first, 0)
        self.assertEqual(fight.clear(0), 0)

    def test_the_health_is_unchanged_by_the_second_clear(self):
        fight = Fight(steps=3)
        fight.clear(0)
        after = fight.remaining
        fight.clear(0)
        self.assertEqual(fight.remaining, after)

    def test_the_step_count_is_unchanged_by_the_second_clear(self):
        fight = Fight(steps=3)
        fight.clear(0)
        fight.clear(0)
        self.assertEqual(fight.cleared, 1)


class TestTheBarNeverLies(unittest.TestCase):
    def test_health_never_goes_below_zero(self):
        fight = Fight(steps=1)
        fight.clear(0)
        self.assertEqual(fight.remaining, 0)

    def test_health_never_rises_above_the_start(self):
        fight = Fight(steps=2, repairs=5)
        fight.repair(0.0)
        self.assertLessEqual(fight.remaining, DEFAULT_HP)

    def test_finished_and_down_are_different_questions(self):
        fight = Fight(steps=2)
        fight.repair(0.0)
        fight.clear(0)
        fight.clear(1)
        self.assertTrue(fight.finished)
        self.assertFalse(fight.down)


class TestTheStartingValues(unittest.TestCase):
    """Starting values on the object, not constants read directly -- T4's
    abilities exist to change them."""

    def test_a_fight_can_be_given_a_different_pool(self):
        self.assertEqual(Fight(steps=2, repairs=9).repairs_left, 9)

    def test_a_fight_can_be_given_different_health(self):
        fight = Fight(steps=2, hp=40)
        fight.clear(0)
        fight.clear(1)
        self.assertEqual(fight.remaining, 0)

    def test_the_defaults_are_what_the_boss_command_uses(self):
        fight = Fight(steps=3)
        self.assertEqual(fight.remaining, DEFAULT_HP)
        self.assertEqual(fight.repairs_left, DEFAULT_REPAIRS)

    def test_a_boss_with_no_steps_is_refused(self):
        with self.assertRaises(ValueError):
            Fight(steps=0)

    def test_a_boss_with_no_health_is_refused(self):
        with self.assertRaises(ValueError):
            Fight(steps=2, hp=0)


if __name__ == "__main__":
    unittest.main()
