"""The history cursor (T3 W3) and the divergence detector (T3 W5).

Stepping back is not running backwards. The steps already happened, so going
back is moving an index over a list — no re-execution, no side effects to
replay, no way for history to disagree with itself.

`compare` is the same idea pointed at W4. Resuming an edited run means
executing it again and fast-forwarding, so something has to check that the
fast-forwarded part really did happen the same way -- and comparing two lists
is pure, so it is testable here rather than against a child process.

Everything here runs without a sandbox, a child process or a terminal, which
is the point: if stepping back needed any of those, it would not be history.
"""

import unittest

from vibecoder.timeline import Divergence, Timeline, compare, signature


def steps(count: int) -> list[dict]:
    return [{"line": i, "func": "solve", "locals": {}} for i in range(1, count + 1)]


class TestAnEmptyTimeline(unittest.TestCase):
    def test_it_has_no_current_step(self):
        self.assertIsNone(Timeline().current)

    def test_its_cursor_sits_before_the_beginning(self):
        self.assertEqual(Timeline().cursor, -1)

    def test_it_is_at_its_edge(self):
        """The next step has to come from somewhere new either way."""
        self.assertTrue(Timeline().at_edge)

    def test_going_back_does_nothing(self):
        timeline = Timeline()
        self.assertIsNone(timeline.back())
        self.assertEqual(timeline.cursor, -1)

    def test_going_forward_does_nothing(self):
        self.assertIsNone(Timeline().forward())

    def test_seeking_does_nothing(self):
        self.assertIsNone(Timeline().seek(3))


class TestNavigating(unittest.TestCase):
    def setUp(self):
        self.timeline = Timeline(steps(5))

    def test_it_starts_at_the_newest_step(self):
        self.assertEqual(self.timeline.cursor, 4)
        self.assertEqual(self.timeline.current["line"], 5)

    def test_back_moves_one_step(self):
        self.assertEqual(self.timeline.back()["line"], 4)
        self.assertEqual(self.timeline.cursor, 3)

    def test_back_repeatedly_walks_to_the_start(self):
        self.assertEqual([self.timeline.back()["line"] for _ in range(4)],
                         [4, 3, 2, 1])
        self.assertTrue(self.timeline.at_start)

    def test_back_at_the_start_returns_none_and_stays_put(self):
        """A reader holding the key down at the start should sit still, not
        accumulate an error."""
        self.timeline.seek(0)
        self.assertIsNone(self.timeline.back())
        self.assertEqual(self.timeline.cursor, 0)
        self.assertIsNone(self.timeline.back())
        self.assertEqual(self.timeline.cursor, 0)

    def test_forward_at_the_edge_returns_none(self):
        """Not an error and not the end of the run: the caller's cue to go and
        get a new step from wherever steps come from."""
        self.assertIsNone(self.timeline.forward())
        self.assertEqual(self.timeline.cursor, 4)

    def test_forward_inside_history_replays(self):
        self.timeline.seek(1)
        self.assertEqual(self.timeline.forward()["line"], 3)

    def test_back_then_forward_returns_to_where_it_was(self):
        before = self.timeline.cursor
        self.timeline.back()
        self.timeline.forward()
        self.assertEqual(self.timeline.cursor, before)

    def test_browsing_is_the_opposite_of_being_at_the_edge(self):
        self.assertTrue(self.timeline.at_edge)
        self.timeline.back()
        self.assertFalse(self.timeline.at_edge)

    def test_seek_clamps_rather_than_raising(self):
        self.assertEqual(self.timeline.seek(99)["line"], 5)
        self.assertEqual(self.timeline.seek(-99)["line"], 1)

    def test_rewind_goes_to_the_first_step(self):
        self.timeline.rewind()
        self.assertEqual(self.timeline.cursor, 0)


class TestAppending(unittest.TestCase):
    def test_appending_extends_history(self):
        timeline = Timeline(steps(2))
        timeline.append({"line": 99, "func": "solve", "locals": {}})
        self.assertEqual(len(timeline), 3)

    def test_appending_jumps_the_cursor_to_the_edge(self):
        """A step arriving while the reader is in the past must not leave the
        view sitting still while the run moves -- that reads as a hang."""
        timeline = Timeline(steps(5))
        timeline.rewind()
        timeline.append({"line": 99, "func": "solve", "locals": {}})
        self.assertTrue(timeline.at_edge)
        self.assertEqual(timeline.current["line"], 99)

    def test_appending_to_an_empty_timeline_lands_on_the_first_step(self):
        timeline = Timeline()
        timeline.append({"line": 1, "func": "solve", "locals": {}})
        self.assertEqual(timeline.cursor, 0)
        self.assertEqual(timeline.current["line"], 1)


class TestHistoryIsNotEditable(unittest.TestCase):
    def test_steps_returns_a_copy(self):
        timeline = Timeline(steps(3))
        timeline.steps.clear()
        self.assertEqual(len(timeline), 3)

    def test_the_sequence_it_was_built_from_is_not_aliased(self):
        original = steps(3)
        timeline = Timeline(original)
        original.clear()
        self.assertEqual(len(timeline), 3)

    def test_nothing_is_executed_by_navigating(self):
        """The strongest form of "no re-execution": a timeline of objects that
        would explode if called survives being walked end to end."""
        class Explodes:
            def __call__(self, *a, **k):
                raise AssertionError("history was executed")

        timeline = Timeline([Explodes() for _ in range(4)])
        while timeline.back() is not None:
            pass
        while timeline.forward() is not None:
            pass
        self.assertEqual(len(timeline), 4)


# --------------------------------------------------------------------------
# Divergence (T3 W5)
# --------------------------------------------------------------------------

def trace(*rows) -> list[dict]:
    """Steps as ``(line, func, **locals)``, in the recorded shape."""
    return [
        {"line": line, "func": func, "locals": {k: str(v) for k, v in loc.items()}}
        for line, func, loc in rows
    ]


class Recorded:
    """A step-like object rather than a dict.

    History holds `Step` objects for a live run and dicts for a recorded one
    (Q69), so the detector has to cope with either without being told which.
    """

    def __init__(self, line, func, **loc):
        self.line, self.func, self.locals = line, func, loc


class TestNothingChanged(unittest.TestCase):
    def test_identical_histories_do_not_diverge(self):
        one = trace((2, "solve", {"n": 1}), (3, "solve", {"n": 1, "v": 1}))
        self.assertIsNone(compare(one, list(one)))

    def test_an_empty_original_cannot_diverge(self):
        self.assertIsNone(compare([], trace((2, "solve", {}))))

    def test_a_longer_replay_is_not_divergence(self):
        """Only the prefix a resumed run claims to have reproduced is
        compared. Everything after the edit point is *supposed* to differ."""
        one = trace((2, "solve", {"n": 1}))
        two = trace((2, "solve", {"n": 1}), (3, "solve", {"n": 9}))
        self.assertIsNone(compare(one, two))


class TestWhatCountsAsDivergence(unittest.TestCase):
    def test_different_values_at_the_same_step(self):
        one = trace((2, "solve", {"n": 1}), (3, "solve", {"n": 1, "v": 1}))
        two = trace((2, "solve", {"n": 1}), (3, "solve", {"n": 1, "v": 2}))
        found = compare(one, two)
        self.assertIsInstance(found, Divergence)
        self.assertEqual(found.index, 1)

    def test_a_different_function_says_which(self):
        one = trace((2, "solve", {}), (3, "<listcomp>", {}))
        two = trace((2, "solve", {}), (3, "solve", {}))
        self.assertIn("<listcomp>", compare(one, two).reason)

    def test_the_reason_counts_steps_from_one(self):
        """Step numbering is what the player was shown, not a list index."""
        one = trace((2, "solve", {"n": 1}))
        two = trace((2, "solve", {"n": 2}))
        self.assertIn("step 1", compare(one, two).reason)

    def test_it_carries_both_sides_for_a_caller_that_wants_to_show_them(self):
        one = trace((2, "solve", {"n": 1}))
        two = trace((2, "solve", {"n": 2}))
        found = compare(one, two)
        self.assertEqual(found.original["locals"], {"n": "1"})
        self.assertEqual(found.replayed["locals"], {"n": "2"})

    def test_the_first_difference_is_the_one_reported(self):
        one = trace((2, "s", {"n": 1}), (3, "s", {"n": 1}), (4, "s", {"n": 1}))
        two = trace((2, "s", {"n": 1}), (3, "s", {"n": 9}), (4, "s", {"n": 9}))
        self.assertEqual(compare(one, two).index, 1)


class TestMovedTextIsNotDivergence(unittest.TestCase):
    """The player has just edited the file, so the text has moved. A statement
    sliding down a line because a guard clause was added above it is not the
    program behaving differently, and a detector that says it is gets ignored.
    """

    def test_the_same_step_at_a_different_line_matches(self):
        one = trace((7, "solve", {"n": 1}))
        two = trace((9, "solve", {"n": 1}))
        self.assertIsNone(compare(one, two))

    def test_the_line_is_deliberately_absent_from_the_signature(self):
        self.assertEqual(
            signature({"line": 1, "func": "s", "locals": {}}),
            signature({"line": 99, "func": "s", "locals": {}}),
        )


class TestRunningOutEarly(unittest.TestCase):
    """A re-run that returns before reaching the line the player was looking
    at has not reproduced the prefix either. Saying nothing would leave them
    at a position that no longer exists."""

    def test_a_short_replay_diverges_at_the_step_it_lacks(self):
        one = trace((2, "s", {}), (3, "s", {}), (4, "s", {}))
        found = compare(one, trace((2, "s", {})), upto=3)
        self.assertEqual(found.index, 1)

    def test_it_says_how_far_it_got(self):
        one = trace((2, "s", {}), (3, "s", {}))
        self.assertIn("1 step", compare(one, trace((2, "s", {})), upto=2).reason)

    def test_the_missing_side_is_none_rather_than_invented(self):
        one = trace((2, "s", {}), (3, "s", {}))
        self.assertIsNone(compare(one, trace((2, "s", {})), upto=2).replayed)


class TestOnlyThePrefixIsCompared(unittest.TestCase):
    def test_upto_stops_the_comparison(self):
        one = trace((2, "s", {"n": 1}), (3, "s", {"n": 1}))
        two = trace((2, "s", {"n": 1}), (3, "s", {"n": 9}))
        self.assertIsNone(compare(one, two, upto=1))
        self.assertIsNotNone(compare(one, two, upto=2))

    def test_upto_past_the_end_is_clamped(self):
        one = trace((2, "s", {"n": 1}))
        self.assertIsNone(compare(one, list(one), upto=50))

    def test_upto_zero_compares_nothing(self):
        one = trace((2, "s", {"n": 1}))
        two = trace((2, "s", {"n": 9}))
        self.assertIsNone(compare(one, two, upto=0))


class TestEitherShapeOfStep(unittest.TestCase):
    def test_objects_and_dicts_compare_the_same(self):
        one = [Recorded(2, "solve", n=1)]
        two = trace((2, "solve", {"n": 1}))
        self.assertIsNone(compare(one, two))
        self.assertIsNone(compare(two, one))

    def test_a_step_without_locals_is_not_a_crash(self):
        self.assertEqual(signature({"func": "s"}), ("s", ()))


class TestReadingADivergence(unittest.TestCase):
    def test_it_prints_as_its_reason(self):
        found = compare(trace((2, "s", {"n": 1})), trace((2, "s", {"n": 2})))
        self.assertEqual(str(found), found.reason)

    def test_it_cannot_be_edited(self):
        found = compare(trace((2, "s", {"n": 1})), trace((2, "s", {"n": 2})))
        with self.assertRaises(Exception):
            found.index = 0


if __name__ == "__main__":
    unittest.main()
