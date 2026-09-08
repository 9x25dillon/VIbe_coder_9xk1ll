"""VibeCoder command line.

    vibecoder profile <path>        build a Vibe Vector from a codebase
    vibecoder levels                list levels, ordered by the Vibe Vector
    vibecoder play <level-id>       play a level
    vibecoder status                progression, stars and global score
    vibecoder replay <run-id>       slow-motion playback of a recorded run
    vibecoder verify                run every level's reference against its tests
    vibecoder showcase              render every visual element
    vibecoder boss <id>             run a boss fight step by step
    vibecoder vision                animate your last run as a machine
    vibecoder reset                 delete the local profile

All output is drawn through the renderer in ``ui.py``, which detects what the
output stream can take. Piping any command produces plain text with no escape
sequences; ``NO_COLOR=1`` does the same on a terminal.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Sequence

from . import levels as level_registry
from . import sandbox
from . import fight as fight_model
from . import repair
from . import style, tips
from .ingest import ArchiveRejected
from .models import Level, RunResult, Source, TestCase, VibeVector
from .profiler import (
    CONVENTION_PLURALS,
    CONVENTIONS,
    profile_path,
    recommend,
    style_signature,
)
from .runner import (
    LiveRun,
    boss_step_benchmark,
    reference_benchmark,
    run_code,
    run_submission,
)
from .scoring import (
    BOSS_WEIGHTS,
    LEVEL_WEIGHTS,
    StepScore,
    score_fight,
    score_submission,
    streak_multiplier,
)
from .session import Session
from .replay import play as play_replay
from .vision import play as vision_play
from .ui import (
    ACCENT,
    BAD,
    FAINT,
    GOLD,
    GOOD,
    INK,
    MUTED,
    VIOLET,
    WARN,
    renderer_for,
    wrap,
)

# One renderer per process, built from whatever the output stream turns out to
# be. Every escape code in this module goes through it -- see T6.
UI = renderer_for()


def heat_for(total: float) -> tuple[int, int, int]:
    """Colour a final score by how close it is to a three-star clear."""
    from .ui import heat

    return heat(min(1.0, total / 95.0))


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------

#: Room for a value in the vibe panel: the box is 64 wide, minus its two
#: borders, the leading space and the 16-column label.
PANEL_VALUE = 64 - 2 - 1 - 16


def _fit_path(text: str, limit: int = PANEL_VALUE) -> str:
    """Shorten a path from the left, because the tail is what identifies it.

    `UI.box` documents that its lines are already of known width and does not
    truncate, so an over-long value breaks out through the right-hand border --
    which a long enough directory has always been able to do, and an archive
    sitting in ``~/Downloads`` makes ordinary. The leading directories are the
    part a reader can lose: ``.../scratchpad/repo.zip`` still says which file
    was profiled.

    The marker is ASCII rather than a glyph so the line is the same width with
    and without Unicode, which is what keeps the box square at every
    capability level.
    """
    if len(text) <= limit:
        return text
    return "..." + text[-(limit - 3):]


def _files_line(vibe: VibeVector) -> str:
    """The file count, saying what it is a count *of*.

    A partial profile reports "412 of 5,183" because the ratio is the useful
    part: it says the repository is twelve times what the budget covered, where
    a bare 412 would read as a small codebase.
    """
    if not vibe.partial:
        return str(vibe.files)
    return f"{vibe.files:,} of {vibe.files_seen:,}"


def cmd_profile(args: argparse.Namespace) -> int:
    try:
        vibe = profile_path(args.path)
    except ArchiveRejected as exc:
        # An archive we refuse to read is a thing the player can fix, so it
        # gets a sentence and an exit code rather than a traceback.
        print(f"\n  {UI.paint('rejected archive', WARN, bold=True)}  {exc}\n")
        return 2
    session = Session.load()
    session.vibe = vibe
    session.vibe_source = str(Path(args.path).resolve())
    session.save()

    if args.json:
        print(json.dumps(vibe.to_json(), indent=2))
        return 0

    print()
    print(UI.rule("VIBE VECTOR", width=64))

    signature = style_signature(vibe)
    stats = [
        f"{'source':<16}{_fit_path(session.vibe_source)}",
        f"{'files':<16}{_files_line(vibe)}",
        f"{'functions':<16}{vibe.functions}",
        f"{'code lines':<16}{vibe.code_lines}",
        f"{'avg func lines':<16}{vibe.avg_function_lines}",
        # A distribution, because one pathological function is not a habit.
        # `median / p90 / max` says "usually this, sometimes that, once this".
        f"{'complexity':<16}{vibe.median_complexity:.0f} median"
        f"   {vibe.p90_complexity:.0f} p90   {vibe.max_complexity} max",
        f"{'nesting':<16}{vibe.avg_nesting:.1f} avg   {vibe.max_nesting} deepest",
        f"{'docstrings':<16}{vibe.docstring_ratio:.0%} of functions",
        f"{'comments':<16}{vibe.comment_density:.0%} of lines",
    ]
    for line in UI.box(stats, width=64):
        print(line)

    if vibe.from_a_newer_build:
        # Said plainly rather than swallowed: the fields are being carried, not
        # understood, and a player comparing this against a fresh profile
        # deserves to know which numbers this build can actually read.
        print(
            f"\n  {UI.badge('NEWER PROFILE', VIOLET)}  "
            + UI.paint(
                f"written by a newer VibeCoder (schema {vibe.version}); "
                f"{len(vibe.unknown)} field(s) preserved but not read",
                MUTED,
            )
        )

    if vibe.partial:
        # Said once, plainly, next to the numbers it qualifies. A profile that
        # does not admit it is a sample is one somebody will compare against a
        # complete one without knowing.
        print(
            f"\n  {UI.badge('PARTIAL', WARN)}  "
            + UI.paint(
                f"stopped by {vibe.partial_reason}; "
                f"{vibe.files_seen - vibe.files:,} files not read",
                MUTED,
            )
        )

    if signature:
        print(f"\n  {UI.paint('STYLE', INK, bold=True)}")
        print(f"    {UI.paint(' / '.join(signature), ACCENT, bold=True)}")

    if vibe.libraries:
        print(f"\n  {UI.paint('LIBRARIES', INK, bold=True)}")
        top = list(vibe.libraries.items())[:8]
        ceiling = max(count for _, count in top)
        for line in UI.bar_chart(top, maximum=ceiling, suffix="", width=18):
            print(line)

    if vibe.patterns:
        print(f"\n  {UI.paint('PATTERNS', INK, bold=True)}")
        ranked = sorted(vibe.patterns.items(), key=lambda kv: -kv[1])[:8]
        for line in UI.bar_chart([(k, v * 100) for k, v in ranked]):
            print(line)

    if vibe.naming:
        # Functions and variables only. Class names are judged separately
        # below, against their own convention -- pooling them here is what
        # made PascalCase read as 0% in a codebase full of classes.
        print(f"\n  {UI.paint('NAMING  (functions and variables)', INK, bold=True)}")
        for name, share in list(vibe.naming.items())[:3]:
            print(f"    {name:<18} {UI.gauge(share * 100, width=22, rgb=VIOLET)} {share:5.0%}")

    if vibe.conventions:
        # Judged per identifier kind, because PEP 8 asks for different shapes
        # in each and a single pooled percentage cannot tell a well-named
        # class from a Java-style function.
        print(f"\n  {UI.paint('PEP 8 CONVENTIONS', INK, bold=True)}")
        for kind, share in vibe.conventions.items():
            label = f"{CONVENTION_PLURALS[kind]} are {CONVENTIONS[kind]}"
            print(
                f"    {label:<30} {UI.gauge(share * 100, width=16, rgb=GOOD)} "
                f"{share:5.0%}"
            )

    if vibe.exceptions_caught:
        print(f"\n  {UI.paint('EXCEPTIONS HANDLED', INK, bold=True)}")
        caught = "  ".join(
            UI.badge(f"{name} {count}", WARN)
            for name, count in list(vibe.exceptions_caught.items())[:6]
        )
        print(f"    {caught}")

    print(f"\n  {UI.paint('TAGS', INK, bold=True)}")
    tags = "  ".join(UI.badge(tag, ACCENT) for tag in vibe.tags) or "(none)"
    print(f"    {tags}")
    print(f"\n  {UI.paint(f'saved to {session.path}', FAINT)}\n")
    return 0


# --------------------------------------------------------------------------
# levels
# --------------------------------------------------------------------------

def cmd_levels(args: argparse.Namespace) -> int:
    session = Session.load()
    all_levels = list(level_registry.all_levels())

    if args.map:
        print()
        entries = [
            {
                "world": lvl.world,
                "world_title": lvl.world_title,
                "id": lvl.id,
                "title": lvl.title,
                "stars": session.levels[lvl.id].best_stars
                if lvl.id in session.levels
                else 0,
            }
            for lvl in all_levels
        ]
        bosses = [
            {"world": boss.world, "id": boss.id, "title": boss.title}
            for boss in level_registry.all_bosses()
        ]
        for line in UI.level_map(entries, bosses=bosses):
            print(line)
        print()
        return 0

    if session.vibe and not args.campaign:
        ordered = recommend(all_levels, session.vibe)
        heading = "RECOMMENDED FOR YOUR VIBE"
    else:
        ordered = all_levels
        heading = "CAMPAIGN ORDER"

    print()
    print(UI.rule(heading, width=76))
    current_world = None
    for level in ordered:
        if args.campaign and level.world != current_world:
            current_world = level.world
            print(
                f"\n  {UI.paint(f'World {level.world}', ACCENT, bold=True)} "
                f"{UI.paint(level.world_title, MUTED)}"
            )
        record = session.levels.get(level.id)
        stars = UI.stars(record.best_stars if record else 0)
        best = f"{record.best_total:6.1f}" if record else "     -"
        tags = UI.paint(",".join(level.tags), FAINT)
        print(f"    {stars}  {best}  {level.id:<16} {level.title:<28} {tags}")

    # Bosses are listed separately rather than folded in among the levels.
    # They are a different shape -- n functions, no banked stars, their own
    # command -- and until now they appeared in no listing at all, so the only
    # way to reach one was to already know its id (T3 W8).
    bosses = level_registry.all_bosses()
    if bosses:
        print()
        print(UI.rule("BOSS FIGHTS", width=76))
        for boss in bosses:
            tags = UI.paint(",".join(boss.tags), FAINT)
            print(
                f"    {UI.paint(UI.glyph('node_boss'), BAD)}  "
                f"{UI.paint(f'W{boss.world}', FAINT)}  "
                f"{boss.id:<16} {boss.title:<28} {tags}"
            )
        print(
            f"\n    {UI.paint('play one with', FAINT)} "
            + UI.paint(f"vibecoder boss {bosses[0].id} --live", MUTED)
        )

    if not session.vibe:
        print(
            "\n  "
            + UI.paint(
                "No Vibe Vector yet. Run `vibecoder profile <path>` to "
                "personalise this ordering.",
                FAINT,
            )
        )
    print()
    return 0


# --------------------------------------------------------------------------
# play
# --------------------------------------------------------------------------

#: Longest argument or value echoed back in the failure block. A 600-element
#: list is the input to one of the beginner levels, and printing it would bury
#: the point rather than make it.
MAX_ECHO = 88


def _echo(value: object) -> str:
    """``repr`` of a value, shortened in the middle so both ends survive.

    The ends are what identify a case -- the first few items say what kind of
    data it is, the last few show where it stops -- so a middle ellipsis keeps
    more meaning than a truncated tail.
    """
    text = value if isinstance(value, str) else repr(value)
    if len(text) <= MAX_ECHO:
        return text
    keep = (MAX_ECHO - 5) // 2
    return f"{text[:keep]} ... {text[-keep:]}"


def _print_first_failure(result: RunResult, tests: Sequence[TestCase]) -> None:
    """Show the first failing case in full: input, expectation, and outcome.

    The pass/fail list says *which* case failed and the score says how badly,
    but neither says what the code was given -- and without the input a player
    cannot reproduce the failure by hand, which is the first thing a beginner
    needs to do. Only the first failure is expanded: when a program is broken
    the later cases are usually the same bug seen again, and eight copies of
    it teaches nothing the first did not.
    """
    failed = [o for o in result.outcomes if not o.passed]
    if not failed:
        return
    first = failed[0]
    by_name = {test.name: test for test in tests}
    case = by_name.get(first.name)

    print(f"\n{UI.rule('WHAT WENT WRONG', width=76)}\n")
    if case is not None and (case.args or case.kwargs):
        arguments = [_echo(arg) for arg in case.args]
        arguments += [f"{key}={_echo(val)}" for key, val in case.kwargs.items()]
        print(f"  {UI.paint('given', MUTED)}       {', '.join(arguments)}")
    if first.error:
        print(f"  {UI.paint('your code', MUTED)}   raised {UI.paint(first.error, BAD)}")
    else:
        print(f"  {UI.paint('expected', MUTED)}    {_echo(first.expected)}")
        print(f"  {UI.paint('you gave', MUTED)}    {UI.paint(_echo(first.got), BAD)}")

    others = len(failed) - 1
    if others:
        plural = "case" if others == 1 else "cases"
        same = sum(1 for o in failed[1:] if o.error and o.error == first.error)
        if same == others:
            note = f"The other {others} {plural} stopped the same way."
        else:
            note = f"{others} more {plural} failed."
        print(f"\n  {UI.paint(note, FAINT)}")


def _print_next_up(level: Level, session: Session) -> None:
    """After a clear, name the level that follows.

    A game that ends a win by returning you to the shell has to be re-entered
    on willpower. Naming the next level -- and what it adds -- is the cheapest
    thing that turns one cleared level into two, and it is the same
    information the world map carries, at the moment it is most useful.
    """
    ordered = list(level_registry.all_levels())
    try:
        position = [lvl.id for lvl in ordered].index(level.id)
    except ValueError:
        return

    remaining = ordered[position + 1:]
    if not remaining:
        print(f"\n    {UI.badge('CAMPAIGN COMPLETE', GOLD)} "
              + UI.paint("every level cleared", GOLD, bold=True))
        return

    following = remaining[0]
    if following.world != level.world:
        # Finishing a world is the milestone worth marking; the next level
        # happens to be the first of the one after.
        print(f"\n    {UI.badge(f'WORLD {level.world} COMPLETE', GOLD)} "
              + UI.paint(level.world_title, GOLD, bold=True))
    print(
        f"\n    {UI.paint('next up', MUTED)}  "
        + UI.paint(following.title, ACCENT, bold=True)
        + UI.paint(f"   {following.id}", FAINT)
    )
    print(f"    {UI.paint(f'  {following.brief.split(chr(46))[0]}.', MUTED)}")


def _print_hints(level: Level, failed_attempts: int) -> None:
    """Reveal the hints this many failures have earned.

    Printed on the retry path only, so a player who is about to try again sees
    them and a player who has already solved it never does. The whole earned
    ladder is reprinted each time rather than only the newest line, because
    the earlier hints have scrolled away by now and the sequence is the point.
    """
    earned = level.hints_after(failed_attempts)
    if not earned:
        return
    print(f"\n{UI.rule('HINT', width=76)}\n")
    for hint in earned:
        for line in wrap(hint, 72, indent="    "):
            print(UI.paint(line, MUTED))
        print()


def _print_results(result: RunResult, tests: Sequence[TestCase] = ()) -> None:
    if result.fatal:
        print(f"\n  {UI.badge(result.error_type or 'ERROR', BAD)} {result.error}")
        return
    print()
    for outcome in result.outcomes:
        if outcome.passed:
            mark = UI.paint(UI.glyph("tick"), GOOD)
            print(f"  {mark} {UI.paint('PASS', GOOD)}  {outcome.name}")
        else:
            detail = outcome.error or f"got {outcome.got}, expected {outcome.expected}"
            mark = UI.paint(UI.glyph("cross"), BAD)
            print(
                f"  {mark} {UI.paint('FAIL', BAD)}  {outcome.name}  "
                f"{UI.paint(detail, FAINT)}"
            )

    ratio = result.passed_count / max(1, result.total_count)
    print(
        f"\n  {UI.gauge(ratio * 100, width=result.total_count * 2)}  "
        f"{result.passed_count}/{result.total_count} passed   "
        + UI.paint(
            f"{result.ops} ops   {result.peak_bytes / 1024:.1f} KiB peak", MUTED
        )
    )
    if result.stdout.strip():
        print(f"\n  {UI.paint('stdout:', FAINT)}\n{result.stdout.rstrip()}")

    _print_first_failure(result, tests)


def _edit(path: Path) -> None:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    subprocess.call([*editor.split(), str(path)])


def _load_level(level_id: str) -> Level:
    try:
        return level_registry.get_level(level_id)
    except KeyError:
        known = ", ".join(lvl.id for lvl in level_registry.all_levels())
        raise SystemExit(f"unknown level {level_id!r}. Available: {known}")


#: The reveal may spend this long on the machine view, and no longer. Chosen
#: to sit between "did something just happen" and "get on with it": long
#: enough to see the token take a lap, short enough that a player grinding
#: attempts never waits on it.
VISION_BUDGET = 2.5

#: Frames drawn within that budget. Sampling to a fixed count rather than
#: racing through 400 keeps each frame legible instead of a blur.
VISION_FRAMES = 36


def _play_vision(code: str, result: RunResult, *, enabled: bool) -> None:
    """The machine view, inside the reveal and on a strict budget.

    Silent whenever there is nothing honest to draw -- no trace, code that
    does not parse, a submission with no function -- because a failed
    submission already has a failure block to read and a broken drawing on top
    of it is noise. This never raises: the reveal is the hottest path in the
    product and nothing decorative may be able to break it.
    """
    if not enabled:
        return
    # A pipe gets nothing here, deliberately. `vibecoder vision` falls back to
    # a still frame because somebody asked to see the machine; the reveal is a
    # live flourish, and printing twenty lines of drawing into every CI log
    # and piped transcript is a change nobody asked for.
    if not UI.caps.animate:
        return
    trace = getattr(result, "trace", None) or []
    if not trace:
        return
    try:
        vision_play(
            code, trace, delay=0.08,
            budget=VISION_BUDGET, limit=VISION_FRAMES,
        )
    except (ValueError, OSError):
        return


def cmd_play(args: argparse.Namespace) -> int:
    level = _load_level(args.level_id)
    session = Session.load()
    seed = args.seed if args.seed is not None else session.next_seed(level.id)
    tests = level.tests_for(seed)

    print()
    print(UI.rule(f"WORLD {level.world}  {level.world_title}", width=76))
    print(
        f"\n  {UI.paint(level.title, INK, bold=True)}  "
        + UI.paint(f"({level.id}, variant {seed})", FAINT)
        + "\n"
    )
    for line in wrap(level.brief, 74):
        print(UI.paint(line, MUTED))
    if level.style_goals:
        goals = "; ".join(style.DESCRIPTIONS[g] for g in level.style_goals)
        print(f"\n  {UI.badge('STYLE GOAL +5%', GOLD)} {UI.paint(goals, WARN)}")
    print(f"\n  {UI.paint(f'par time: {level.par_seconds / 60:.0f} min', FAINT)}\n")

    workspace = Path(args.solution) if args.solution else None
    if workspace is None:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=f"_{level.func_name}.py", delete=False, encoding="utf-8"
        )
        handle.write(level.starter)
        handle.close()
        workspace = Path(handle.name)
        print(f"  {UI.paint(f'editing {workspace}', FAINT)}\n")

    ref_ops, ref_peak = reference_benchmark(level, seed)

    started = time.perf_counter()
    attempt = 0
    first_run_clean = False
    result = RunResult()

    while True:
        if not args.solution:
            _edit(workspace)

        code = workspace.read_text(encoding="utf-8")
        attempt += 1
        # `code` is read from a file the player chose, on their machine.
        result = run_submission(
            level, code, tests, record_trace=True, source=Source.PLAYER
        )
        if attempt == 1:
            first_run_clean = not result.fatal
        _print_results(result, tests)

        if result.all_passed or args.solution:
            break
        _print_hints(level, attempt)
        try:
            prompt = UI.paint("[enter] keep editing, 'q' to give up: ", FAINT)
            again = input(f"\n  {prompt}")
        except EOFError:
            break
        if again.strip().lower().startswith("q"):
            break

    style_results = style.evaluate(code, level.func_name, level.style_goals)

    # Scoring a file from disk has no honest solve time: the clock started
    # moments ago regardless of how long the player actually worked. Rather
    # than award a free 100 on Speed, that mode drops the axis, renormalises
    # the other two, and does not bank the result. A front-end that tracks
    # real solve time passes --elapsed and gets a fully ranked run.
    practice = bool(args.solution) and args.elapsed is None
    if args.elapsed is not None:
        elapsed = args.elapsed
    else:
        elapsed = time.perf_counter() - started
    weights = LEVEL_WEIGHTS.without_speed() if practice else LEVEL_WEIGHTS

    score = score_submission(
        result,
        elapsed_seconds=elapsed,
        par_seconds=level.par_seconds,
        ref_ops=ref_ops,
        ref_peak_bytes=ref_peak,
        attempt=attempt,
        style_goals_met=style.all_met(style_results),
        first_run_clean=first_run_clean,
        weights=weights,
    )

    if practice:
        outcome = {"improved": False, "cleared": False, "streak": session.streak}
    else:
        multipliers = {lvl.id: lvl.multiplier for lvl in level_registry.all_levels()}
        outcome = session.submit(level.id, score, seed=seed, multipliers=multipliers)

    run_id = session.save_run(
        level.id,
        {
            "level_id": level.id,
            "seed": seed,
            "attempt": attempt,
            "practice": practice,
            "code": code,
            "score": score.to_json(),
            "result": result.to_json(),
        },
    )
    if not practice:
        session.save()

    _play_vision(code, result, enabled=not args.no_vision)

    print()
    print(UI.rule("SCORE", width=76))
    print()

    # Each axis animates in as it is revealed; on a pipe these collapse to the
    # same final lines, so the transcript is identical either way.
    UI.reveal_gauge("accuracy", score.accuracy, weights.accuracy)
    if practice:
        print(
            f"    {'speed':<11} "
            + UI.paint("not measured in practice mode", FAINT)
        )
    else:
        UI.reveal_gauge(
            "speed",
            score.speed,
            weights.speed,
            f"({elapsed:.0f}s vs {level.par_seconds:.0f}s par)",
        )
    UI.reveal_gauge(
        "functional",
        score.functional,
        weights.functional,
        f"({result.ops} ops vs {ref_ops} reference)",
    )

    print(f"\n    {UI.paint('subtotal', MUTED)}    {score.subtotal:.1f}")
    for name, rate in score.bonuses.items():
        print(f"    {UI.badge(f'+{rate:.0%}', GOOD)} {UI.paint(name, GOOD)}")

    print(f"\n    {UI.paint('TOTAL', INK, bold=True)}       "
          f"{UI.paint(f'{score.total:.1f}', heat_for(score.total), bold=True)}")
    UI.star_burst(score.stars)

    if practice:
        print(
            "    "
            + UI.paint(
                "practice run - not banked. Pass --elapsed <seconds> to score "
                "a ranked attempt.",
                FAINT,
            )
        )

    if outcome["improved"]:
        print(f"    {UI.badge('NEW PERSONAL BEST', GOOD)}")
    if outcome["streak"] > 1:
        flames = UI.paint(UI.glyph("arrow") * min(outcome["streak"], 8), GOLD)
        print(
            f"    {flames} streak {outcome['streak']} "
            + UI.paint(
                f"(x{streak_multiplier(outcome['streak']):.1f} on the next "
                f"perfect clear)",
                MUTED,
            )
        )

    if result.all_passed and not practice:
        _print_next_up(level, session)

    advice = tips.generate(
        code,
        level.func_name,
        result,
        ref_ops=ref_ops,
        vibe=session.vibe,
        style_results=style_results,
    )
    if advice:
        print()
        print(UI.rule("VIBE TIPS", width=76))
        for tip in advice:
            print()
            for index, line in enumerate(wrap(tip, 72, indent="      ")):
                if index == 0:
                    marker = UI.paint(UI.glyph("arrow"), VIOLET)
                    print(f"    {marker} {line.lstrip()}")
                else:
                    print(line)

    print(
        "\n  "
        + UI.paint(
            f"run saved as {run_id} - replay it with `vibecoder replay {run_id}`",
            FAINT,
        )
        + "\n"
    )
    return 0


# --------------------------------------------------------------------------
# status / replay / verify / reset
# --------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    session = Session.load()
    all_levels = list(level_registry.all_levels())
    cleared = sum(1 for r in session.levels.values() if r.best_stars > 0)
    stars = sum(r.best_stars for r in session.levels.values())

    total_stars = len(all_levels) * 3

    print()
    for line in UI.banner():
        print("  " + line)
    print()
    print(UI.rule("PROGRESSION", width=76))
    print()
    print(f"    {'global score':<15}{UI.paint(f'{session.total_score:.1f}', GOLD, bold=True)}")
    print(
        f"    {'levels cleared':<15}"
        f"{UI.gauge(cleared, width=24, maximum=max(1, len(all_levels)))} "
        f"{cleared}/{len(all_levels)}"
    )
    print(
        f"    {'stars':<15}"
        f"{UI.gauge(stars, width=24, maximum=max(1, total_stars), rgb=GOLD)} "
        f"{stars}/{total_stars}"
    )
    print(f"    {'streak':<15}{session.streak}")
    print(
        f"    {'tokens':<15}"
        + "  ".join(UI.badge(f"{k} x{v}", VIOLET) for k, v in session.tokens.items())
    )
    print(
        f"    {'vibe source':<15}"
        + UI.paint(session.vibe_source or "(not profiled)", MUTED)
    )

    if session.levels:
        print()
        print(UI.rule("LEVELS", width=76))
        for level in all_levels:
            record = session.levels.get(level.id)
            if not record:
                continue
            history = [h["total"] for h in record.history][-12:]
            trend = UI.sparkline(history) if len(history) > 1 else ""
            print(
                f"    {UI.stars(record.best_stars)}  {record.best_total:6.1f}  "
                f"{level.id:<16} {trend:<14} "
                + UI.paint(
                    f"{record.attempts} attempts, {len(record.seeds_played)} variants",
                    FAINT,
                )
            )

    print(f"\n  {UI.paint(f'profile: {session.path}', FAINT)}\n")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    session = Session.load()
    if not args.run_id:
        runs = session.list_runs()
        if not runs:
            print("no recorded runs yet - play a level first")
            return 1
        print("\n  recorded runs:")
        for run in runs[-20:]:
            print(f"    {run}")
        print()
        return 0

    try:
        payload = session.load_run(args.run_id)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))

    trace = payload.get("result", {}).get("trace", [])
    print()
    print(UI.rule(f"REPLAY  {args.run_id}", width=76))
    print(
        "  "
        + UI.paint(f"variant {payload.get('seed')}, {len(trace)} steps", FAINT)
    )
    play_replay(
        payload["code"],
        trace,
        delay=args.delay,
        interactive=args.step,
    )
    return 0


def cmd_vision(args: argparse.Namespace) -> int:
    """Animate a recorded run as the machine its function describes.

    Its own command rather than part of the score reveal: the reveal is the
    hottest path in the product, and a visual that is still finding its feet
    does not belong there until it has earned the place.
    """
    session = Session.load()
    run_id = args.run_id
    if not run_id:
        runs = session.list_runs()
        if not runs:
            print("no recorded runs yet - play a level first")
            return 1
        run_id = runs[-1]

    try:
        payload = session.load_run(run_id)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))

    trace = payload.get("result", {}).get("trace", [])
    if not trace:
        print(f"run {run_id} recorded no trace - nothing to animate")
        return 1

    print()
    print(UI.rule(f"VISION  {run_id}", width=76))
    print("  " + UI.paint(f"{len(trace)} steps", FAINT))
    try:
        vision_play(
            payload["code"],
            trace,
            function=args.function,
            delay=args.delay,
            interactive=args.step,
        )
    except ValueError as exc:
        print(f"\n  {UI.paint('cannot draw this run', WARN, bold=True)}  {exc}\n")
        return 2
    return 0


#: Seconds per line when a live fight runs itself. The design's figure is
#: 2.0, which is two minutes for a 60-line function -- T3 names that as a
#: hazard rather than a setting, so this is the floor and `--speed` moves it.
LIVE_DELAY = 0.35

#: After this many laps of the same line, stop waiting on it. The hazard list
#: calls for auto-fast-forward through loop bodies; a loop is exactly where a
#: fixed delay stops teaching and starts costing.
LOOP_PATIENCE = 3


class _Pacer:
    """Sleeps the fight's slow motion, and remembers how long it slept.

    Speed is the *player's* time (CLAUDE.md S4), and a live fight's wall clock
    is not: most of it is the engine deliberately waiting between lines so the
    run can be watched. Counting that would score a display setting -- the
    same fight played at `--speed 0.1` and `--speed 2.0` would earn different
    marks for identical play, which is M1's shape a fourth time.

    So the engine subtracts its own animation from the clock. What is left is
    the time the player was actually in control: reading the trace, and typing
    in the repair pane. Measured around the sleep rather than accumulated from
    `delay`, because `time.sleep` overshoots and the correction has to be of
    what really happened.
    """

    def __init__(self, delay: float) -> None:
        self.delay = max(0.0, delay)
        self.slept = 0.0

    def pause(self) -> None:
        if not self.delay:
            return
        before = time.perf_counter()
        time.sleep(self.delay)
        self.slept += time.perf_counter() - before


def _live_step(boss, index: int, code: str, seed: int, pacer: "_Pacer",
               fight, fix: "Path | None" = None) -> tuple[bool, str, bool]:
    """Play one boss step until it clears or the player stops.

    An *attempt* is one run of the step. A step can fail two ways and both
    have to be repairable, because the common one is not the dramatic one:

    - **It crashes.** The run pauses on the line that raised and a repair
      resumes it in place (strategy A, T3 W4).
    - **It finishes with the wrong answer.** There is nothing to resume, so a
      repair re-runs the step from the top.

    The second is what a starter does — `return []` answers wrongly and never
    raises — so a fight that only offered a repair on a crash would refuse to
    let anyone play it from the beginning.

    Returns whether the step cleared, the source it cleared with, and whether
    its **opening** attempt died with a fatal error rather than merely
    answering wrongly. The source is not necessarily the one it started with:
    handing the edited text back is what makes T3's exit criterion 3 true of
    the *fight* rather than of one step, because later steps then run against
    what the player actually ended up writing.

    The crash flag is reported rather than stored because only the caller can
    see the whole fight, and `clean_first_run` is a claim about all of it.
    """
    step = boss.step(index)
    tests = step.tests_for(seed)
    code = _with_starter(code, step)
    print(f"\n  {UI.paint(step.title, INK, bold=True)}  "
          + UI.paint(f"{step.func_name}()", MUTED))
    opened_badly = False
    first = True
    while True:
        cleared, code, again, crashed = _attempt(
            step, tests, code, pacer, fight, fix
        )
        if first:
            opened_badly = crashed
            first = False
        if cleared:
            return True, code, opened_badly
        if not again:
            return False, code, opened_badly
        # A scripted fix is spent on the attempt that used it; a typed one is
        # not, because the player is sitting there and may want another go.
        fix = None
        print(f"    {UI.paint(UI.glyph('run'), ACCENT)} "
              + UI.paint("running the step again with your fix", MUTED))


def _attempt(step, tests, code: str, pacer: "_Pacer",
             fight, fix: "Path | None") -> tuple[bool, str, bool, bool]:
    """One run of one step.

    Returns ``(cleared, source, worth trying again, crashed)``. ``crashed``
    is whether this attempt died with a fatal error rather than finishing
    with the wrong answer -- the distinction the `clean_first_run` bonus
    rests on, and one the caller cannot recover afterwards because a
    repaired run drains clean.

    The pacing is here rather than in the child on purpose: the child runs a
    line, reports it, and blocks, so it never sleeps and the whole feel of the
    thing is the parent's business -- which is where the player is.
    """
    seen: dict[int, int] = {}
    previous: dict[str, str] = {}
    last_failure: tuple[int, str] | None = None
    crashed = False
    with LiveRun(code, step.func_name, tests[0], source=Source.PLAYER) as live:
        while True:
            event = live.step()
            if event is None:
                break
            seen[event.line] = seen.get(event.line, 0) + 1
            # The value that *changed*, not whichever happens to be last in
            # the dict. Same diff `vision.frames` does, and for the same
            # reason: the point of watching is seeing something move.
            changed = ""
            for name, value in event.locals.items():
                if previous.get(name) != value:
                    changed = f"{name} = {value}"
            previous = dict(event.locals)
            if event.failed and (event.line, event.error) == last_failure:
                # The same exception propagating through another frame of the
                # same file. One report per raise is what happened; repeating
                # it per frame reads as two different problems.
                continue
            if event.failed:
                last_failure = (event.line, event.error)
                crashed = True
                # Criterion 2: the run is paused *on* the line that raised,
                # not after it. `settrace` reports the exception while the
                # frame is still there; once it unwinds the line is gone.
                print(
                    f"    {UI.paint(f'{event.line:>3}', BAD, bold=True)} "
                    f"{UI.paint(UI.glyph('cross'), BAD, bold=True)} "
                    + UI.paint(event.error[:60], BAD)
                )
                if _repair_is_on_offer(fix) and not fight.can_repair:
                    # Aborting rather than falling through: the child is
                    # blocked mid-run, and draining one that nobody has
                    # released waits forever.
                    print(f"    {UI.paint('no repairs left', WARN, bold=True)}")
                    live.abort()
                    return False, code, False, crashed
                edited = _offer_repair(
                    code, step, tests, fight, fix,
                    line=event.line, error=event.error, values=event.locals,
                )
                fix = None
                if edited is not None:
                    code = edited
                    _apply_edit(live, code)
                    previous = dict(live.steps[-1].locals) if live.steps else {}
                    last_failure = None
                    continue
            else:
                print(
                    f"    {UI.paint(f'{event.line:>3}', FAINT)} "
                    f"{UI.paint(UI.glyph('arrow'), ACCENT)} "
                    + UI.paint(changed[:60], MUTED)
                )
            # A loop seen four times has taught what it is going to teach.
            if seen[event.line] <= LOOP_PATIENCE:
                pacer.pause()
        result = live.drain()

    # Not crashing is not the same as answering, and the one case we watched
    # is not the same as the set. The step is judged on all of them (Q72).
    verdict = _check(code, step, tests)
    accuracy = _accuracy_of(verdict, tests)
    crashed = crashed or bool(result.error)
    if not result.error and accuracy == 1.0:
        return True, code, False, crashed

    if result.error:
        print(f"    {UI.paint(result.error, BAD)}")
    else:
        # A percentage on its own cannot be acted on. Showing the case is
        # what makes the repair a decision rather than a guess -- the same
        # reason `_print_first_failure` exists for an ordinary level.
        print(f"    {UI.paint(f'{accuracy:.0%} of cases pass', BAD)}")
        _print_first_failure(verdict, tests)

    if _repair_is_on_offer(fix) and not fight.can_repair:
        print(f"    {UI.paint('no repairs left', WARN, bold=True)}")
        return False, code, False, crashed
    edited = _offer_repair(
        code, step, tests, fight, fix,
        line=_def_line(code, step.func_name),
        error=result.error or _wrong_answer(verdict),
        values={},
    )
    if edited is None:
        return False, code, False, crashed
    return False, edited, True, crashed


def _with_starter(code: str, step) -> str:
    """Add this step's stub to what the player has written so far.

    A boss is one shared file and each step brings a new function, so the
    buffer has to grow as the fight does. Without this a player reaches step
    two holding code that never mentions `above_floor`, and the fight asks
    them to write a signature it never showed them — which is the difference
    between a puzzle and a guessing game.

    Their earlier work is kept exactly as they wrote it; only the missing stub
    is appended. Already defining the function means they solved ahead, and
    nothing is added.
    """
    pattern = re.compile(rf"^\s*def {re.escape(step.func_name)}\b", re.MULTILINE)
    if pattern.search(code):
        return code
    return code.rstrip("\n") + "\n\n\n" + step.starter.strip("\n") + "\n"


def _repair_is_on_offer(fix: "Path | None") -> bool:
    """Whether anything could supply a fix: a file, or a person at a terminal."""
    return fix is not None or repair.available()


def _offer_repair(code: str, step, tests, fight, fix: "Path | None", *,
                  line: int, error: str, values: dict) -> "str | None":
    """Ask for a fix and spend a repair if one is given, else ``None``.

    One function, because a step can fail two ways and a repair has to cost
    the same either way -- the pool is only a resource if every way of using
    it draws on it.

    Accuracy is measured against the code *as it failed*, before any edit: the
    heal is scaled by how wrong this was, not by how good the fix is. It is
    skipped entirely when no repair is on offer, so a piped or scripted run
    does not pay for a verdict nothing reads.
    """
    if not _repair_is_on_offer(fix) or not fight.can_repair:
        return None
    accuracy = _accuracy_of(_check(code, step, tests), tests)
    if fix is not None:
        edited = fix.read_text(encoding="utf-8")
    else:
        # Q67: the player types the fix into the paused fight. The child stays
        # blocked while they do, and its budget counts executing time only, so
        # thinking is free.
        edited = repair.offer(code, line=line, error=error,
                              func=step.func_name, values=values,
                              title=step.title)
    if edited is None:
        return None
    # Spent only when an edit is actually applied: a player who opens the pane
    # and gives up has not used one.
    cost = fight.repair(accuracy)
    tone = GOOD if cost.healed <= 2 else WARN
    print(f"    {UI.paint(str(cost), tone)}  "
          + UI.paint(f"(accuracy {accuracy:.0%})", FAINT))
    return edited


def _check(code: str, step, tests) -> RunResult:
    """Run the step's whole test set. The verdict a live step is judged on."""
    return run_code(code, step.func_name, tests, source=Source.PLAYER)


def _accuracy_of(result: RunResult, tests) -> float:
    """Fraction of the step's own cases that passed.

    A stepped run watches *one* case, which cannot say how wrong the code was
    -- and how wrong it was is exactly what a repair's heal is scaled by. So
    this is measured by an ordinary run against the whole set, in a process of
    its own, while the paused child sits untouched.

    It is also what decides whether a step cleared, which answers Q72: a live
    step is judged on the same cases it faces when it is scored normally.
    """
    if not tests:
        return 0.0
    return sum(1 for o in result.outcomes if o.passed) / len(tests)


def _def_line(code: str, func_name: str) -> int:
    """Where to put the cursor when nothing raised.

    A wrong answer has no offending line, so the pane opens on the function
    the step is about rather than at the top of a file the player has to
    scroll.
    """
    for number, line in enumerate(code.splitlines(), start=1):
        if line.strip().startswith(f"def {func_name}"):
            return number
    return 1


def _wrong_answer(verdict: RunResult) -> str:
    """The first failing case, in one line, for the pane's header."""
    failed = [o for o in verdict.outcomes if not o.passed]
    if not failed:
        return "the answer was wrong"
    first = failed[0]
    if first.error:
        return first.error
    return f"expected {first.expected}, got {first.got}"


def _repairs(count: int) -> str:
    return f"{count} repair" if count == 1 else f"{count} repairs"


def _fight_bar(fight) -> str:
    """The boss's health and what the player has left to spend.

    The bar is painted `BAD` rather than heat-coloured, because heat reads a
    full bar as good news and a full bar here is a healthy enemy.
    """
    pips = (UI.glyph("token") * fight.repairs_left
            + UI.glyph("pause") * fight.spent)
    return (
        f"  {UI.paint('boss', FAINT)} "
        f"{UI.gauge(fight.remaining, width=20, rgb=BAD)} "
        f"{UI.paint(f'{fight.remaining:>3}', INK, bold=True)}"
        f"   {UI.paint('repairs', FAINT)} {UI.paint(pips, ACCENT)}"
    )


def _apply_edit(live, code: str) -> None:
    """Swap in edited source mid-fight and say whether it really continued.

    Strategy A re-runs from the top and fast-forwards, so "resumed" is a claim
    about the part the player did not watch a second time. When `LiveRun.edit`
    reports that the replay stopped matching, exit criterion 4 says to tell
    them rather than let the fight look continuous.
    """
    divergence = live.edit(code)
    resumed = len(live.steps)
    if divergence is None:
        print(f"    {UI.paint(UI.glyph('arrow'), ACCENT)} "
              + UI.paint(f"edit applied, resumed at step {resumed + 1}", MUTED))
        return
    print(f"    {UI.paint(UI.glyph('cross'), WARN, bold=True)} "
          + UI.paint(f"replay diverged: {divergence}", WARN))
    note = "the re-run is not a continuation of what you watched"
    print(f"      {UI.paint(note, FAINT)}")


def _finish(fight) -> int:
    """How a cleared fight ended, and what it cost.

    ``BOSS DOWN`` is reserved for HP actually reaching zero, which only a
    fight with nothing spent on it can do. Everyone else cleared the boss and
    left it standing, and is told the difference rather than congratulated
    identically — that difference is the whole point of the pool.
    """
    if fight.down:
        print(f"\n  {UI.paint('BOSS DOWN', GOOD, bold=True)}  "
              + UI.paint("flawless -- nothing spent", MUTED) + "\n")
        return 0
    print(f"\n  {UI.paint('BOSS SURVIVES', WARN, bold=True)}  "
          + UI.paint(
              f"on {fight.remaining} hp; every step cleared, "
              f"{_repairs(fight.spent)} spent", MUTED)
          + "\n")
    return 0


def _measure_fight(boss, code: str, seed: int) -> list[StepScore]:
    """Measure every step against the source the fight ended with (T3 W7).

    Not against the attempt that cleared each step: a fight carries one buffer
    forward, so the file the player finishes holding is the submission, and a
    fix typed at step three is part of what step one is judged on. That is the
    same rule an ordinary level follows when it scores the final file rather
    than the drafts.

    A step whose function the buffer never grew -- because the fight stopped
    before reaching it -- measures as zero passed rather than being skipped.
    Skipping it would score an abandoned fight on the part that went well.
    """
    scores: list[StepScore] = []
    for index, step in enumerate(boss.steps):
        tests = step.tests_for(seed)
        # The player's own code, on the player's machine (N9).
        result = run_code(code, step.func_name, tests, source=Source.PLAYER)
        ref_ops, ref_peak = boss_step_benchmark(boss, index, seed)
        goals = style.evaluate(code, step.func_name, step.style_goals)
        scores.append(
            StepScore(
                passed=sum(1 for o in result.outcomes if o.passed),
                total=len(tests),
                ops=result.ops,
                ref_ops=ref_ops,
                peak_bytes=result.peak_bytes,
                ref_peak_bytes=ref_peak,
                style_met=style.all_met(goals),
            )
        )
    return scores


def _print_fight_score(score, weights, steps, *, elapsed: float,
                       par_seconds: float, ranked: bool, measured: bool) -> None:
    """The fight's scorecard, in the same shape a level's uses.

    Deliberately the same layout: a boss is scored on the same three axes and
    a player should not have to learn a second card to read one. Only the
    weights differ, and they are printed, so the difference is visible rather
    than assumed.
    """
    print()
    print(UI.rule("FIGHT SCORE", width=76))
    print()
    UI.reveal_gauge("accuracy", score.accuracy, weights.accuracy,
                    f"({sum(s.passed for s in steps)}/"
                    f"{sum(s.total for s in steps)} cases)")
    if ranked:
        # Only claim the subtraction when it actually happened. A caller that
        # supplied `--elapsed` handed over its own clock, and saying the engine
        # corrected one it never read would be a caption describing the wrong
        # measurement.
        how = ", slow motion excluded" if measured else ""
        UI.reveal_gauge("speed", score.speed, weights.speed,
                        f"({elapsed:.0f}s vs {par_seconds:.0f}s par{how})")
    else:
        print(f"    {'speed':<11} "
              + UI.paint("not measured -- no honest solve time", FAINT))
    UI.reveal_gauge("functional", score.functional, weights.functional,
                    f"({sum(s.ops for s in steps)} ops vs "
                    f"{sum(s.ref_ops for s in steps)} reference)")

    print(f"\n    {UI.paint('subtotal', MUTED)}    {score.subtotal:.1f}")
    for name, rate in score.bonuses.items():
        print(f"    {UI.badge(f'+{rate:.0%}', GOOD)} {UI.paint(name, GOOD)}")
    print(f"\n    {UI.paint('TOTAL', INK, bold=True)}       "
          f"{UI.paint(f'{score.total:.1f}', heat_for(score.total), bold=True)}")
    UI.star_burst(score.stars)
    if not ranked:
        print("    " + UI.paint(
            "practice fight - not banked. Pass --elapsed <seconds> to score "
            "a ranked attempt.", FAINT))
    print()


def _score_the_fight(boss, code: str, seed: int, fight, *,
                     started: float, pacer: "_Pacer", crashed: bool,
                     elapsed_override: "float | None",
                     ranked: bool) -> None:
    """Measure, score and print a finished fight (T3 W7).

    Called whether or not the fight was cleared: an abandoned fight is scored
    on what it actually achieved rather than left unscored, because a zero
    printed for a reason is information and a blank is not.

    The elapsed time handed to the scorer is wall clock **minus the engine's
    own animation**. See `_Pacer` for why: the alternative scores a display
    setting on an axis that is supposed to measure the player.
    """
    weights = BOSS_WEIGHTS if ranked else BOSS_WEIGHTS.without_speed()
    if elapsed_override is not None:
        elapsed = elapsed_override
    else:
        elapsed = max(0.0, time.perf_counter() - started - pacer.slept)
    steps = _measure_fight(boss, code, seed)
    score = score_fight(
        steps,
        elapsed_seconds=elapsed,
        par_seconds=boss.par_seconds,
        repairs_spent=fight.spent,
        crashed_first_run=crashed,
        weights=weights,
    )
    _print_fight_score(score, weights, steps, elapsed=elapsed,
                       par_seconds=boss.par_seconds, ranked=ranked,
                       measured=elapsed_override is None)


def cmd_boss(args: argparse.Namespace) -> int:
    """Run a boss fight step by step (T3 W1).

    Steps are checked in order and stop at the first failure, because a boss
    is a sequence: reporting step three against a buffer whose step one is
    wrong grades a situation the player is not in. Live stepping is W2; this
    is the format being playable, which is what makes W1 a waypoint rather
    than a data structure.
    """
    try:
        boss = level_registry.get_boss(args.boss_id)
    except KeyError as exc:
        raise SystemExit(str(exc))

    seed = args.seed if args.seed is not None else 1
    if getattr(args, "live", False):
        code = boss.reference_source() if args.reference else (
            Path(args.solution).read_text(encoding="utf-8")
            if args.solution else boss.starter_source(0)
        )
        print()
        print(UI.rule(f"BOSS  {boss.title}  (live)", width=76))
        fix = Path(args.fix) if getattr(args, "fix", None) else None
        fight = fight_model.Fight(
            steps=boss.step_count,
            repairs=max(0, getattr(args, "repairs", fight_model.DEFAULT_REPAIRS)),
        )
        # A fight is ranked only when the player brought nothing but
        # themselves. Starting from a file, from the reference, or handing the
        # engine a scripted fix all mean the clock is not measuring anyone
        # solving anything -- the same judgement practice mode makes for a
        # level, and for the same reason (M1).
        elapsed_override = getattr(args, "elapsed", None)
        ranked = elapsed_override is not None or not (
            args.reference or args.solution or fix
        )
        pacer = _Pacer(args.speed)
        started = time.perf_counter()
        crashed_first_run = False
        print()
        print(_fight_bar(fight))
        for index in range(boss.step_count):
            # The edited source carries forward: a fix made at step two is
            # what step three is judged on, because that is what the player
            # would submit.
            cleared, code, opened_badly = _live_step(
                boss, index, code, seed, pacer, fight, fix
            )
            crashed_first_run = crashed_first_run or opened_badly
            if not cleared:
                print(f"\n  {UI.paint('the fight stops here', WARN)}\n")
                _score_the_fight(
                    boss, code, seed, fight, started=started, pacer=pacer,
                    crashed=crashed_first_run,
                    elapsed_override=elapsed_override, ranked=ranked,
                )
                return 1
            dealt = fight.clear(index)
            spent = fight.spent_on(index)
            how = "first try" if not spent else f"after {_repairs(spent)}"
            print(f"    {UI.paint(UI.glyph('tick'), GOOD, bold=True)} "
                  + UI.paint(f"cleared {how}", MUTED)
                  + UI.paint(f"   -{dealt}", GOOD, bold=True))
            print(_fight_bar(fight))
        outcome = _finish(fight)
        _score_the_fight(
            boss, code, seed, fight, started=started, pacer=pacer,
            crashed=crashed_first_run, elapsed_override=elapsed_override,
            ranked=ranked,
        )
        return outcome

    if args.solution:
        code = Path(args.solution).read_text(encoding="utf-8")
    elif args.reference:
        code = boss.reference_source()
    else:
        code = boss.starter_source(0)

    print()
    print(UI.rule(f"BOSS  {boss.title}", width=76))
    print(f"\n  {UI.paint(boss.brief, INK)}\n")

    fight = fight_model.Fight(steps=boss.step_count)
    cleared = 0
    # Nothing here is watched or paced, so there is no honest solve time to
    # measure: this path checks a file rather than playing a fight. It is
    # ranked only when a front-end supplies the clock, exactly as a level's
    # practice mode is.
    elapsed_override = getattr(args, "elapsed", None)
    crashed_first_run = False
    for index, step in enumerate(boss.steps):
        tests = step.tests_for(seed)
        result = run_code(code, step.func_name, tests, source=Source.PLAYER)
        crashed_first_run = crashed_first_run or bool(result.error)
        passed = [o for o in result.outcomes if o.passed]
        ok = len(passed) == len(tests) and not result.error
        mark = UI.glyph("tick") if ok else UI.glyph("cross")
        colour = GOOD if ok else BAD
        print(
            f"  {UI.paint(mark, colour, bold=True)} "
            f"{UI.paint(f'step {index + 1}/{boss.step_count}', FAINT)}  "
            f"{step.title:<24} "
            f"{UI.paint(f'{len(passed)}/{len(tests)}', colour)}  "
            + UI.paint(step.func_name, MUTED)
        )
        if not ok:
            if result.error:
                print(f"      {UI.paint(result.error.splitlines()[-1], BAD)}")
            else:
                _print_first_failure(result, tests)
            print(
                f"\n  {UI.paint('the fight stops here', WARN)}  "
                + UI.paint(f"{cleared}/{boss.step_count} steps cleared", MUTED)
                + "\n"
            )
            _score_the_fight(
                boss, code, seed, fight, started=0.0, pacer=_Pacer(0.0),
                crashed=crashed_first_run, elapsed_override=elapsed_override,
                ranked=elapsed_override is not None,
            )
            return 1
        cleared += 1
        fight.clear(index)

    print()
    print(_fight_bar(fight))
    outcome = _finish(fight)
    _score_the_fight(
        boss, code, seed, fight, started=0.0, pacer=_Pacer(0.0),
        crashed=crashed_first_run, elapsed_override=elapsed_override,
        ranked=elapsed_override is not None,
    )
    return outcome


def cmd_verify(args: argparse.Namespace) -> int:
    """Every reference solution must pass its own tests on several variants.

    This is the guard that keeps a level from shipping with a reference that
    disagrees with its own generated expectations.
    """
    failures = 0
    for level in level_registry.all_levels():
        for seed in range(1, args.seeds + 1):
            try:
                ops, peak = reference_benchmark(level, seed)
            except RuntimeError as exc:
                failures += 1
                print(
                    f"  {UI.paint(UI.glyph('cross'), BAD)} "
                    f"{UI.paint('FAIL', BAD)}  {level.id} seed {seed}: {exc}"
                )
                continue
            if args.verbose:
                print(
                    f"  {UI.paint(UI.glyph('tick'), GOOD)} "
                    f"{UI.paint('OK', GOOD)}    {level.id} seed {seed}: "
                    + UI.paint(f"{ops} ops, {peak / 1024:.1f} KiB", MUTED)
                )
    # Bosses are verified too, per step. A boss reference is checked in the
    # presence of the steps before it, because a step that calls an earlier
    # function cannot be shown correct in isolation.
    boss_runs = 0
    for boss in level_registry.all_bosses():
        for index, step in enumerate(boss.steps):
            source = boss.reference_source(index)
            for seed in range(1, args.seeds + 1):
                boss_runs += 1
                result = run_code(
                    source, step.func_name, step.tests_for(seed),
                    source=boss.source,
                )
                failed = [o.name for o in result.outcomes if not o.passed]
                if failed or result.error:
                    failures += 1
                    print(
                        f"  {UI.paint(UI.glyph('cross'), BAD)} "
                        f"{UI.paint('FAIL', BAD)}  {boss.id}/{step.id} "
                        f"seed {seed}: {result.error or failed}"
                    )
                elif args.verbose:
                    print(
                        f"  {UI.paint(UI.glyph('tick'), GOOD)} "
                        f"{UI.paint('OK', GOOD)}    {boss.id}/{step.id} "
                        f"seed {seed}"
                    )

    total = len(level_registry.all_levels()) * args.seeds + boss_runs
    clean = total - failures
    print(
        f"\n  {UI.gauge(clean, width=30, maximum=max(1, total))}  "
        f"{clean}/{total} reference runs clean\n"
    )
    return 1 if failures else 0


def cmd_edit(args: argparse.Namespace) -> int:
    """Play a level in the full-screen editor (T7).

    Unlike `play`, this front-end knows how long the player actually worked,
    so the Speed axis is honest and a cleared level is banked in full.
    """
    from . import editor as tui

    level = _load_level(args.level_id)
    session = Session.load()
    seed = args.seed if args.seed is not None else session.next_seed(level.id)
    try:
        return tui.play(level, seed=seed, session=session)
    except RuntimeError as exc:
        print(f"\n  {UI.paint(str(exc), BAD)}\n")
        return 1


def cmd_sandbox(args: argparse.Namespace) -> int:
    """Report which execution backends this machine can offer.

    Worth surfacing because the answer changes what the game is allowed to
    run: with no isolating backend, a community level has nowhere safe to
    execute and must be refused rather than run on the host.
    """
    rows = sandbox.describe()
    print()
    print(f"  {UI.rule('execution backends', width=64)}")
    for name, isolating, available in rows:
        mark = UI.glyph("tick") if available else UI.glyph("cross")
        colour = GOOD if available else BAD
        kind = "isolating" if isolating else "host process"
        print(
            f"  {UI.paint(mark, colour)} {name:<12}"
            f"{UI.paint(kind, MUTED if isolating else BAD)}"
        )
        # What a backend actually applies, never what it is assumed to. An
        # unlisted protection is an absent one.
        applied = sandbox.backend(name).hardening if available else ()
        if applied:
            print(f"    {UI.paint(' '.join(sorted(applied)), FAINT)}")

    usable = [name for name, iso, ok in rows if iso and ok]
    print()
    if usable:
        print(
            f"  untrusted code runs under {UI.paint(usable[0], GOOD)}"
            + (f"  (fallback: {', '.join(usable[1:])})" if usable[1:] else "")
        )
    else:
        print(
            f"  {UI.paint('no isolating backend', BAD)} - untrusted code will be "
            "refused.\n  Install bubblewrap, or start the Docker daemon."
        )
    print(UI.paint("\n  pin one with VIBECODER_SANDBOX=<name>\n", MUTED))
    return 0 if usable else 1


def cmd_showcase(args: argparse.Namespace) -> int:
    """Render every visual element at once.

    Exists so the presentation layer can be eyeballed without playing a level,
    and so a terminal's actual capabilities are visible at a glance. Piping this
    to a file is the quickest check that no escape codes leak.
    """
    caps = UI.caps
    print()
    for line in UI.banner():
        print("  " + line)

    print()
    print(UI.rule("DETECTED CAPABILITIES", width=76))
    detected = [
        f"{'colour depth':<16}{caps.depth.name}",
        f"{'unicode':<16}{caps.unicode}",
        f"{'animation':<16}{caps.animate}",
        f"{'width':<16}{caps.width}",
    ]
    for line in UI.box(detected, width=64):
        print(line)

    print()
    print(UI.rule("GAUGES", width=76))
    print()
    for value in (12.0, 38.0, 61.0, 84.0, 100.0):
        print(
            f"    {value:5.0f}  {UI.gradient_gauge(value, width=40)}  "
            f"{UI.stars(3 if value >= 95 else 2 if value >= 80 else 1 if value >= 60 else 0)}"
        )

    print()
    print(UI.rule("SCORE BREAKDOWN", width=76))
    print()
    print(UI.axis_row("accuracy", 100.0, 0.50))
    print(UI.axis_row("speed", 72.0, 0.25, "(250s vs 180s par)"))
    print(UI.axis_row("functional", 33.1, 0.25, "(49590 ops vs 2184 reference)"))

    print()
    print(UI.rule("BOSS HEALTH", width=76))
    print()
    for current in (100, 64, 28, 0):
        print(UI.health_bar(current, 100, width=44))

    print()
    print(UI.rule("SPARKLINES", width=76))
    print()
    print(f"    rising     {UI.sparkline([1, 3, 4, 8, 12, 18, 25, 31, 44, 60])}")
    print(f"    volatile   {UI.sparkline([40, 12, 55, 20, 70, 30, 88, 42, 95, 51])}")
    print(f"    flat       {UI.sparkline([50] * 10)}")

    print()
    print(UI.rule("LEVEL MAP", width=76))
    demo = [
        {"world": 1, "world_title": "Data Wrangler", "id": "a", "title": "a", "stars": 3},
        {"world": 1, "world_title": "Data Wrangler", "id": "b", "title": "b", "stars": 2},
        {"world": 1, "world_title": "Data Wrangler", "id": "c", "title": "c", "stars": 0},
        {"world": 2, "world_title": "Algorithm Architect", "id": "d", "title": "d", "stars": 1},
        {"world": 2, "world_title": "Algorithm Architect", "id": "e", "title": "e", "stars": 0},
    ]
    for line in UI.level_map(demo):
        print(line)

    print()
    print(UI.rule("BADGES", width=76))
    print()
    print(
        "    "
        + "  ".join(
            UI.badge(text, rgb)
            for text, rgb in (
                ("PASS", GOOD), ("FAIL", BAD), ("STYLE GOAL", GOLD),
                ("data", ACCENT), ("async", VIOLET), ("PARTIAL", WARN),
            )
        )
    )
    print()
    return 0


def cmd_reset(args: argparse.Namespace) -> int:
    session = Session.load()
    if not session.path.exists():
        print("nothing to reset")
        return 0
    if not args.force:
        try:
            confirm = input(f"delete {session.path}? [y/N] ")
        except EOFError:
            print("refusing to reset without confirmation (use --force)")
            return 1
        if not confirm.strip().lower().startswith("y"):
            print("cancelled")
            return 0
    session.path.unlink()
    print(f"deleted {session.path}")
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vibecoder",
        description="A Python puzzle game that adapts to how you already write code.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_profile = sub.add_parser("profile", help="build a Vibe Vector from a codebase")
    p_profile.add_argument(
        "path", help="directory, file, or .zip archive to analyse"
    )
    p_profile.add_argument("--json", action="store_true", help="emit raw JSON")
    p_profile.set_defaults(func=cmd_profile)

    p_levels = sub.add_parser("levels", help="list available levels")
    p_levels.add_argument(
        "--campaign", action="store_true", help="campaign order instead of vibe order"
    )
    p_levels.add_argument(
        "--map", action="store_true", help="draw the world map instead of a list"
    )
    p_levels.set_defaults(func=cmd_levels)

    p_play = sub.add_parser("play", help="play a level")
    p_play.add_argument("level_id")
    p_play.add_argument("--seed", type=int, help="replay a specific variant")
    p_play.add_argument(
        "--solution", help="score an existing file instead of opening an editor"
    )
    p_play.add_argument(
        "--elapsed",
        type=float,
        help="real solve time in seconds; makes a --solution run count for score",
    )
    p_play.add_argument(
        "--no-vision", action="store_true",
        help="skip the machine view in the reveal",
    )
    p_play.set_defaults(func=cmd_play)

    p_status = sub.add_parser("status", help="show progression")
    p_status.set_defaults(func=cmd_status)

    p_replay = sub.add_parser("replay", help="slow-motion playback of a run")
    p_replay.add_argument("run_id", nargs="?", help="omit to list recorded runs")
    p_replay.add_argument("--delay", type=float, default=0.35)
    p_replay.add_argument("--step", action="store_true", help="advance on Enter")
    p_replay.set_defaults(func=cmd_replay)

    p_vision = sub.add_parser(
        "vision", help="animate a recorded run as a machine"
    )
    p_vision.add_argument(
        "run_id", nargs="?", help="run to animate (default: the most recent)"
    )
    p_vision.add_argument("--function", help="which function to draw")
    p_vision.add_argument("--delay", type=float, default=0.08,
                          help="seconds between frames")
    p_vision.add_argument("--step", action="store_true",
                          help="advance one frame per keypress")
    p_vision.set_defaults(func=cmd_vision)

    p_boss = sub.add_parser("boss", help="run a boss fight step by step")
    p_boss.add_argument("boss_id")
    p_boss.add_argument("--seed", type=int, help="pick a variant")
    p_boss.add_argument("--solution", help="run a file instead of the starter")
    p_boss.add_argument(
        "--elapsed", type=float,
        help="real solve time in seconds; makes the fight a ranked attempt",
    )
    p_boss.add_argument(
        "--repairs", type=int, default=fight_model.DEFAULT_REPAIRS,
        help="how many repairs the fight allows (0 makes the first failure final)",
    )
    p_boss.add_argument(
        "--fix",
        help="with --live: take the fix from this file instead of asking "
             "you to type it (the scriptable path; a real terminal gets the "
             "editor)",
    )
    p_boss.add_argument(
        "--reference", action="store_true",
        help="run the reference solution, to see the fight completed",
    )
    p_boss.add_argument(
        "--live", action="store_true",
        help="watch each step execute line by line",
    )
    p_boss.add_argument(
        "--speed", type=float, default=LIVE_DELAY,
        help="seconds per line while watching live",
    )
    p_boss.set_defaults(func=cmd_boss)

    p_verify = sub.add_parser("verify", help="check every level's reference solution")
    p_verify.add_argument("--seeds", type=int, default=3)
    p_verify.add_argument("--verbose", "-v", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

    p_showcase = sub.add_parser(
        "showcase", help="render every visual element and detected capabilities"
    )
    p_showcase.set_defaults(func=cmd_showcase)

    p_edit = sub.add_parser(
        "edit", help="play a level in the full-screen editor"
    )
    p_edit.add_argument("level_id")
    p_edit.add_argument("--seed", type=int, default=None)
    p_edit.set_defaults(func=cmd_edit)

    p_sandbox = sub.add_parser(
        "sandbox", help="show which execution backends are available"
    )
    p_sandbox.set_defaults(func=cmd_sandbox)

    p_reset = sub.add_parser("reset", help="delete the local profile")
    p_reset.add_argument("--force", action="store_true")
    p_reset.set_defaults(func=cmd_reset)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
