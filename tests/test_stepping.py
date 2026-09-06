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
