"""Keystroke rhythm. Every assertion passes an explicit clock: no sleeping."""

import unittest

from vibecoder.pulse import IDLE_AFTER, THINKING_AFTER, Pulse

T0 = 1000.0


def typed(count: int, interval: float, start: float = T0) -> Pulse:
    p = Pulse()
    for index in range(count):
        p.press(start + index * interval)
    return p


class TestState(unittest.TestCase):
    def test_a_fresh_pulse_is_idle(self):
        self.assertEqual(Pulse().state(T0), "idle")

    def test_fast_typing_reads_as_a_burst(self):
        p = typed(20, 0.05)
        self.assertEqual(p.state(T0 + 20 * 0.05), "burst")

    def test_steady_typing_reads_as_typing(self):
        p = typed(20, 0.4)
        self.assertEqual(p.state(T0 + 20 * 0.4), "typing")

    def test_a_short_silence_reads_as_thinking(self):
        p = typed(5, 0.1)
        self.assertEqual(p.state(T0 + THINKING_AFTER + 0.5), "thinking")

    def test_a_long_silence_reads_as_idle(self):
        p = typed(5, 0.1)
        self.assertEqual(p.state(T0 + IDLE_AFTER + 1), "idle")


class TestEnergy(unittest.TestCase):
    def test_energy_peaks_at_the_moment_of_a_keystroke(self):
        p = Pulse()
        p.press(T0)
        self.assertAlmostEqual(p.energy(T0), 1.0)

    def test_energy_decays(self):
        p = Pulse()
        p.press(T0)
        self.assertLess(p.energy(T0 + 1), p.energy(T0 + 0.1))

    def test_energy_never_goes_negative(self):
        p = Pulse()
        p.press(T0)
        self.assertGreaterEqual(p.energy(T0 + 600), 0.0)

    def test_an_untouched_pulse_has_no_energy(self):
        self.assertEqual(Pulse().energy(T0), 0.0)


class TestWpm(unittest.TestCase):
    def test_no_keystrokes_is_zero(self):
        self.assertEqual(Pulse().wpm(T0), 0.0)

    def test_a_single_keystroke_is_zero(self):
        p = Pulse()
        p.press(T0)
        self.assertEqual(p.wpm(T0), 0.0)

    def test_a_known_cadence_gives_a_known_rate(self):
        """Five chars per second is 60 wpm by the standard definition."""
        p = typed(21, 0.2)
        self.assertAlmostEqual(p.wpm(T0 + 4.0), 60.0, delta=1.0)

    def test_faster_typing_scores_higher(self):
        slow = typed(20, 0.5).wpm(T0 + 10)
        fast = typed(20, 0.1).wpm(T0 + 2)
        self.assertGreater(fast, slow)


class TestEvenness(unittest.TestCase):
    def test_a_metronome_is_perfectly_even(self):
        self.assertAlmostEqual(typed(20, 0.2).evenness(T0 + 4), 1.0, places=5)

    def test_too_few_keystrokes_reports_nothing(self):
        self.assertEqual(typed(2, 0.2).evenness(T0 + 1), 0.0)

    def test_erratic_typing_scores_lower_than_steady(self):
        steady = typed(12, 0.2)
        erratic = Pulse()
        stamp = T0
        for gap in (0.05, 0.9, 0.05, 1.4, 0.05, 0.7, 0.05, 1.1, 0.05, 0.6, 0.05):
            stamp += gap
            erratic.press(stamp)
        self.assertLess(erratic.evenness(stamp), steady.evenness(T0 + 2.4))

    def test_evenness_stays_in_range(self):
        erratic = Pulse()
        stamp = T0
        for gap in (0.01, 3.0, 0.01, 3.0, 0.01):
            stamp += gap
            erratic.press(stamp)
        self.assertGreaterEqual(erratic.evenness(stamp), 0.0)
        self.assertLessEqual(erratic.evenness(stamp), 1.0)


class TestTrail(unittest.TestCase):
    def test_the_trail_has_the_requested_width(self):
        self.assertEqual(len(typed(10, 0.1).trail(16, T0 + 1)), 16)

    def test_a_zero_width_trail_is_empty(self):
        self.assertEqual(typed(10, 0.1).trail(0, T0 + 1), [])

    def test_recent_keystrokes_land_at_the_right_hand_end(self):
        p = typed(10, 0.02)
        trail = p.trail(8, T0 + 0.2)
        self.assertGreater(trail[-1], 0.0)
        self.assertEqual(trail[0], 0.0)

    def test_values_are_normalised(self):
        trail = typed(40, 0.05).trail(10, T0 + 2)
        self.assertLessEqual(max(trail), 1.0)
        self.assertGreaterEqual(min(trail), 0.0)

    def test_the_trail_drains_as_time_passes(self):
        """A still display cannot show a pause, and the pause is the point."""
        p = typed(20, 0.05)
        busy = sum(p.trail(12, T0 + 1))
        later = sum(p.trail(12, T0 + p.window + 2))
        self.assertGreater(busy, later)
        self.assertEqual(later, 0.0)

    def test_an_empty_pulse_has_a_flat_trail(self):
        self.assertEqual(set(Pulse().trail(6, T0)), {0.0})


class TestBookkeeping(unittest.TestCase):
    def test_total_counts_every_keystroke_ever(self):
        p = typed(30, 0.05)
        self.assertEqual(p.total, 30)

    def test_total_survives_the_window_expiring(self):
        p = typed(30, 0.05)
        p.trail(4, T0 + 1000)
        self.assertEqual(p.total, 30)

    def test_reset_clears_everything(self):
        p = typed(10, 0.1)
        p.reset()
        self.assertEqual(p.total, 0)
        self.assertEqual(p.state(T0), "idle")


if __name__ == "__main__":
    unittest.main()
