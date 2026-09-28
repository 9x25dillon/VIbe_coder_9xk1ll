"""The game's use cases, callable by a front-end that owns no terminal (T9 W1).

The CLI drives a level from a loop that also prints, and a boss from private
functions that also print. A browser cannot run either: the only Python it has
lives in a WebAssembly worker, and every submission runs in *another* worker it
cannot block on. This module is those lifecycles with the printing taken out --
open, run, finish, and the fight's equivalents -- each returning a plain,
JSON-shaped dict.

It owns what ADR-001 says the engine must own and a renderer must not: the
seed, the difficulty, the attempt count, first-run state, the clock and
persistence. A front-end sends intents and renders facts. Scores are computed
by the same `scoring` functions the CLI calls, against a reference benchmarked
in the same interpreter as the submission, so the numbers mean the same thing
wherever the engine is running.

**Execution is injected.** An `Executor` runs `_harness.py` once and returns
its stdout. The browser build passes one backed by a fresh Pyodide worker per
run; the tests pass one backed by a subprocess. Neither is described as a
security boundary (N4), and the service asks the executor whether it isolates
before running anything that needs it (N9) -- the answer for the browser is
no, so third-party source is refused there exactly as it is on a pinned host.

The service is async because the browser's executor is: a worker cannot be
waited on synchronously without cross-origin isolation, which a static host
cannot always promise. Nothing here blocks.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Protocol, Sequence

from . import daily as daily_model
from . import fight as fight_model
from . import levels as level_registry
from . import style, tips
from .models import (
    DEFAULT_DIFFICULTY,
    BossLevel,
    Difficulty,
    Level,
    RunResult,
    Source,
    TestCase,
)
from .policy import Decision, choose_difficulty, choose_drill
from .runner import (
    DEFAULT_MEM_LIMIT_MB,
    DEFAULT_TIMEOUT,
    REFERENCE_FILENAME,
    SUBMISSION_FILENAME,
    build_payload,
    parse_reply,
)
from .sandbox import SandboxUnavailable
from .scoring import (
    BOSS_WEIGHTS,
    LEVEL_WEIGHTS,
    StepScore,
    Weights,
    score_fight,
    score_submission,
    streak_multiplier,
)
from .session import Session
from .timeline import compare

#: Largest source a front-end may submit. Generous for any puzzle here, and a
#: bound on what a runaway paste costs to ship into a worker and back.
MAX_SOURCE = 64 * 1024

#: Stepped events kept from one run. The harness reports every line so that a
#: paused parent is never left waiting; a free-running fight in a loop would
#: otherwise hand the renderer millions of frames it could never show.
MAX_STEP_EVENTS = 2000

#: Longest repr shown for a test's input or output. Both ends survive, because
#: the ends are what identify a case (see `cli._echo`).
MAX_ECHO = 88


class ServiceError(Exception):
    """A request the service refused, with a stable machine-readable code.

    Refusals are values a front-end is expected to render, not crashes: a
    stale play id after a page reload, or a finish sent twice, is a normal
    thing for a client to do and a normal thing to explain.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_json(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class ExecutionFailed(Exception):
    """The child died without a result: the executor's analogue of a crash."""


class Executor(Protocol):
    """Runs `_harness.py` once. The only thing the service cannot do itself.

    ``commands`` are control lines written after the payload, for a stepped
    run. The reply is the child's whole stdout. Raise `TimeoutError` when the
    wall clock expires and `ExecutionFailed` for any other death.
    """

    #: Whether this transport contains code the player did not write. A
    #: browser worker is WebAssembly, and it is still not claimed as one.
    isolating: bool

    async def run(self, payload: dict, commands: Sequence[dict] = ()) -> str:
        ...  # pragma: no cover - protocol


def echo(value: Any) -> str:
    """``repr`` shortened in the middle, so both ends of a case survive."""
    text = value if isinstance(value, str) else repr(value)
    if len(text) <= MAX_ECHO:
        return text
    keep = (MAX_ECHO - 5) // 2
    return f"{text[:keep]} ... {text[-keep:]}"


def _first_sentence(text: str) -> str:
    head = text.strip().split(". ")[0].rstrip(".")
    return head + "."


def _accuracy_of(result: RunResult, tests: Sequence[TestCase]) -> float:
    """Fraction of the step's own cases that passed (`cli._accuracy_of`)."""
    if not tests:
        return 0.0
    return sum(1 for o in result.outcomes if o.passed) / len(tests)


def _outcomes(result: RunResult) -> list[dict[str, Any]]:
    return [
        {"name": o.name, "passed": o.passed, "got": o.got,
         "expected": o.expected, "error": o.error}
        for o in result.outcomes
    ]


def first_failure(result: RunResult, tests: Sequence[TestCase]) -> dict | None:
    """The first failing case in full: what it was given and what came back.

    The same content `cli._print_first_failure` prints, as data: without the
    input a player cannot reproduce the failure by hand, which is the first
    thing a beginner needs to do.
    """
    failed = [o for o in result.outcomes if not o.passed]
    if not failed:
        return None
    first = failed[0]
    case = {test.name: test for test in tests}.get(first.name)
    given: list[str] = []
    if case is not None:
        given = [echo(arg) for arg in case.args]
        given += [f"{key}={echo(val)}" for key, val in case.kwargs.items()]
    others = failed[1:]
    return {
        "name": first.name,
        "given": ", ".join(given),
        "expected": echo(first.expected),
        "got": echo(first.got),
        "error": first.error,
        "others": len(others),
        "others_same": bool(others) and all(
            o.error and o.error == first.error for o in others
        ),
    }


def _result_json(result: RunResult, tests: Sequence[TestCase]) -> dict[str, Any]:
    return {
        "passed": result.passed_count,
        "total": len(tests) if not result.outcomes else result.total_count,
        "all_passed": result.all_passed,
        "fatal": result.fatal,
        "error": result.error,
        "error_type": result.error_type,
        "outcomes": _outcomes(result),
        "first_failure": first_failure(result, tests),
        "stdout": result.stdout[-2000:],
        "ops": result.ops,
        "peak_bytes": result.peak_bytes,
    }


def _weights_json(weights: Weights) -> dict[str, float]:
    return {"accuracy": weights.accuracy, "speed": weights.speed,
            "functional": weights.functional}


def _step_events(out: str) -> list[dict[str, Any]]:
    """The stepped run's line events, bounded, in the order they happened."""
    events: list[dict[str, Any]] = []
    for line in out.splitlines():
        if '"event": "step"' not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("event") != "step":
            continue
        events.append({
            "line": int(event.get("line", 0)),
            "func": str(event.get("func", "")),
            "locals": {str(k): str(v) for k, v in (event.get("locals") or {}).items()},
            "error": str(event.get("error", "")),
        })
        if len(events) >= MAX_STEP_EVENTS:
            break
    return events


# --------------------------------------------------------------------------
# Per-play state
# --------------------------------------------------------------------------

@dataclass
class _LevelPlay:
    id: str
    level: Level
    seed: int
    decision: Decision
    tests: list[TestCase]
    ref_ops: int
    ref_peak: int
    started: float
    served: "daily_model.Daily | None" = None
    attempt: int = 0
    first_run_clean: bool = False
    code: str = ""
    result: RunResult = field(default_factory=RunResult)


@dataclass
class _FightPlay:
    id: str
    boss: BossLevel
    seed: int
    fight: fight_model.Fight
    code: str
    started: float
    #: Animation the renderer spent between lines, which is the engine's
    #: pacing and not the player's time (`cli._Pacer`).
    slept: float = 0.0
    last_call: float = 0.0
    index: int = 0
    state: str = "ready"
    crashed_first_run: bool = False
    #: Whether the current step has had its opening run yet; only that run's
    #: crash counts against `clean_first_run`.
    opened: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    paused_at: int = -1
    verdict: RunResult = field(default_factory=RunResult)
    result: RunResult = field(default_factory=RunResult)


class Service:
    """One player's game, driven by intents from a front-end.

    Holds the player's `Session` in memory and saves it through the same
    write-then-rename path as the CLI. ``on_save`` is called after every save,
    which is where the browser flushes its IndexedDB-backed filesystem.
    """

    def __init__(
        self,
        executor: Executor,
        *,
        session_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], str] | None = None,
        on_save: Callable[[], Any] | None = None,
    ) -> None:
        self.executor = executor
        self._clock = clock
        self._today = today or (lambda: date.today().isoformat())
        self._on_save = on_save
        self._session_path = session_path
        self.session = Session.load(session_path)
        self._plays: dict[str, _LevelPlay] = {}
        self._fights: dict[str, _FightPlay] = {}
        self._ids = itertools.count(1)
        self._benchmarks: dict[tuple, tuple[int, int]] = {}

    # -- execution ----------------------------------------------------------

    async def _execute(
        self,
        code: str,
        func_name: str,
        tests: Sequence[TestCase],
        *,
        source: Source,
        record_trace: bool = False,
        filename: str = SUBMISSION_FILENAME,
        mode: str = "",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> tuple[RunResult, str]:
        """Run code through the executor, with `run_code`'s semantics.

        ``source`` has no default for the reason `run_code`'s has none (N9):
        it is the argument that decides whether a stranger's Python may run,
        and forgetting it must be a `TypeError`, not a silent fast path.
        """
        if source.requires_isolation and not self.executor.isolating:
            raise SandboxUnavailable(
                "third-party code requires an isolating backend; "
                "this transport does not provide one"
            )
        payload = build_payload(
            code, func_name, tests, timeout=timeout,
            mem_limit_mb=DEFAULT_MEM_LIMIT_MB, record_trace=record_trace,
            filename=filename, mode=mode,
        )
        # A stepped run is released immediately: the renderer paces the
        # replay, so the child never has to wait on anyone.
        commands = [{"cmd": "run"}] if mode == "step" else []
        try:
            out = await self.executor.run(payload, commands)
        except TimeoutError:
            return RunResult(
                error=f"execution exceeded {timeout:g}s - check for an infinite loop",
                error_type="Timeout",
            ), ""
        except ExecutionFailed as exc:
            return RunResult(error=f"sandbox crashed: {exc}",
                             error_type="SandboxCrash"), ""
        return parse_reply(out), out

    async def _reference(self, level: Level, seed: int,
                         difficulty: Difficulty | None,
                         tests: Sequence[TestCase]) -> tuple[int, int]:
        """`runner.reference_benchmark`, through the injected executor.

        Keyed on difficulty for the same reason: a hard variant's ops divided
        by a default-sized reference would punish a size the game chose.
        """
        key = ("level", level.id, seed, difficulty.level if difficulty else -1.0)
        if key in self._benchmarks:
            return self._benchmarks[key]
        result, _ = await self._execute(
            level.reference, level.func_name, tests,
            source=level.source, filename=REFERENCE_FILENAME,
        )
        if result.fatal or not result.all_passed:
            raise ServiceError(
                "reference_failed",
                f"reference solution for {level.id} failed on variant {seed}: "
                f"{result.error or 'wrong answer'}",
            )
        self._benchmarks[key] = (result.ops, result.peak_bytes)
        return self._benchmarks[key]

    async def _boss_reference(self, boss: BossLevel, index: int,
                              seed: int) -> tuple[int, int]:
        """`runner.boss_step_benchmark`, through the injected executor."""
        key = ("boss", boss.id, index, seed)
        if key in self._benchmarks:
            return self._benchmarks[key]
        step = boss.step(index)
        result, _ = await self._execute(
            boss.reference_source(index), step.func_name, step.tests_for(seed),
            source=boss.source, filename=REFERENCE_FILENAME,
        )
        if result.fatal or not result.all_passed:
            raise ServiceError(
                "reference_failed",
                f"reference for {boss.id} step {index + 1} failed: "
                f"{result.error or 'wrong answer'}",
            )
        self._benchmarks[key] = (result.ops, result.peak_bytes)
        return self._benchmarks[key]

    def _save(self) -> None:
        self.session.save()
        if self._on_save is not None:
            self._on_save()

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}{next(self._ids)}"

    # -- queries ------------------------------------------------------------

    def hello(self) -> dict[str, Any]:
        """What this engine is, so a client can show it and check it."""
        from . import __version__

        return {
            "engine": __version__,
            "python": sys.version.split()[0],
            "levels": len(level_registry.all_levels()),
            "bosses": len(level_registry.all_bosses()),
            "isolating": bool(self.executor.isolating),
        }

    def _next_level(self) -> str | None:
        """The first level without a star, in campaign order (`campaign`)."""
        for level in level_registry.all_levels():
            record = self.session.levels.get(level.id)
            if not (record and record.best_stars):
                return level.id
        return None

    def catalogue(self) -> dict[str, Any]:
        """Every world, level and boss, with this player's record on each."""
        worlds: list[dict[str, Any]] = []
        bosses = level_registry.all_bosses()
        for number, levels in sorted(level_registry.worlds().items()):
            rows = []
            for level in levels:
                record = self.session.levels.get(level.id)
                rows.append({
                    "id": level.id,
                    "index": level.index,
                    "title": level.title,
                    "summary": _first_sentence(level.brief),
                    "par": level.par_seconds,
                    "tags": list(level.tags),
                    "multiplier": level.multiplier,
                    "stars": record.best_stars if record else 0,
                    "best": record.best_total if record else 0.0,
                    "attempts": record.attempts if record else 0,
                })
            worlds.append({
                "world": number,
                "title": levels[0].world_title if levels else "",
                "levels": rows,
                "bosses": [
                    {"id": boss.id, "title": boss.title,
                     "summary": _first_sentence(boss.brief),
                     "steps": boss.step_count, "par": boss.par_seconds}
                    for boss in bosses if boss.world == number
                ],
            })
        return {"worlds": worlds, "next": self._next_level(),
                "daily": self.daily(), "player": self.player()}

    def player(self) -> dict[str, Any]:
        """The character sheet: totals, streak and measured mastery."""
        session = self.session
        levels = level_registry.all_levels()
        mastery = session.current_mastery()
        return {
            "total_score": session.total_score,
            "streak": session.streak,
            "streak_multiplier": streak_multiplier(session.streak),
            "cleared": sum(1 for r in session.levels.values() if r.best_stars),
            "levels": len(levels),
            "stars": sum(r.best_stars for r in session.levels.values()),
            "max_stars": 3 * len(levels),
            "mastery": [
                {"tag": tag, "value": round(mastery.value(tag), 3),
                 "observations": mastery.tags[tag].observations,
                 "confident": mastery.confident(tag)}
                for tag in sorted(mastery.known_tags(),
                                  key=lambda t: mastery.value(t))
            ],
        }

    def daily(self) -> dict[str, Any] | None:
        """Today's challenge: the same level and variant for everyone."""
        today = self._today()
        served = daily_model.choose(
            today, [level.id for level in level_registry.all_levels()]
        )
        if served is None:
            return None
        level = level_registry.get_level(served.level_id)
        played = self.session.daily_played(today)
        return {
            "date": today,
            "level_id": served.level_id,
            "title": level.title,
            "seed": served.seed,
            "played": None if played is None else
            {"total": played.total, "stars": played.stars},
            "streak": daily_model.streak(
                [a.date for a in self.session.dailies], today
            ),
        }

    # -- levels -------------------------------------------------------------

    async def open_level(self, level_id: str, *,
                         daily: bool = False) -> dict[str, Any]:
        """Prepare a level and start the clock on the player's solve time.

        The reference is benchmarked *before* the clock starts: a cold worker
        is the engine's wait, not the player's, and Speed is the player's time.
        """
        try:
            level = level_registry.get_level(level_id)
        except KeyError:
            raise ServiceError("unknown_level", f"no such level: {level_id}")

        served = None
        if daily:
            served = daily_model.choose(
                self._today(), [lvl.id for lvl in level_registry.all_levels()]
            )
            if served is None or served.level_id != level.id:
                raise ServiceError("not_daily", f"{level_id} is not today's daily")
            seed = served.seed
            # A daily imposes its difficulty (T5 W1): adapting a shared
            # challenge would hand everyone a different puzzle.
            decision = Decision(
                difficulty=Difficulty(DEFAULT_DIFFICULTY.level),
                source="fixed",
                reason="a daily challenge is the same for everyone, so this "
                       "variant is not adapted to you",
                evidence={"imposed": DEFAULT_DIFFICULTY.level},
            )
        else:
            seed = self.session.next_seed(level.id)
            decision = choose_difficulty(
                level.tags, self.session.current_mastery(), self.session.vibe
            )

        tests = level.tests_for(seed, decision.difficulty)
        ref_ops, ref_peak = await self._reference(
            level, seed, decision.difficulty, tests
        )
        play = _LevelPlay(
            id=self._new_id("p"), level=level, seed=seed, decision=decision,
            tests=tests, ref_ops=ref_ops, ref_peak=ref_peak,
            started=self._clock(), served=served, code=level.starter,
        )
        self._plays[play.id] = play
        today = self.daily() if served is not None else None
        return {
            "play": play.id,
            "level": {
                "id": level.id,
                "world": level.world,
                "world_title": level.world_title,
                "index": level.index,
                "title": level.title,
                "brief": level.brief,
                "func_name": level.func_name,
                "starter": level.starter,
                "par": level.par_seconds,
                "tags": list(level.tags),
                "style_goals": [style.DESCRIPTIONS.get(g, g)
                                for g in level.style_goals],
                "hints": len(level.hints),
            },
            "seed": seed,
            "cases": len(tests),
            "difficulty": {
                "level": decision.difficulty.level,
                "band": decision.difficulty.band,
                "source": decision.source,
                "reason": decision.reason,
            },
            "daily": None if served is None else {
                "date": served.date,
                "already": today["played"] if today else None,
            },
        }

    def _play(self, play_id: str) -> _LevelPlay:
        play = self._plays.get(play_id)
        if play is None:
            raise ServiceError("no_such_play",
                               "that level is no longer open -- open it again")
        return play

    async def run(self, play_id: str, code: str) -> dict[str, Any]:
        """One submission: every hidden case, with a trace of the first."""
        play = self._play(play_id)
        if not isinstance(code, str) or len(code) > MAX_SOURCE:
            raise ServiceError("too_large",
                               f"source must be at most {MAX_SOURCE} characters")
        play.attempt += 1
        play.code = code
        # The player's own code, typed on their own device (N9).
        result, _ = await self._execute(
            code, play.level.func_name, play.tests,
            source=Source.PLAYER, record_trace=True,
        )
        if play.attempt == 1:
            play.first_run_clean = not result.fatal
        play.result = result
        body = _result_json(result, play.tests)
        body.update({
            "attempt": play.attempt,
            # The earned ladder, reprinted whole each time (`_print_hints`).
            "hints": [] if result.all_passed
            else list(play.level.hints_after(play.attempt)),
            "trace": result.trace,
        })
        return body

    async def finish(self, play_id: str, *,
                     give_up: bool = False) -> dict[str, Any]:
        """Score, bank and close a play. Exactly once per play.

        Follows `cmd_play`: a solved level is banked, and so is an unsolved
        one the player chose to stop on, because a completed ranked attempt
        is real. Leaving without either is `abandon`, which banks nothing --
        an interrupted session is never silently declared passed or banked.
        """
        play = self._play(play_id)
        if play.attempt == 0:
            raise ServiceError("invalid_state", "nothing has been submitted yet")
        if not play.result.all_passed and not give_up:
            raise ServiceError("invalid_state",
                               "not solved yet -- keep going, or give up to bank it")
        # Removed before anything can fail, so a retried finish cannot bank
        # twice: the second call finds no play.
        del self._plays[play_id]

        level, result = play.level, play.result
        style_results = style.evaluate(play.code, level.func_name,
                                       level.style_goals)
        elapsed = max(0.0, self._clock() - play.started)
        weights = LEVEL_WEIGHTS
        score = score_submission(
            result,
            elapsed_seconds=elapsed,
            par_seconds=level.par_seconds,
            ref_ops=play.ref_ops,
            ref_peak_bytes=play.ref_peak,
            attempt=play.attempt,
            style_goals_met=style.all_met(style_results),
            first_run_clean=play.first_run_clean,
            weights=weights,
        )
        multipliers = {lvl.id: lvl.multiplier
                       for lvl in level_registry.all_levels()}
        outcome = self.session.submit(
            level.id, score, seed=play.seed, multipliers=multipliers,
            tags=level.tags,
        )
        daily_note = None
        if play.served is not None:
            entry = self.session.record_daily(
                play.served.date, play.served.level_id, play.served.seed, score
            )
            daily_note = {"ranked": entry.ranked}
        run_id = self.session.save_run(level.id, {
            "level_id": level.id,
            "seed": play.seed,
            "difficulty": play.decision.difficulty.level,
            "difficulty_source": play.decision.source,
            "difficulty_reason": play.decision.reason,
            "attempt": play.attempt,
            "practice": False,
            "code": play.code,
            "score": score.to_json(),
            "result": result.to_json(),
        })
        self._save()

        advice = tips.generate(
            play.code, level.func_name, result, ref_ops=play.ref_ops,
            vibe=self.session.vibe, style_results=style_results,
        )
        return {
            "score": score.to_json(),
            "weights": _weights_json(weights),
            "elapsed": round(elapsed, 1),
            "par": level.par_seconds,
            "ops": result.ops,
            "ref_ops": play.ref_ops,
            "peak_bytes": result.peak_bytes,
            "ref_peak_bytes": play.ref_peak,
            "passed": result.passed_count,
            "total": len(play.tests),
            "all_passed": result.all_passed,
            "style": {style.DESCRIPTIONS.get(k, k): v
                      for k, v in style_results.items()},
            "outcome": {
                "improved": outcome["improved"],
                "cleared": outcome["cleared"],
                "streak": outcome["streak"],
                "streak_multiplier": outcome["streak_multiplier"],
            },
            "daily": daily_note,
            "tips": advice,
            "run_id": run_id,
            "code": play.code,
            "trace": result.trace,
            "next": self._next_up(level) if result.all_passed else None,
            "player": self.player(),
        }

    def abandon(self, play_id: str) -> dict[str, Any]:
        """Close a play without scoring it. Idempotent: closing twice is fine."""
        existed = self._plays.pop(play_id, None) is not None
        return {"closed": existed}

    def reset(self) -> dict[str, Any]:
        """Delete this player's progress *and* their saved runs.

        Further than `vibecoder reset`, which removes only the profile: on a
        phone there is no terminal from which to find `runs/` afterwards, and
        a run artifact is the code somebody wrote. Wiping progress while
        keeping their code would be the surprising half of the operation.
        """
        path = self.session.path
        removed = 0
        runs = path.parent / "runs"
        if runs.is_dir():
            for artifact in runs.glob("*.json"):
                artifact.unlink()
                removed += 1
        if path.exists():
            path.unlink()
        self.session = Session.load(self._session_path)
        self._plays.clear()
        self._fights.clear()
        if self._on_save is not None:
            self._on_save()
        return {"runs_removed": removed}

    def _next_up(self, level: Level) -> dict[str, Any]:
        """What to play after a clear: a drill if one is warranted, else the
        next level in campaign order (`cli._print_next_up`)."""
        ordered = list(level_registry.all_levels())
        drill = choose_drill(ordered, self.session.current_mastery())
        following = None
        ids = [lvl.id for lvl in ordered]
        if level.id in ids:
            rest = ordered[ids.index(level.id) + 1:]
            if rest:
                following = rest[0]
        return {
            "drill": None if drill is None else
            {"tag": drill.tag, "levels": list(drill.levels), "reason": drill.reason},
            "level": None if following is None else
            {"id": following.id, "title": following.title,
             "summary": _first_sentence(following.brief)},
            "world_complete": following is not None and following.world != level.world,
            "campaign_complete": following is None,
        }

    # -- bosses -------------------------------------------------------------

    def _fight_json(self, play: _FightPlay) -> dict[str, Any]:
        fight = play.fight
        return {
            "hp": fight.hp,
            "remaining": fight.remaining,
            "repairs": fight.repairs,
            "repairs_left": fight.repairs_left,
            "spent": fight.spent,
            "cleared": fight.cleared,
            "down": fight.down,
        }

    def _fight(self, fight_id: str) -> _FightPlay:
        play = self._fights.get(fight_id)
        if play is None:
            raise ServiceError("no_such_fight",
                               "that fight is over -- start it again")
        return play

    def _pace(self, play: _FightPlay, slept: float) -> None:
        """Take the renderer's animation off the clock (`cli._Pacer`).

        Bounded by the wall time since the last call, so no report can make
        Speed faster than the time that actually passed.
        """
        now = self._clock()
        window = max(0.0, now - play.last_call)
        play.slept += min(max(0.0, float(slept or 0.0)), window)
        play.last_call = now

    async def open_boss(self, boss_id: str) -> dict[str, Any]:
        """Start a fight. The clock starts here; a fight is not banked (Q84)."""
        try:
            boss = level_registry.get_boss(boss_id)
        except KeyError:
            raise ServiceError("unknown_boss", f"no such boss: {boss_id}")
        now = self._clock()
        play = _FightPlay(
            id=self._new_id("f"), boss=boss, seed=1,
            fight=fight_model.Fight(steps=boss.step_count),
            code=boss.starter_source(0), started=now, last_call=now,
        )
        self._fights[play.id] = play
        return {
            "fight": play.id,
            "boss": {
                "id": boss.id,
                "world": boss.world,
                "title": boss.title,
                "brief": boss.brief,
                "par": boss.par_seconds,
                "steps": [
                    {"title": step.title, "func_name": step.func_name,
                     "brief": step.brief, "uses": list(step.uses)}
                    for step in boss.steps
                ],
            },
            "code": play.code,
            "state": self._fight_json(play),
        }

    async def boss_attempt(self, fight_id: str, code: str | None = None, *,
                           slept: float = 0.0) -> dict[str, Any]:
        """Run the current step from the top, and say how it went.

        Two runs, concurrently: the watched one, stepped, over the step's
        first case; and the verdict, an ordinary run over every case. The
        watched run is what the renderer replays line by line and pauses on
        a raise; the verdict is what decides a clear and what a repair's
        heal is scaled by (`cli._accuracy_of`, Q72). The CLI runs them one
        after the other because its child is blocked on a person; here
        neither waits on anyone.
        """
        play = self._fight(fight_id)
        self._pace(play, slept)
        if play.state != "ready":
            raise ServiceError("invalid_state", f"the fight is {play.state}")
        if code is not None:
            self._accept_code(play, code)
        return await self._attempt(play)

    def _accept_code(self, play: _FightPlay, code: str) -> None:
        if not isinstance(code, str) or len(code) > MAX_SOURCE:
            raise ServiceError("too_large",
                               f"source must be at most {MAX_SOURCE} characters")
        play.code = code

    async def _attempt(self, play: _FightPlay) -> dict[str, Any]:
        boss, index = play.boss, play.index
        step = boss.step(index)
        tests = step.tests_for(play.seed)
        play.code = step.with_stub(play.code)
        # The player's own code on the player's own device (N9), twice.
        (watched, out), (verdict, _) = await asyncio.gather(
            self._execute(play.code, step.func_name, tests[:1],
                          source=Source.PLAYER, mode="step"),
            self._execute(play.code, step.func_name, tests,
                          source=Source.PLAYER),
        )
        events = _step_events(out)
        play.events, play.result, play.verdict = events, watched, verdict

        # Only the step's opening run can cost the fight its clean start.
        failing = next((i for i, e in enumerate(events) if e["error"]), None)
        crashed = failing is not None or bool(watched.error)
        if not play.opened:
            play.opened = True
            play.crashed_first_run = play.crashed_first_run or crashed

        accuracy = _accuracy_of(verdict, tests)
        body: dict[str, Any] = {
            "step": index,
            "code": play.code,
            "events": events,
            "resume_at": 0,
            "divergence": None,
            "accuracy": accuracy,
            "verdict": _result_json(verdict, tests),
            "watched": {"error": watched.error, "error_type": watched.error_type,
                        "outcomes": _outcomes(watched)},
        }

        if failing is not None:
            # Paused *on* the line that raised (T3 criterion 2).
            play.state = "crashed"
            play.paused_at = failing
            body.update(outcome="crashed", paused_at=failing,
                        line=events[failing]["line"],
                        error=events[failing]["error"])
        elif not watched.error and accuracy == 1.0:
            dealt = play.fight.clear(index)
            spent = play.fight.spent_on(index)
            play.index += 1
            play.opened = False
            if play.index >= boss.step_count:
                play.state = "won"
            else:
                play.state = "ready"
                play.code = boss.step(play.index).with_stub(play.code)
            body.update(outcome="cleared", dealt=dealt, spent=spent,
                        code=play.code)
        else:
            play.state = "wrong"
            play.paused_at = -1
            body.update(outcome="wrong",
                        line=self._def_line(play.code, step.func_name),
                        error=watched.error or self._wrong_answer(verdict))

        if play.state in ("crashed", "wrong") and not play.fight.can_repair:
            # Nothing left to spend: the step cannot clear, so the fight
            # stops here and is scored on what it achieved.
            play.state = "over"
            body["no_repairs"] = True
        body["fight"] = self._fight_json(play)
        body["state"] = play.state
        return body

    @staticmethod
    def _def_line(code: str, func_name: str) -> int:
        for number, line in enumerate(code.splitlines(), start=1):
            if line.strip().startswith(f"def {func_name}"):
                return number
        return 1

    @staticmethod
    def _wrong_answer(verdict: RunResult) -> str:
        failed = [o for o in verdict.outcomes if not o.passed]
        if not failed:
            return "the answer was wrong"
        first = failed[0]
        if first.error:
            return first.error
        return f"expected {first.expected}, got {first.got}"

    async def boss_repair(self, fight_id: str, code: str, *,
                          slept: float = 0.0) -> dict[str, Any]:
        """Spend a repair on an edit, then carry on.

        After a raise, the edited source re-runs from the top against the
        same input and is checked against the prefix already watched
        (strategy A, W5); the renderer resumes at the paused step, or at the
        first step that stopped matching. After a wrong answer there is
        nothing to resume, so the step simply runs again.

        The heal is priced on the code **as it failed** -- the verdict the
        attempt already measured -- never on the fix (`cli._offer_repair`).
        """
        play = self._fight(fight_id)
        self._pace(play, slept)
        if play.state not in ("crashed", "wrong"):
            raise ServiceError("invalid_state", f"the fight is {play.state}")
        tests = play.boss.step(play.index).tests_for(play.seed)
        cost = play.fight.repair(_accuracy_of(play.verdict, tests))
        if cost is None:
            play.state = "over"
            raise ServiceError("no_repairs", "no repairs left")
        self._accept_code(play, code)
        repaired = {"healed": cost.healed, "accuracy": cost.accuracy,
                    "message": str(cost)}

        if play.state == "crashed":
            original, target = play.events, play.paused_at
            play.state = "ready"
            body = await self._attempt(play)
            divergence = compare(original, body["events"], upto=target)
            resume = target if divergence is None else divergence.index
            body["resume_at"] = resume
            body["divergence"] = None if divergence is None else {
                "index": divergence.index, "reason": divergence.reason}
            if body.get("outcome") == "crashed" and body["paused_at"] < resume:
                # The same raise, still before where the player was looking:
                # the fix did not reach it.
                body["resume_at"] = body["paused_at"]
        else:
            play.state = "ready"
            body = await self._attempt(play)
        body["repair"] = repaired
        return body

    async def boss_finish(self, fight_id: str, *,
                          slept: float = 0.0) -> dict[str, Any]:
        """Measure every step against the final source and score the fight.

        Called whether or not it was cleared, like `cli._score_the_fight`: an
        abandoned fight is scored on what it achieved, because a zero given
        for a reason is information and a blank is not. Not banked (Q84).
        """
        play = self._fight(fight_id)
        self._pace(play, slept)
        del self._fights[fight_id]
        boss = play.boss
        elapsed = max(0.0, self._clock() - play.started - play.slept)
        weights = BOSS_WEIGHTS

        async def measure(index: int) -> StepScore:
            step = boss.step(index)
            tests = step.tests_for(play.seed)
            result, _ = await self._execute(
                play.code, step.func_name, tests, source=Source.PLAYER)
            ref_ops, ref_peak = await self._boss_reference(boss, index, play.seed)
            goals = style.evaluate(play.code, step.func_name, step.style_goals)
            return StepScore(
                passed=sum(1 for o in result.outcomes if o.passed),
                total=len(tests), ops=result.ops, ref_ops=ref_ops,
                peak_bytes=result.peak_bytes, ref_peak_bytes=ref_peak,
                style_met=style.all_met(goals),
            )

        steps = list(await asyncio.gather(
            *(measure(i) for i in range(boss.step_count))
        ))
        score = score_fight(
            steps, elapsed_seconds=elapsed, par_seconds=boss.par_seconds,
            repairs_spent=play.fight.spent,
            crashed_first_run=play.crashed_first_run, weights=weights,
        )
        cleared_all = play.state == "won"
        return {
            "score": score.to_json(),
            "weights": _weights_json(weights),
            "elapsed": round(elapsed, 1),
            "animation": round(play.slept, 1),
            "par": boss.par_seconds,
            "steps": [
                {"title": boss.step(i).title, "passed": s.passed,
                 "total": s.total, "ops": s.ops, "ref_ops": s.ref_ops}
                for i, s in enumerate(steps)
            ],
            "ending": "down" if play.fight.down else
            ("survives" if cleared_all else "stopped"),
            "fight": self._fight_json(play),
            "banked": False,
        }


__all__ = [
    "ExecutionFailed",
    "Executor",
    "MAX_SOURCE",
    "Service",
    "ServiceError",
    "echo",
    "first_failure",
]
