"""Function classes: what your code looks like, never what it scores. T4 W8.

Two rules do most of the work here, and both are exit criteria rather than
preferences:

* **Criterion 6** -- a class is derivable from the Vibe Vector alone, and
  changing a player's scores without changing their code never changes it.
* **No class is better than another.** There is no ordering, no tier and no
  number attached, and the blurbs are written so none reads as the
  consolation prize.

The third rule is the trajectory's last hazard: a class system is a horoscope
by default, and the evidence on screen is what makes it a measurement instead.
"""

import inspect
import unittest

from vibecoder.mastery import Mastery
from vibecoder.models import VibeVector
from vibecoder.profiler import (
    CLASS_RULES,
    CLASS_SIGNALS_REQUIRED,
    Signal,
    all_classes,
    derive_class,
)


def vibe(**patterns) -> VibeVector:
    docstrings = patterns.pop("docstring_ratio", 0.0)
    return VibeVector(files=20, functions=100, patterns=patterns,
                      docstring_ratio=docstrings)


COMPREHENSIONIST = dict(comprehension=0.8, generator_expr=0.5,
                        builtin_aggregate=0.7)
LOOPWRIGHT = dict(comprehension=0.02, generator_expr=0.0, enumerate=0.4)


class TestASignal(unittest.TestCase):
    def test_an_at_least_signal_is_met_at_the_threshold(self):
        self.assertTrue(Signal("x", value=0.5, threshold=0.5).met)

    def test_an_at_least_signal_is_not_met_below_it(self):
        self.assertFalse(Signal("x", value=0.49, threshold=0.5).met)

    def test_an_at_most_signal_inverts(self):
        self.assertTrue(Signal("x", value=0.1, threshold=0.15, at_most=True).met)
        self.assertFalse(Signal("x", value=0.2, threshold=0.15, at_most=True).met)

    def test_a_signal_carries_the_measurement_not_just_the_verdict(self):
        """The hazard: a class is flattery unless the numbers are on screen
        where the player can disagree with them."""
        rendered = str(Signal("comprehensions in", value=0.7, threshold=0.45))
        self.assertIn("70%", rendered)
        self.assertIn("45%", rendered)

    def test_an_unmet_signal_has_no_margin(self):
        self.assertEqual(Signal("x", value=0.1, threshold=0.5).margin, 0.0)

    def test_margin_grows_with_the_measurement(self):
        near = Signal("x", value=0.5, threshold=0.45).margin
        far = Signal("x", value=0.95, threshold=0.45).margin
        self.assertLess(near, far)


class TestDerivingAClass(unittest.TestCase):
    def test_a_comprehension_heavy_codebase_is_a_comprehensionist(self):
        self.assertEqual(derive_class(vibe(**COMPREHENSIONIST)).name,
                         "Comprehensionist")

    def test_a_loop_heavy_codebase_is_a_loopwright(self):
        self.assertEqual(derive_class(vibe(**LOOPWRIGHT)).name, "Loopwright")

    def test_an_empty_codebase_has_no_class(self):
        """`None` is a real answer. A codebase without a pronounced habit gets
        a description of that, not an invented label."""
        self.assertIsNone(derive_class(VibeVector()))

    def test_absence_alone_never_earns_a_class(self):
        """The bug this rule exists for: an empty vector cleared two of
        Loopwright's signals by containing nothing at all, and a project with
        no comprehensions because it has no code is not a Loopwright."""
        self.assertIsNone(derive_class(VibeVector()))
        # Two `at_most` signals met, no positive one: still nothing.
        self.assertIsNone(derive_class(vibe(comprehension=0.0,
                                            generator_expr=0.0,
                                            enumerate=0.01)))

    def test_absence_still_corroborates_a_present_habit(self):
        """The paired positive. Absence cannot establish a reading; it can
        support one, and a real Loopwright must still be reachable."""
        found = derive_class(vibe(**LOOPWRIGHT))
        self.assertEqual(found.name, "Loopwright")

    def test_one_matching_signal_is_not_enough(self):
        """One threshold cleared is a coincidence, and a class handed out on a
        single number is the horoscope the hazard warns about."""
        found = derive_class(vibe(comprehension=0.9))
        self.assertIsNone(found)

    def test_two_matching_signals_are_enough(self):
        found = derive_class(vibe(comprehension=0.9, generator_expr=0.9))
        self.assertIsNotNone(found)
        self.assertEqual(len(found.met), CLASS_SIGNALS_REQUIRED)

    def test_the_class_carries_every_signal_not_only_the_met_ones(self):
        """A player should see the one they missed as well, or "what earned
        it" is a list with the interesting part removed."""
        found = derive_class(vibe(comprehension=0.9, generator_expr=0.9))
        self.assertEqual(len(found.signals), 3)
        self.assertEqual(len(found.met), 2)

    def test_derivation_is_deterministic(self):
        subject = vibe(**COMPREHENSIONIST)
        self.assertEqual(derive_class(subject), derive_class(subject))

    def test_every_class_is_reachable(self):
        """A class nothing can earn is decoration. Each rule set is fed a
        codebase built from its own thresholds."""
        for name, _, rules in CLASS_RULES:
            with self.subTest(cls=name):
                patterns, docstrings = {}, 0.0
                for label, read, threshold, at_most in rules:
                    value = 0.0 if at_most else min(1.0, threshold + 0.2)
                    probe = VibeVector(patterns={"__probe__": 1.0},
                                       docstring_ratio=value)
                    # Identify which field this rule reads by feeding a vector
                    # whose patterns are empty: a docstring rule sees `value`.
                    if read(probe) == value:
                        docstrings = value
                    else:
                        for key in ("comprehension", "generator_expr",
                                    "builtin_aggregate", "enumerate", "class",
                                    "dataclass", "property", "type_hints",
                                    "keyword_only_args", "generator_function",
                                    "context_manager", "lambda",
                                    "map_filter_reduce"):
                            if read(VibeVector(patterns={key: 0.77})) == 0.77:
                                patterns[key] = value
                                break
                built = VibeVector(patterns=patterns, docstring_ratio=docstrings)
                self.assertEqual(len(all_classes(built)[0].met), 3, name)


class TestNoClassOutranksAnother(unittest.TestCase):
    def test_a_class_carries_no_score_or_rank(self):
        """There is deliberately nothing to sort players by."""
        found = derive_class(vibe(**COMPREHENSIONIST))
        fields = set(type(found).__dataclass_fields__)
        self.assertEqual(fields, {"name", "blurb", "signals"})

    def test_no_blurb_reads_as_a_verdict(self):
        """A Loopwright is not a junior Comprehensionist. Nothing in a blurb
        may grade the habit it describes."""
        graded = ("better", "worse", "best", "advanced", "beginner", "should",
                  "poor", "good", "bad", "improve", "still", "only")
        for name, blurb, _ in CLASS_RULES:
            with self.subTest(cls=name):
                for word in graded:
                    self.assertNotIn(word, blurb.lower().split())

    def test_every_class_has_the_same_number_of_signals(self):
        """Otherwise "cleared 3 of 3" would mean different things per class
        and the comparison that picks a winner would be unfair."""
        counts = {len(rules) for _, _, rules in CLASS_RULES}
        self.assertEqual(len(counts), 1)


class TestCriterionSix(unittest.TestCase):
    """A class is derivable from the Vibe Vector alone, and changing scores
    without changing code never changes it."""

    def test_there_is_nowhere_to_pass_a_score(self):
        """The signature is the assertion. Enforcement by argument list beats
        a rule somebody has to remember."""
        parameters = list(inspect.signature(derive_class).parameters)
        self.assertEqual(parameters, ["vibe"])

    def test_mastery_cannot_reach_the_derivation(self):
        source = inspect.getsource(derive_class) + inspect.getsource(all_classes)
        self.assertNotIn("mastery", source.lower())

    def test_the_class_survives_any_amount_of_scoring(self):
        subject = vibe(**COMPREHENSIONIST)
        before = derive_class(subject)

        mastery = Mastery()
        for _ in range(50):
            mastery.observe(("functional", "algorithms", "data"), 0.0)
        for _ in range(50):
            mastery.observe(("oop", "typing"), 1.0)

        self.assertEqual(derive_class(subject), before)

    def test_changing_the_code_can_change_the_class(self):
        """The paired negative. Without it, "scores never change the class"
        would also pass for a constant."""
        self.assertNotEqual(
            derive_class(vibe(**COMPREHENSIONIST)).name,
            derive_class(vibe(**LOOPWRIGHT)).name,
        )


class TestTheRunnersUp(unittest.TestCase):
    def test_all_classes_returns_every_rule(self):
        self.assertEqual(len(all_classes(VibeVector())), len(CLASS_RULES))

    def test_the_best_fit_comes_first(self):
        ranked = all_classes(vibe(**COMPREHENSIONIST))
        self.assertEqual(ranked[0].name, "Comprehensionist")

    def test_ordering_is_by_signals_met_before_anything_else(self):
        ranked = all_classes(vibe(**COMPREHENSIONIST))
        met = [len(cls.met) for cls in ranked]
        self.assertEqual(met, sorted(met, reverse=True))

    def test_a_tie_is_broken_deterministically(self):
        subject = vibe(**COMPREHENSIONIST)
        self.assertEqual([c.name for c in all_classes(subject)],
                         [c.name for c in all_classes(subject)])


if __name__ == "__main__":
    unittest.main()
