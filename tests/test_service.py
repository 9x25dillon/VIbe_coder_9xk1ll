"""The front-end use-case layer (T9 W1): lifecycles without a terminal.

The browser build drives the game through `vibecoder.service`, with every run
going through an injected executor. These tests inject one that runs the real
`_harness.py` in a real subprocess, so everything below is measured rather than
mocked -- and they test the scorer with bad solutions as well as good ones,
because M1 was a scorer that had only ever seen good ones.
"""

import asyncio
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from vibecoder import runner
from vibecoder.levels import get_boss, get_level
from vibecoder.models import Source, TestCase as Case
from vibecoder.sandbox import SandboxUnavailable
from vibecoder.scoring import LEVEL_WEIGHTS, score_submission
from vibecoder.service import (
    ExecutionFailed,
    MAX_SOURCE,
    Service,
    ServiceError,
    echo,
)
from vibecoder.session import Session


class HarnessExecutor:
    """Runs the standalone harness in a child interpreter, like the host path."""

    isolating = False

    def __init__(self) -> None:
        self.payloads: list[dict] = []

    async def run(self, payload, commands=()):
        self.payloads.append(payload)
        text = json.dumps(payload) + "\n" + "".join(
            json.dumps(c) + "\n" for c in commands
        )

        def go() -> str:
            done = subprocess.run(
                [sys.executable, "-I", str(runner.HARNESS)],
                input=text, capture_output=True, text=True,
                timeout=float(payload.get("timeout", 10)) + 20,
            )
            return done.stdout

        return await asyncio.to_thread(go)


class Clock:
    """A clock the test moves by hand, so Speed is a known number."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class ServiceCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "profile.json"
        self.clock = Clock()
        self.saves = 0
        self.executor = HarnessExecutor()
        self.service = self.make()

    def make(self, executor=None) -> Service:
        def saved() -> None:
            self.saves += 1

        return Service(
            executor or self.executor, session_path=self.path,
            clock=self.clock, today=lambda: "2026-09-28", on_save=saved,
        )


class TestLevelLifecycle(ServiceCase):
    async def test_a_reference_solve_scores_like_the_cli(self):
        level = get_level("w2-l3-join")
        opened = await self.service.open_level(level.id)
        self.clock.now += 120.0
        ran = await self.service.run(opened["play"], level.reference)
        self.assertTrue(ran["all_passed"])
        self.assertEqual(ran["hints"], [])
        done = await self.service.finish(opened["play"])

        # The same measurement through the CLI's own path.
        seed = opened["seed"]
        from vibecoder.models import Difficulty
        difficulty = Difficulty(opened["difficulty"]["level"])
        tests = level.tests_for(seed, difficulty)
        ref_ops, _ = await asyncio.to_thread(
            runner.reference_benchmark, level, seed, difficulty)
        cli = await asyncio.to_thread(
            lambda: runner.run_submission(level, level.reference, tests,
                                          source=Source.PLAYER))
        self.assertEqual(done["ref_ops"], ref_ops)
        self.assertEqual(done["ops"], cli.ops)

        # And the scorer applied to what the service measured, by hand.
        expected = score_submission(
            runner.RunResult(outcomes=cli.outcomes, ops=done["ops"],
                             peak_bytes=done["peak_bytes"]),
            elapsed_seconds=120.0, par_seconds=level.par_seconds,
            ref_ops=done["ref_ops"], ref_peak_bytes=done["ref_peak_bytes"],
            attempt=1, style_goals_met=all(done["style"].values()),
            first_run_clean=True, weights=LEVEL_WEIGHTS,
        )
        self.assertEqual(done["score"], expected.to_json())
        self.assertEqual(done["elapsed"], 120.0)
        self.assertIn("first_try", done["score"]["bonuses"])

    async def test_a_naive_solution_is_correct_and_costs_functional(self):
        """M1's lesson: score a bad solution, not just the good one."""
        level = get_level("w2-l3-join")
        naive = (
            "def join_events(users, events):\n"
            "    out = []\n"
            "    for e in events:\n"
            "        for u in users:\n"
            "            if u['id'] == e['user_id']:\n"
            "                out.append({'name': u['name'], 'action': e['action']})\n"
            "    return out\n"
        )
        opened = await self.service.open_level(level.id)
        ran = await self.service.run(opened["play"], naive)
        self.assertTrue(ran["all_passed"], ran["first_failure"])
        done = await self.service.finish(opened["play"])
        self.assertEqual(done["score"]["accuracy"], 100.0)
        self.assertLess(done["score"]["functional"], 60.0)
        self.assertGreater(done["ops"], done["ref_ops"])

    async def test_the_clock_starts_after_the_reference_is_measured(self):
        level = get_level("w1-l1-greet")

        class Slow(HarnessExecutor):
            async def run(inner, payload, commands=()):
                self.clock.now += 50.0   # a cold worker, charged to nobody
                return await super().run(payload, commands)

        service = self.make(Slow())
        opened = await service.open_level(level.id)
        self.clock.now += 10.0
        await service.run(opened["play"], level.reference)
        done = await service.finish(opened["play"])
        # 10s of solving plus the 50s the submission's own run took; the
        # reference's 50s happened before the clock started.
        self.assertEqual(done["elapsed"], 60.0)

    async def test_the_starter_fails_and_cannot_finish_without_giving_up(self):
        level = get_level("w1-l3-count")
        opened = await self.service.open_level(level.id)
        ran = await self.service.run(opened["play"], level.starter)
        self.assertFalse(ran["all_passed"])
        self.assertIsNotNone(ran["first_failure"])
        with self.assertRaises(ServiceError) as caught:
            await self.service.finish(opened["play"])
        self.assertEqual(caught.exception.code, "invalid_state")

        done = await self.service.finish(opened["play"], give_up=True)
        self.assertEqual(done["score"]["stars"], 0)
        self.assertEqual(done["score"]["speed"], 0.0)
        self.assertIsNone(done["next"])
        banked = Session.load(self.path).levels[level.id]
        self.assertEqual((banked.attempts, banked.clears), (1, 0))

    async def test_finish_banks_exactly_once(self):
        level = get_level("w1-l1-greet")
        opened = await self.service.open_level(level.id)
        await self.service.run(opened["play"], level.reference)
        await self.service.finish(opened["play"])
        with self.assertRaises(ServiceError) as caught:
            await self.service.finish(opened["play"])
        self.assertEqual(caught.exception.code, "no_such_play")
        self.assertEqual(Session.load(self.path).levels[level.id].attempts, 1)
        self.assertEqual(self.saves, 1)

    async def test_abandon_banks_nothing(self):
        level = get_level("w1-l1-greet")
        opened = await self.service.open_level(level.id)
        await self.service.run(opened["play"], level.reference)
        self.assertEqual(self.service.abandon(opened["play"]), {"closed": True})
        self.assertEqual(self.service.abandon(opened["play"]), {"closed": False})
        self.assertFalse(self.path.exists())
        self.assertEqual(self.saves, 0)

    async def test_a_crash_first_costs_both_first_run_bonuses(self):
        level = get_level("w1-l1-greet")
        opened = await self.service.open_level(level.id)
        crashed = await self.service.run(opened["play"], "def greet(:\n")
        self.assertTrue(crashed["fatal"])
        self.assertEqual(crashed["error_type"], "SyntaxError")
        await self.service.run(opened["play"], level.reference)
        done = await self.service.finish(opened["play"])
        self.assertNotIn("first_try", done["score"]["bonuses"])
        self.assertNotIn("clean_first_run", done["score"]["bonuses"])

    async def test_hints_are_earned_by_failing(self):
        level = get_level("w1-l3-count")
        if not level.hints:
            self.skipTest("level has no hints")
        opened = await self.service.open_level(level.id)
        ran = await self.service.run(opened["play"], level.starter)
        self.assertEqual(ran["hints"], list(level.hints_after(1)))

    async def test_reset_removes_progress_and_saved_code(self):
        level = get_level("w1-l1-greet")
        opened = await self.service.open_level(level.id)
        await self.service.run(opened["play"], level.reference)
        await self.service.finish(opened["play"])
        runs = self.path.parent / "runs"
        self.assertEqual(len(list(runs.glob("*.json"))), 1)
        other = await self.service.open_level(level.id)

        self.assertEqual(self.service.reset(), {"runs_removed": 1})
        self.assertFalse(self.path.exists())
        self.assertEqual(list(runs.glob("*.json")), [])
        self.assertEqual(self.service.player()["cleared"], 0)
        # An open play belonged to the wiped profile; it cannot bank into
        # the fresh one.
        with self.assertRaises(ServiceError):
            await self.service.run(other["play"], level.reference)

    async def test_refusals_carry_codes(self):
        with self.assertRaises(ServiceError) as caught:
            await self.service.open_level("w9-nope")
        self.assertEqual(caught.exception.code, "unknown_level")
        opened = await self.service.open_level("w1-l1-greet")
        with self.assertRaises(ServiceError) as caught:
            await self.service.run(opened["play"], "x" * (MAX_SOURCE + 1))
        self.assertEqual(caught.exception.code, "too_large")
        with self.assertRaises(ServiceError) as caught:
            await self.service.finish(opened["play"])
        self.assertEqual(caught.exception.code, "invalid_state")


class TestDaily(ServiceCase):
    async def test_a_daily_is_served_fixed_and_ranked_once(self):
        today = self.service.daily()
        self.assertIsNotNone(today)
        level = get_level(today["level_id"])
        for ranked in (True, False):
            opened = await self.service.open_level(level.id, daily=True)
            self.assertEqual(opened["seed"], today["seed"])
            self.assertEqual(opened["difficulty"]["source"], "fixed")
            await self.service.run(opened["play"], level.reference)
            done = await self.service.finish(opened["play"])
            self.assertEqual(done["daily"], {"ranked": ranked})
        self.assertIsNotNone(self.service.daily()["played"])

    async def test_another_level_is_not_the_daily(self):
        today = self.service.daily()
        other = next(l for l in ("w1-l1-greet", "w1-l2-bigger")
                     if l != today["level_id"])
        with self.assertRaises(ServiceError) as caught:
            await self.service.open_level(other, daily=True)
        self.assertEqual(caught.exception.code, "not_daily")


class TestExecution(ServiceCase):
    async def test_a_timeout_reads_like_the_hosts(self):
        class Hung(HarnessExecutor):
            async def run(self, payload, commands=()):
                raise TimeoutError

        service = self.make(Hung())
        result, _ = await service._execute(
            "def f():\n    return 1\n", "f", [Case("t", expected=1)],
            source=Source.PLAYER)
        self.assertEqual(result.error_type, "Timeout")
        self.assertIn("infinite loop", result.error)

    async def test_a_dead_child_is_a_crash_not_a_pass(self):
        class Dead(HarnessExecutor):
            async def run(self, payload, commands=()):
                raise ExecutionFailed("worker vanished")

        service = self.make(Dead())
        result, _ = await service._execute(
            "def f():\n    return 1\n", "f", [Case("t", expected=1)],
            source=Source.PLAYER)
        self.assertEqual(result.error_type, "SandboxCrash")
        self.assertFalse(result.all_passed)

    async def test_garbage_output_is_malformed(self):
        class Garbage(HarnessExecutor):
            async def run(self, payload, commands=()):
                return "hello\n{not json\n"

        service = self.make(Garbage())
        result, _ = await service._execute(
            "def f():\n    return 1\n", "f", [Case("t", expected=1)],
            source=Source.PLAYER)
        self.assertEqual(result.error_type, "SandboxCrash")
        self.assertIn("malformed", result.error)

    async def test_third_party_code_is_refused_without_isolation(self):
        with self.assertRaises(SandboxUnavailable):
            await self.service._execute(
                "def f():\n    return 1\n", "f", [Case("t", expected=1)],
                source=Source.THIRD_PARTY)
        self.assertEqual(self.executor.payloads, [])

    def test_execute_has_no_default_source(self):
        """N9, for the second transport: forgetting must be a TypeError."""
        parameter = inspect.signature(Service._execute).parameters["source"]
        self.assertIs(parameter.default, inspect.Parameter.empty)

    async def test_the_payload_is_the_one_run_code_sends(self):
        tests = [Case("t", args=[2], expected=4)]
        await self.service._execute("def f(x):\n    return x * 2\n", "f",
                                    tests, source=Source.PLAYER)
        self.assertEqual(
            self.executor.payloads[-1],
            runner.build_payload("def f(x):\n    return x * 2\n", "f", tests),
        )


class TestRunnerSeam(unittest.TestCase):
    def test_parse_reply_finds_the_result_among_progress(self):
        out = "\n".join([
            json.dumps({"event": "progress", "index": 0, "total": 1,
                        "name": "t", "passed": True}),
            json.dumps({"event": "result", "outcomes": [
                {"name": "t", "passed": True, "got": "1", "expected": "1",
                 "error": ""}], "ops": 3}),
        ])
        result = runner.parse_reply(out)
        self.assertTrue(result.all_passed)
        self.assertEqual(result.ops, 3)

    def test_parse_reply_refuses_a_stream_without_a_result(self):
        result = runner.parse_reply(json.dumps({"event": "progress"}))
        self.assertEqual(result.error_type, "SandboxCrash")

    def test_step_mode_is_only_sent_when_asked(self):
        self.assertNotIn("mode", runner.build_payload("", "f", []))
        self.assertEqual(runner.build_payload("", "f", [], mode="step")["mode"],
                         "step")

    def test_echo_keeps_both_ends(self):
        text = echo(list(range(200)))
        self.assertTrue(text.startswith("[0, 1"))
        self.assertTrue(text.endswith("199]"))
        self.assertIn(" ... ", text)


class TestBossStub(unittest.TestCase):
    def test_a_missing_function_gets_its_stub(self):
        boss = get_boss("w1-boss-pipeline")
        grown = boss.step(1).with_stub(boss.starter_source(0))
        self.assertIn(f"def {boss.step(1).func_name}", grown)

    def test_a_function_already_written_is_left_alone(self):
        boss = get_boss("w1-boss-pipeline")
        code = boss.reference_source()
        self.assertEqual(boss.step(1).with_stub(code), code)


class TestBoss(ServiceCase):
    BOSS = "w1-boss-pipeline"

    async def test_the_starter_answers_wrongly_and_a_repair_clears_it(self):
        boss = get_boss(self.BOSS)
        opened = await self.service.open_boss(self.BOSS)
        first = await self.service.boss_attempt(opened["fight"])
        self.assertEqual(first["outcome"], "wrong")
        self.assertGreater(len(first["events"]), 0)
        self.assertLess(first["accuracy"], 1.0)

        fixed = boss.step(0).with_stub(boss.reference_source(0))
        repaired = await self.service.boss_repair(opened["fight"], fixed)
        self.assertEqual(repaired["outcome"], "cleared")
        self.assertIn("healed", repaired["repair"])
        self.assertEqual(repaired["fight"]["spent"], 1)
        # The next step's stub arrived with the clear.
        self.assertIn(f"def {boss.step(1).func_name}", repaired["code"])
        self.assertEqual(repaired["state"], "ready")

    async def test_the_reference_wins_but_a_repair_leaves_it_standing(self):
        boss = get_boss(self.BOSS)
        opened = await self.service.open_boss(self.BOSS)
        fight = opened["fight"]
        first = await self.service.boss_attempt(fight)
        self.assertEqual(first["outcome"], "wrong")
        body = await self.service.boss_repair(fight, boss.reference_source())
        while body["state"] == "ready":
            body = await self.service.boss_attempt(fight)
        self.assertEqual(body["state"], "won")
        self.clock.now += 300.0
        done = await self.service.boss_finish(fight, slept=100.0)
        self.assertEqual(done["ending"], "survives")
        self.assertFalse(done["banked"])
        self.assertEqual(done["score"]["accuracy"], 100.0)
        self.assertNotIn("first_try", done["score"]["bonuses"])
        # The renderer's animation came off the clock, and no more than that.
        self.assertEqual(done["elapsed"], 200.0)
        self.assertFalse(self.path.exists(), "a fight must not be banked (Q84)")

    async def test_a_flawless_fight_puts_the_boss_down(self):
        boss = get_boss(self.BOSS)
        opened = await self.service.open_boss(self.BOSS)
        fight = opened["fight"]
        body = await self.service.boss_attempt(fight, boss.reference_source())
        while body["state"] == "ready":
            body = await self.service.boss_attempt(fight)
        done = await self.service.boss_finish(fight)
        self.assertEqual(done["ending"], "down")
        self.assertIn("first_try", done["score"]["bonuses"])

    async def test_a_raise_pauses_on_its_line_and_a_fix_resumes_there(self):
        boss = get_boss(self.BOSS)
        step = boss.step(0)
        good = step.with_stub(boss.reference_source(0))
        # Break the reference on its last line, so there is a prefix to keep.
        lines = good.rstrip("\n").splitlines()
        body_lines = [i for i, l in enumerate(lines) if l.strip().startswith("return")]
        if not body_lines:
            self.skipTest("reference has no return line to break")
        at = body_lines[-1]
        indent = lines[at][: len(lines[at]) - len(lines[at].lstrip())]
        broken_lines = lines[:at] + [indent + "raise ValueError('boom')"] + lines[at + 1:]
        broken = "\n".join(broken_lines) + "\n"

        opened = await self.service.open_boss(self.BOSS)
        crashed = await self.service.boss_attempt(opened["fight"], broken)
        self.assertEqual(crashed["outcome"], "crashed")
        self.assertIn("ValueError", crashed["error"])
        self.assertEqual(crashed["line"], at + 1)
        paused = crashed["paused_at"]

        resumed = await self.service.boss_repair(opened["fight"], good)
        self.assertIsNone(resumed["divergence"])
        self.assertEqual(resumed["resume_at"], paused)
        self.assertEqual(resumed["outcome"], "cleared")

    async def test_an_edit_that_changes_the_past_is_reported(self):
        opened = await self.service.open_boss(self.BOSS)
        boss = get_boss(self.BOSS)
        step = boss.step(0)
        # Walk a loop, then raise; the "fix" walks a different loop.
        crash = step.with_stub(
            f"def {step.func_name}(*args, **kwargs):\n"
            "    total = 0\n"
            "    for i in range(3):\n"
            "        total += i\n"
            "    raise RuntimeError('late')\n"
        )
        crashed = await self.service.boss_attempt(opened["fight"], crash)
        self.assertEqual(crashed["outcome"], "crashed")
        changed = crash.replace("total += i", "total += i * 10")
        resumed = await self.service.boss_repair(opened["fight"], changed)
        self.assertIsNotNone(resumed["divergence"])
        self.assertLess(resumed["resume_at"], crashed["paused_at"] + 1)

    async def test_running_out_of_repairs_ends_the_fight(self):
        boss = get_boss(self.BOSS)
        opened = await self.service.open_boss(self.BOSS)
        fight = opened["fight"]
        body = await self.service.boss_attempt(fight)
        while body["state"] == "wrong":
            body = await self.service.boss_repair(fight, boss.starter_source(0))
        self.assertEqual(body["state"], "over")
        self.assertTrue(body.get("no_repairs"))
        with self.assertRaises(ServiceError):
            await self.service.boss_repair(fight, boss.reference_source())
        done = await self.service.boss_finish(fight)
        self.assertEqual(done["ending"], "stopped")
        self.assertLess(done["score"]["accuracy"], 100.0)
        self.assertEqual(done["score"]["speed"], 0.0)

    async def test_pacing_cannot_exceed_the_time_that_passed(self):
        opened = await self.service.open_boss(self.BOSS)
        self.clock.now += 5.0
        with self.assertRaises(ServiceError):
            await self.service.boss_repair(opened["fight"], "x", slept=1e9)
        play = self.service._fights[opened["fight"]]
        self.assertEqual(play.slept, 5.0)
