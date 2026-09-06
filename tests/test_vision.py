"""The machine view: what gets drawn, and what the recording drives.

Every assertion here is on plain text from a `Screen`, with no terminal
involved -- the same way the editor is tested, and for the same reason: a
frame is a value, and a value can be compared.
"""

import re
import unittest

from vibecoder.ui import GLYPHS, renderer_for
from vibecoder.vision import (
    Frame,
    build_machine,
    frames,
    layout,
    render,
    sample,
    still,
)

LOOP = '''\
def solve(rows):
    total = 0
    for r in rows:
        if r > 0:
            total += r
    return total
'''


def trace_for(lines, func="solve", **values):
    return [{"line": line, "func": func, "locals": dict(values)} for line in lines]


class TestTheMachine(unittest.TestCase):
    def test_each_statement_becomes_a_part(self):
        machine = build_machine(LOOP)
        self.assertEqual(
            [p.kind for p in machine.parts],
            ["block", "loop", "branch", "block", "return"],
        )

    def test_nesting_becomes_depth(self):
        machine = build_machine(LOOP)
        self.assertEqual([p.depth for p in machine.parts], [0, 0, 1, 2, 0])

    def test_a_compound_statement_owns_only_its_header_line(self):
        """Otherwise the loop lights up for every line in its own body.

        The token would be in two boxes at once, which is not a drawing bug so
        much as a claim about where control is that happens to be false.
        """
        machine = build_machine(LOOP)
        loop = machine.parts[1]
        self.assertEqual(loop.lines, (3,))
        self.assertEqual(machine.part_for_line(5), 3)  # the body, not the loop

    def test_a_multi_line_statement_owns_every_line_it_spans(self):
        machine = build_machine(
            "def solve(x):\n    return sum(\n        v\n        for v in x\n    )\n"
        )
        self.assertEqual(machine.part_for_line(2), 0)
        self.assertEqual(machine.part_for_line(4), 0)

    def test_an_elif_chain_does_not_invent_an_else_box(self):
        """An `elif` is an `If` inside `orelse`; drawing "else" in front of it
        would show the player a step they never wrote."""
        machine = build_machine(
            "def solve(x):\n"
            "    if x > 2:\n        return 'big'\n"
            "    elif x > 1:\n        return 'mid'\n"
            "    else:\n        return 'small'\n"
        )
        labels = [p.label for p in machine.parts]
        self.assertEqual(labels.count("else"), 1)
        self.assertIn("if x > 1", labels)

    def test_the_title_names_the_function_and_its_arguments(self):
        self.assertEqual(build_machine(LOOP).title, "solve(rows)")

    def test_solve_wins_when_several_functions_exist(self):
        machine = build_machine(
            "def helper(a):\n    return a\n\n\ndef solve(rows):\n    return rows\n"
        )
        self.assertEqual(machine.name, "solve")

    def test_the_last_function_is_drawn_when_none_is_named_solve(self):
        machine = build_machine(
            "def first(a):\n    return a\n\n\ndef second(b):\n    return b\n"
        )
        self.assertEqual(machine.name, "second")

    def test_a_named_function_can_be_chosen(self):
        machine = build_machine(
            "def first(a):\n    return a\n\n\ndef solve(b):\n    return b\n",
            function="first",
        )
        self.assertEqual(machine.name, "first")

    def test_code_that_does_not_parse_is_refused(self):
        with self.assertRaises(ValueError):
            build_machine("def (:\n")

    def test_a_missing_function_is_refused(self):
        with self.assertRaises(ValueError):
            build_machine("def solve(x):\n    return x\n", function="nope")

    def test_a_file_with_no_function_is_refused(self):
        with self.assertRaises(ValueError):
            build_machine("x = 1\n")


class TestFramesComeFromTheRecording(unittest.TestCase):
    def test_a_line_lights_the_box_that_owns_it(self):
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([2, 3, 4, 5, 6]))
        self.assertEqual([f.part for f in built], [0, 1, 2, 3, 4])

    def test_a_loop_counts_an_iteration_each_time_control_returns(self):
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([3, 4, 5, 3, 4, 5, 3, 4, 5]))
        self.assertEqual(built[-1].iterations[1], 3)

    def test_staying_in_the_loop_body_does_not_count_an_iteration(self):
        """The counter is iterations, not visits: re-entering the header is
        what completes a lap."""
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([3, 4, 5, 4, 5]))
        self.assertEqual(built[-1].iterations[1], 1)

    def test_a_branch_never_taken_never_lights_up(self):
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([2, 3, 6]))
        self.assertNotIn(3, [f.part for f in built])

    def test_a_step_inside_a_helper_keeps_the_last_box_lit_and_says_where(self):
        """Dropping these would make a helper call look instantaneous, and a
        solution that hides its work in a helper is the one whose cost most
        needs showing."""
        machine = build_machine(LOOP)
        built = frames(
            machine,
            trace_for([3]) + trace_for([9], func="helper") + trace_for([6]),
        )
        self.assertEqual(built[1].part, built[0].part)
        self.assertEqual(built[1].where, "in helper()")
        self.assertEqual(built[2].where, "")

    def test_an_unmapped_line_keeps_the_previous_box(self):
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([3, 999]))
        self.assertEqual(built[1].part, built[0].part)

    def test_the_changed_local_is_the_one_reported(self):
        machine = build_machine(LOOP)
        built = frames(machine, [
            {"line": 5, "func": "solve", "locals": {"r": "1", "total": "0"}},
            {"line": 5, "func": "solve", "locals": {"r": "1", "total": "7"}},
        ])
        self.assertEqual(built[1].changed, "total")

    def test_an_empty_trace_makes_no_frames(self):
        self.assertEqual(frames(build_machine(LOOP), []), [])

    def test_every_frame_knows_how_far_through_it_is(self):
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([2, 3, 6]))
        self.assertEqual([(f.step, f.total) for f in built],
                         [(1, 3), (2, 3), (3, 3)])


class TestRendering(unittest.TestCase):
    def frame_text(self, source=LOOP, lines=(2, 3, 4, 5), **kwargs):
        machine = build_machine(source)
        built = frames(machine, trace_for(list(lines)))
        return render(machine, built[-1], **kwargs).as_text()

    def test_the_live_box_carries_the_token(self):
        text = self.frame_text(rows=24, columns=72)
        live = [line for line in text.splitlines() if "total += r" in line]
        self.assertTrue(live and "@" in live[0], text)

    def test_a_box_that_is_not_live_carries_no_token(self):
        text = self.frame_text(rows=24, columns=72)
        other = [line for line in text.splitlines() if "total = 0" in line]
        self.assertTrue(other and "@" not in other[0], text)

    def test_the_loop_counter_is_drawn_beside_its_box(self):
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([3, 4, 5, 3, 4, 5]))
        text = render(machine, built[-1], rows=24, columns=72).as_text()
        line = next(l for l in text.splitlines() if "for r in rows" in l)
        self.assertIn("o 2", line)

    def test_the_return_rail_reaches_the_last_nested_box(self):
        """The rail is the loop: if it stops at the header the machine says
        control never goes back, which is the opposite of what a loop does."""
        text = self.frame_text(rows=24, columns=72)
        rows = text.splitlines()
        header = next(i for i, l in enumerate(rows) if "for r in rows" in l)
        deepest = next(i for i, l in enumerate(rows) if "total += r" in l)
        self.assertGreater(deepest, header)
        # every row between the loop and its deepest body carries the rail
        for row in rows[header:deepest + 1]:
            self.assertTrue(row.startswith(("|", "+")), repr(row))

    def test_nested_boxes_share_a_right_edge(self):
        """Nesting reads as nesting only if the boxes line up on one side."""
        text = self.frame_text(rows=24, columns=72)
        edges = {
            line.rstrip().rindex("|")
            for line in text.splitlines()
            if line.count("|") >= 2 and "step" not in line
        }
        self.assertEqual(len(edges), 1, text)

    def test_the_footer_reports_the_step(self):
        text = self.frame_text(rows=24, columns=72)
        self.assertIn("step 4/4", text)

    def test_a_long_label_is_elided_rather_than_wrapped(self):
        source = (
            "def solve(x):\n"
            "    result = x + " + " + ".join(f"value_{i}" for i in range(40)) + "\n"
            "    return result\n"
        )
        text = self.frame_text(source, lines=(2,), rows=24, columns=72)
        self.assertIn("...", text)
        for line in text.splitlines():
            self.assertLessEqual(len(line), 72, repr(line))

    def test_no_row_exceeds_the_width_it_was_given(self):
        text = self.frame_text(rows=24, columns=48)
        for line in text.splitlines():
            self.assertLessEqual(len(line), 48, repr(line))

    def test_the_viewport_keeps_the_live_box_on_screen(self):
        """A function taller than the terminal must still show where you are."""
        source = "def solve(x):\n" + "".join(
            f"    step_{i} = {i}\n" for i in range(40)
        ) + "    return x\n"
        machine = build_machine(source)
        built = frames(machine, trace_for([38]))
        text = render(machine, built[-1], rows=20, columns=72).as_text()
        self.assertIn("step_36", text)

    def test_the_layout_is_identical_without_unicode(self):
        """T6's rule: the same geometry at every capability level."""
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([2, 3, 4, 5]))
        ascii_text = render(machine, built[-1], rows=24, columns=72).as_text()
        unicode_text = render(
            machine, built[-1], rows=24, columns=72,
            glyph=lambda name: GLYPHS[name][0],
        ).as_text()
        self.assertNotEqual(ascii_text, unicode_text)
        self.assertEqual(
            [len(l) for l in ascii_text.splitlines()],
            [len(l) for l in unicode_text.splitlines()],
        )

    def test_a_frame_carries_no_escape_sequence_of_its_own(self):
        """`vision` draws into a Screen; escapes are `Screen.diff`'s business."""
        self.assertNotIn("\033", self.frame_text(rows=24, columns=72))

    def test_a_machine_with_no_frames_still_draws(self):
        machine = build_machine(LOOP)
        text = render(machine, Frame(0, 0, -1, 0, ""), rows=24, columns=72).as_text()
        self.assertIn("total = 0", text)


class TestTheStillForAPipe(unittest.TestCase):
    def test_a_pipe_gets_one_frame_and_no_escapes(self):
        text = still(LOOP, trace_for([2, 3, 4, 5, 6]))
        self.assertNotIn("\033", text)
        self.assertIn("step 5/5", text)

    def test_a_chosen_step_is_rendered(self):
        text = still(LOOP, trace_for([2, 3, 4, 5, 6]), step=2)
        self.assertIn("step 2/5", text)

    def test_a_step_past_the_end_clamps_rather_than_raising(self):
        self.assertIn("step 5/5", still(LOOP, trace_for([2, 3, 4, 5, 6]), step=99))

    def test_an_empty_trace_still_draws_the_machine(self):
        text = still(LOOP, [])
        self.assertIn("for r in rows", text)


class TestTheRevealBudget(unittest.TestCase):
    """The machine view lands in the hottest path, so it has to stay bounded."""

    def frames_of(self, count):
        return [Frame(i, count, 0, 0, "") for i in range(1, count + 1)]

    def test_a_long_run_is_sampled_down(self):
        self.assertEqual(len(sample(self.frames_of(400), 36)), 36)

    def test_a_short_run_is_left_alone(self):
        self.assertEqual(len(sample(self.frames_of(6), 36)), 6)

    def test_sampling_keeps_the_order_of_the_run(self):
        kept = sample(self.frames_of(400), 36)
        self.assertTrue(all(a.step < b.step for a, b in zip(kept, kept[1:])))

    def test_the_last_instant_always_survives(self):
        """The final frame is the answer coming out; dropping it ends the
        animation somewhere arbitrary."""
        self.assertEqual(sample(self.frames_of(400), 36)[-1].step, 400)

    def test_the_first_instant_always_survives(self):
        self.assertEqual(sample(self.frames_of(400), 36)[0].step, 1)

    def test_a_sampled_frame_keeps_the_true_count_at_that_instant(self):
        """Sampling must not make the loop counter count surviving frames.

        The counters are computed over the whole trace before sampling, so a
        kept frame reports what had really happened by then.
        """
        machine = build_machine(LOOP)
        built = frames(machine, trace_for([3, 4, 5] * 20))
        kept = sample(built, 6)
        self.assertEqual(kept[-1].iterations[1], built[-1].iterations[1])
        self.assertEqual(built[-1].iterations[1], 20)

    def test_zero_limit_means_no_sampling(self):
        self.assertEqual(len(sample(self.frames_of(400), 0)), 400)


class TestTheRendererStyleHelper(unittest.TestCase):
    """`vision` gets its escapes from `ui`, which is the module that owns them."""

    def test_a_plain_stream_gets_no_colour(self):
        import io

        renderer = renderer_for(io.StringIO())
        self.assertNotIn("38;2", renderer.style((1, 2, 3)))

    def test_bold_is_independent_of_colour_depth(self):
        import io

        renderer = renderer_for(io.StringIO())
        self.assertIn("1m", renderer.style(None, bold=True))


if __name__ == "__main__":
    unittest.main()
