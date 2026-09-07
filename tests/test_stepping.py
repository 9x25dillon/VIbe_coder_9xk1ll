"""Live stepping (T3 W2): a submission under the parent's control.

The engine's whole shape follows from one decision: the child runs a line,
reports it, and blocks waiting to be told what to do next. Pause therefore
needs no implementation -- it is the parent not answering yet -- the child
never sleeps, and pacing lives where the player is.

These tests drive a real child process through a real sandbox backend, because
the thing under test *is* the protocol between them.
"""

import time
import unittest

from vibecoder.models import Source, TestCase
from vibecoder.runner import LiveRun, Step
from vibecoder.vision import build_machine, frames

LOOP = '''\
def solve(rows):
    total = 0
    for r in rows:
        total += r
    return total
'''

FOREVER = '''\
def solve(n):
    while True:
        n += 1
    return n
'''

BOOM = '''\
def solve(n):
    value = n
    raise ValueError("boom")
'''

# The edits a player might make to BOOM once it pauses on line 3.
FIXED = '''\
def solve(n):
    value = n
    return value
'''
#: Changes a line the player has already watched run, so the fast-forward
#: cannot honestly claim to have reproduced it.
DIVERGENT = '''\
def solve(n):
    value = n * 2
    return value
'''
#: Returns before reaching the line the player was looking at.
SHORTER = '''\
def solve(n):
    return n
'''
#: Same prefix as BOOM, and one more line after the edit point.
LONGER = '''\
def solve(n):
    value = n
    total = value
    return total
'''
#: Does not crash and does not answer.
EVASIVE = '''\
def solve(n):
    value = n
    return None
'''


def case(*args, expected=None):
    return TestCase("t", list(args), expected=expected)


class SteppingTestBase(unittest.TestCase):
    def live(self, code=LOOP, test=None, **kwargs):
        run = LiveRun(
            code, "solve", test or case([1, 2, 3], expected=6),
            source=Source.PLAYER, **kwargs,
        )
        self.addCleanup(run.close)
        run.start()
        return run


class TestSteppingOneLineAtATime(SteppingTestBase):
    def test_the_first_step_is_the_first_line_of_the_body(self):
        live = self.live()
        step = live.step()
        self.assertIsInstance(step, Step)
        self.assertEqual(step.func, "solve")
        self.assertEqual(step.index, 1)

    def test_each_call_advances_exactly_one_line(self):
        live = self.live()
        seen = [live.step() for _ in range(4)]
        self.assertEqual([s.index for s in seen], [1, 2, 3, 4])

    def test_locals_arrive_as_they_were_at_that_instant(self):
        """Not the final values: the point of watching is seeing them change."""
        live = self.live()
        values = []
        for _ in range(6):
            step = live.step()
            if step is None:
                break
            values.append(step.locals.get("total"))
        self.assertIn("0", values)
        self.assertNotEqual(values[-1], values[1])

    def test_the_run_ends_by_returning_none(self):
        live = self.live()
        for _ in range(200):
            if live.step() is None:
                break
        else:
            self.fail("the run never ended")
        self.assertTrue(live.finished)

    def test_the_result_arrives_after_the_last_step(self):
        live = self.live()
        live.resume()
        result = live.drain()
        self.assertEqual(result.error, "")
        self.assertTrue(live.finished)


class TestPauseIsTheParentNotAnswering(SteppingTestBase):
    def test_the_child_does_not_advance_while_we_do_not_ask(self):
        """The strongest statement of the design: pause is the absence of a
        command, so there is no pause state to get wrong."""
        live = self.live()
        live.step()
        live.step()
        before = len(live.steps)
        time.sleep(0.3)
        self.assertEqual(len(live.steps), before)
        self.assertFalse(live.finished)

    def test_a_long_pause_does_not_time_out_the_run(self):
        """A fight paused while somebody reads it must not fail for being
        watched carefully. The child's budget counts executing time only."""
        live = self.live(timeout=1.0)
        live.step()
        time.sleep(1.5)
        step = live.step()
        self.assertIsNotNone(step)
        live.resume()
        self.assertEqual(live.drain().error, "")

    def test_resuming_runs_to_completion_without_further_prompting(self):
        live = self.live()
        live.step()
        live.resume()
        result = live.drain()
        self.assertEqual(result.error, "")
        self.assertGreater(len(live.steps), 3)

    def test_resume_is_idempotent(self):
        live = self.live()
        live.step()
        live.resume()
        live.resume()
        self.assertEqual(live.drain().error, "")


class TestAbort(SteppingTestBase):
    def test_aborting_stops_the_run_where_it_stands(self):
        live = self.live(test=case(list(range(50)), expected=1225))
        live.step()
        live.step()
        live.abort()
        result = live.result()
        self.assertEqual(result.error_type, "Aborted")
        self.assertIn("player", result.error)

    def test_an_aborted_run_keeps_the_steps_it_reached(self):
        live = self.live(test=case(list(range(50)), expected=1225))
        for _ in range(5):
            live.step()
        live.abort()
        self.assertEqual(len(live.result().trace), 5)

    def test_aborting_twice_is_harmless(self):
        live = self.live()
        live.step()
        live.abort()
        live.abort()
        self.assertTrue(live.finished)

    def test_closing_without_finishing_does_not_hang(self):
        live = self.live(test=case(list(range(500)), expected=124750))
        live.step()
        live.close()
        live.close()


class TestItStaysContained(SteppingTestBase):
    def test_a_runaway_loop_is_stopped_by_its_own_budget(self):
        """Free-running is the only mode that can run away, and it is bounded
        by executing time rather than by wall clock."""
        live = self.live(code=FOREVER, test=case(0, expected=0), timeout=1.0)
        live.step()
        live.resume()
        result = live.drain()
        self.assertEqual(result.error_type, "Aborted")
        self.assertIn("budget", result.error)

    def test_stepping_past_the_recording_cap_does_not_hang_the_parent(self):
        """Recording is bounded because it is memory the parent is handed.
        Reporting is not, because stopping it would leave a paused parent
        waiting for a line that never comes."""
        live = self.live(code=FOREVER, test=case(0, expected=0), timeout=10.0)
        for _ in range(430):
            if live.step() is None:
                self.fail("the child stopped reporting")
        self.assertGreater(len(live.steps), 400)
        live.abort()

    def test_the_recorded_trace_is_still_capped(self):
        live = self.live(code=FOREVER, test=case(0, expected=0), timeout=10.0)
        for _ in range(430):
            if live.step() is None:
                break
        live.abort()
        self.assertEqual(len(live.result().trace), 400)

    def test_a_crash_is_reported_rather_than_raised(self):
        live = self.live(code=BOOM, test=case(1, expected=None))
        live.resume()
        result = live.drain()
        self.assertEqual(result.error_type, "ValueError")
        self.assertIn("boom", result.error)

    def test_a_crash_keeps_the_steps_that_ran_before_it(self):
        live = self.live(code=BOOM, test=case(1, expected=None))
        live.resume()
        result = live.drain()
        self.assertTrue(result.trace)
        self.assertEqual(result.trace[0]["func"], "solve")


class TestOneTraceShapeForEveryRenderer(SteppingTestBase):
    """The live engine must emit what the recording emits.

    `replay` and `vision` both read that shape already. A second shape would
    mean a second renderer, and T3's hazard list names this explicitly.
    """

    def test_a_step_carries_exactly_the_recorded_fields(self):
        live = self.live()
        step = live.step()
        self.assertEqual(set(step.to_trace()), {"line", "func", "locals"})

    def test_the_final_trace_matches_the_recorded_shape(self):
        live = self.live()
        live.resume()
        result = live.drain()
        for record in result.trace:
            self.assertEqual(set(record), {"line", "func", "locals"})

    def test_vision_renders_a_live_trace_without_translation(self):
        live = self.live()
        live.resume()
        result = live.drain()
        machine = build_machine(LOOP)
        built = frames(machine, result.trace)
        self.assertTrue(built)
        self.assertGreater(built[-1].iterations.get(1, 0), 1)

    def test_a_live_trace_and_a_recorded_trace_agree(self):
        """Same code, same input, two engines: the recording and the live run
        must not disagree about what happened."""
        from vibecoder.runner import run_code

        test = case([1, 2, 3], expected=6)
        recorded = run_code(
            LOOP, "solve", [test], source=Source.PLAYER, record_trace=True
        ).trace

        live = self.live(test=test)
        live.resume()
        stepped = live.drain().trace

        self.assertEqual(
            [(s["line"], s["func"]) for s in recorded],
            [(s["line"], s["func"]) for s in stepped],
        )


class TestSteppingBack(SteppingTestBase):
    """T3 W3: read-only history. Nothing is re-executed and the child is not
    told, because it is still blocked exactly where it was."""

    def test_back_returns_an_earlier_step(self):
        live = self.live()
        for _ in range(4):
            live.step()
        earlier = live.back()
        self.assertEqual(earlier.index, 3)

    def test_stepping_back_records_nothing_new(self):
        live = self.live()
        for _ in range(4):
            live.step()
        before = len(live.steps)
        live.back()
        live.back()
        self.assertEqual(len(live.steps), before)

    def test_back_at_the_start_of_history_returns_none(self):
        live = self.live()
        live.step()
        self.assertIsNone(live.back())

    def test_forward_inside_history_replays_without_driving_the_child(self):
        live = self.live()
        for _ in range(4):
            live.step()
        live.back()
        live.back()
        before = len(live.steps)
        replayed = live.forward()
        self.assertEqual(replayed.index, 3)
        self.assertEqual(len(live.steps), before)

    def test_forward_at_the_edge_drives_the_child_again(self):
        """One verb for the caller: inside history it is a cursor move, at the
        edge it is the run continuing."""
        live = self.live()
        for _ in range(3):
            live.step()
        live.back()
        live.forward()
        before = len(live.steps)
        live.forward()
        self.assertEqual(len(live.steps), before + 1)

    def test_browsing_says_whether_the_reader_is_in_the_past(self):
        live = self.live()
        live.step()
        live.step()
        self.assertFalse(live.browsing)
        live.back()
        self.assertTrue(live.browsing)
        live.forward()
        self.assertFalse(live.browsing)

    def test_the_run_still_finishes_after_browsing(self):
        live = self.live()
        for _ in range(4):
            live.step()
        live.back()
        live.back()
        live.resume()
        self.assertEqual(live.drain().error, "")


class TestPausingOnTheFailingLine(SteppingTestBase):
    """T3 exit criterion 2: a deliberate error pauses on the offending line,
    not after it.

    `settrace` reports the exception while ``f_lineno`` is still the line that
    raised. Once the frame unwinds, that line is gone and the best anyone can
    say is which function failed.
    """

    def test_the_failing_step_is_reported_on_the_line_that_raised(self):
        live = self.live(code=BOOM, test=case(1, expected=None))
        failed = None
        while (step := live.step()) is not None:
            if step.failed:
                failed = step
                break
        self.assertIsNotNone(failed)
        self.assertEqual(failed.line, 3)
        self.assertIn("boom", failed.error)

    def test_the_run_is_still_paused_there(self):
        """Not "reported afterwards": the child is blocked on that line and
        the parent decides what happens next."""
        live = self.live(code=BOOM, test=case(1, expected=None))
        while (step := live.step()) is not None:
            if step.failed:
                break
        self.assertFalse(live.finished)

    def test_locals_at_the_moment_of_failure_are_available(self):
        live = self.live(code=BOOM, test=case(7, expected=None))
        while (step := live.step()) is not None:
            if step.failed:
                self.assertEqual(step.locals.get("value"), "7")
                return
        self.fail("no failing step was reported")

    def test_an_ordinary_step_is_not_marked_failed(self):
        live = self.live()
        self.assertFalse(live.step().failed)

    def test_the_failure_can_be_stepped_back_from(self):
        """Back from "it raised here" is "it was about to run here" -- the
        same line, reported first as execution and then as the exception.
        Two events on one line is what actually happened."""
        live = self.live(code=BOOM, test=case(1, expected=None))
        while (step := live.step()) is not None:
            if step.failed:
                break
        before = live.back()
        self.assertFalse(before.failed)
        self.assertEqual(before.line, 3)
        earlier = live.back()
        self.assertEqual(earlier.line, 2)

    def test_the_recorded_trace_keeps_only_the_three_fields(self):
        """`error` rides on the live event alone. The recording is what
        `replay` and `vision` read, and a fourth key is a second shape."""
        live = self.live(code=BOOM, test=case(1, expected=None))
        live.resume()
        result = live.drain()
        for record in result.trace:
            self.assertEqual(set(record), {"line", "func", "locals"})

    def test_interpreter_internals_are_not_shown_as_variables(self):
        """`.0` is a comprehension's own iterator: a real local, and not a
        variable anybody wrote."""
        code = "def solve(rows):\n    return [r for r in rows if r > 1]\n"
        live = self.live(code=code, test=case([1, 2, 3], expected=[2, 3]))
        while (step := live.step()) is not None:
            for name in step.locals:
                self.assertFalse(name.startswith("."), name)


class EditTestBase(SteppingTestBase):
    def paused_on_the_failure(self, code=BOOM, expected=3, arg=3):
        """A run stopped on the line that raised -- where an edit starts."""
        live = self.live(code=code, test=case(arg, expected=expected))
        while (step := live.step()) is not None:
            if step.failed:
                return live
        self.fail("the run never reached a failing step")


class TestEditAndResume(EditTestBase):
    """T3 W4, strategy A: CPython will not swap the code object of a running
    frame, so "edit line 7 and continue" is re-running the edited source from
    the top against the same recorded inputs and fast-forwarding to the edit
    point.

    The inputs are the test payload, which is data the parent already holds --
    which is why the memo strategy A needs costs nothing here.
    """

    def test_the_edit_becomes_the_source(self):
        """Exit criterion 3's "reflected in the final submitted source" is
        something a caller can read rather than assume."""
        live = self.paused_on_the_failure()
        live.edit(FIXED)
        self.assertEqual(live.code, FIXED)

    def test_it_resumes_at_the_edit_point_rather_than_the_top(self):
        live = self.paused_on_the_failure()
        self.assertEqual(live.cursor, 2)
        live.edit(FIXED)
        self.assertEqual(len(live.steps), 2)

    def test_the_edited_step_is_not_replayed_away(self):
        """Fast-forward stops *at* the step the reader is on, never through
        it: that step is the one whose behaviour they just changed."""
        live = self.paused_on_the_failure()
        live.edit(FIXED)
        self.assertFalse(live.steps[-1].failed)
        self.assertEqual(live.steps[-1].line, 3)

    def test_the_fixed_run_finishes_and_answers(self):
        live = self.paused_on_the_failure()
        live.edit(FIXED)
        live.resume()
        result = live.drain()
        self.assertEqual(result.error, "")
        self.assertTrue(all(o.passed for o in result.outcomes))

    def test_the_history_it_replaced_is_kept(self):
        live = self.paused_on_the_failure()
        before = live.steps
        live.edit(FIXED)
        self.assertEqual(len(live.origin), len(before))
        self.assertTrue(live.origin[-1].failed)

    def test_editing_before_anything_ran_starts_from_the_top(self):
        live = self.live(code=BOOM, test=case(3, expected=3))
        self.assertIsNone(live.edit(FIXED))
        self.assertEqual(live.steps, [])
        self.assertEqual(live.step().line, 2)

    def test_editing_from_a_step_the_reader_stepped_back_to(self):
        """The edit point is where the player is looking, not where the child
        happens to be blocked."""
        live = self.paused_on_the_failure()
        live.back()
        live.back()
        live.edit(FIXED)
        self.assertEqual(len(live.steps), 0)

    def test_it_can_be_edited_more_than_once(self):
        live = self.paused_on_the_failure()
        live.edit(DIVERGENT)
        live.edit(FIXED)
        self.assertEqual(live.code, FIXED)
        live.resume()
        self.assertEqual(live.drain().error, "")

    def test_the_fast_forward_leaves_the_child_blocked(self):
        """Not run to the end: a fast-forward that kept going would finish the
        fight while the player was still reading the line they fixed."""
        live = self.paused_on_the_failure()
        live.edit(FIXED)
        self.assertFalse(live.finished)

    def test_the_run_is_stepping_again_after_an_edit(self):
        """One line per ask, from the edit point -- not free-running."""
        live = self.paused_on_the_failure()
        live.edit(LONGER)
        before = len(live.steps)
        live.step()
        self.assertEqual(len(live.steps), before + 1)

    def test_closing_after_an_edit_does_not_hang(self):
        live = self.paused_on_the_failure()
        live.edit(FIXED)
        live.close()
        live.close()

    def test_an_unedited_run_reports_no_divergence(self):
        live = self.paused_on_the_failure()
        self.assertIsNone(live.divergence)
        self.assertEqual(live.origin, [])


class TestDivergenceIsReported(EditTestBase):
    """T3 W5 and exit criterion 4: when the replay stops matching, the engine
    says so instead of presenting a different execution as a continuation of
    the one the player watched."""

    def test_a_fix_confined_to_the_paused_line_does_not_diverge(self):
        self.assertIsNone(self.paused_on_the_failure().edit(FIXED))

    def test_changing_a_line_already_watched_diverges(self):
        live = self.paused_on_the_failure()
        found = live.edit(DIVERGENT)
        self.assertIsNotNone(found)
        self.assertEqual(found.index, 1)

    def test_the_finding_is_remembered_not_only_returned(self):
        live = self.paused_on_the_failure()
        returned = live.edit(DIVERGENT)
        self.assertIs(live.divergence, returned)

    def test_the_fast_forward_stops_at_the_divergence(self):
        """Going on past it is the lie criterion 4 forbids: everything after
        would be presented as part of a run that no longer happened."""
        live = self.paused_on_the_failure()
        live.edit(DIVERGENT)
        self.assertEqual(len(live.steps), live.divergence.index + 1)

    def test_a_run_that_ends_before_the_edit_point_diverges(self):
        """Reaching the end early is not "continuous" either -- the player is
        left at a position that no longer exists."""
        live = self.paused_on_the_failure()
        found = live.edit(SHORTER)
        self.assertIsNotNone(found)
        self.assertIn("before reaching", found.reason)

    def test_a_later_edit_replaces_the_earlier_finding(self):
        live = self.paused_on_the_failure()
        live.edit(DIVERGENT)
        live.edit(FIXED)
        self.assertIsNone(live.divergence)


class TestAStepIsJudgedOnItsAnswer(EditTestBase):
    """Watching a function not crash says nothing about whether it answered.
    A stepped run reports one outcome for the one test it executes, so a step
    cleared by ``return None`` is caught rather than celebrated. Scoring the
    fight is W6/W7; this is only the difference between the two."""

    def test_a_correct_answer_passes(self):
        live = self.paused_on_the_failure()
        live.edit(FIXED)
        live.resume()
        outcomes = live.drain().outcomes
        self.assertEqual([o.passed for o in outcomes], [True])

    def test_not_crashing_is_not_passing(self):
        live = self.paused_on_the_failure()
        live.edit(EVASIVE)
        live.resume()
        result = live.drain()
        self.assertEqual(result.error, "")
        self.assertEqual([o.passed for o in result.outcomes], [False])

    def test_the_answer_it_gave_is_reported(self):
        live = self.paused_on_the_failure()
        live.edit(EVASIVE)
        live.resume()
        outcome = live.drain().outcomes[0]
        self.assertEqual((outcome.got, outcome.expected), ("None", "3"))

    def test_a_crash_is_not_reported_as_an_answer(self):
        live = self.paused_on_the_failure()
        live.resume()
        result = live.drain()
        self.assertIn("boom", result.error)
        self.assertFalse(any(o.passed for o in result.outcomes))


class TestTheResultIsAlwaysAvailable(SteppingTestBase):
    def test_result_before_anything_ran_says_so(self):
        live = self.live()
        result = live.result()
        self.assertEqual(result.error_type, "NoReply")

    def test_drain_from_the_very_start_runs_the_whole_thing(self):
        live = self.live()
        live.resume()
        self.assertEqual(live.drain().error, "")

    def test_steps_is_a_copy_the_caller_cannot_corrupt(self):
        live = self.live()
        live.step()
        live.steps.clear()
        self.assertEqual(len(live.steps), 1)


if __name__ == "__main__":
    unittest.main()
