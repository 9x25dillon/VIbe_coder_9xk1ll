"""VibeCoder command line.

    vibecoder profile <path>        build a Vibe Vector from a codebase
    vibecoder levels                list levels, ordered by the Vibe Vector
    vibecoder play <level-id>       play a level
    vibecoder status                progression, stars and global score
    vibecoder replay <run-id>       slow-motion playback of a recorded run
    vibecoder verify                run every level's reference against its tests
    vibecoder reset                 delete the local profile
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import levels as level_registry
from . import style, tips
from .models import Level, RunResult
from .profiler import profile_path, recommend
from .runner import reference_benchmark, run_submission
from .scoring import LEVEL_WEIGHTS, score_submission, streak_multiplier
from .session import Session
from .replay import play as play_replay

BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


def _colour(text: str, code: str) -> str:
    return text if os.environ.get("NO_COLOR") else f"{code}{text}{RESET}"


def _stars(count: int) -> str:
    return "*" * count + "." * (3 - count)


def _bar(value: float, width: int = 24) -> str:
    filled = int(round(width * max(0.0, min(100.0, value)) / 100.0))
    return "#" * filled + "-" * (width - filled)


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------

def cmd_profile(args: argparse.Namespace) -> int:
    vibe = profile_path(args.path)
    session = Session.load()
    session.vibe = vibe
    session.vibe_source = str(Path(args.path).resolve())
    session.save()

    if args.json:
        print(json.dumps(vibe.to_json(), indent=2))
        return 0

    print(_colour("\n  VIBE VECTOR", BOLD))
    print(f"  source          {session.vibe_source}")
    print(f"  files           {vibe.files}")
    print(f"  functions       {vibe.functions}")
    print(f"  code lines      {vibe.code_lines}")
    print(f"  avg func lines  {vibe.avg_function_lines}")
    print(f"  max complexity  {vibe.max_complexity}")
    print(f"  docstrings      {vibe.docstring_ratio:.0%} of functions")

    if vibe.libraries:
        print(_colour("\n  LIBRARIES", BOLD))
        for name, count in list(vibe.libraries.items())[:8]:
            print(f"    {name:<16} {count}")

    if vibe.patterns:
        print(_colour("\n  PATTERNS", BOLD))
        for name, share in sorted(
            vibe.patterns.items(), key=lambda kv: -kv[1]
        )[:8]:
            print(f"    {name:<18} {_bar(share * 100, 18)} {share:.0%}")

    if vibe.naming:
        top = ", ".join(f"{k} {v:.0%}" for k, v in list(vibe.naming.items())[:3])
        print(_colour("\n  NAMING", BOLD) + f"\n    {top}")

    if vibe.exceptions_caught:
        caught = ", ".join(f"{k} ({v})" for k, v in vibe.exceptions_caught.items())
        print(_colour("\n  EXCEPTIONS HANDLED", BOLD) + f"\n    {caught}")

    print(_colour("\n  TAGS", BOLD) + f"\n    {', '.join(vibe.tags) or '(none)'}")
    print(f"\n  saved to {session.path}\n")
    return 0


# --------------------------------------------------------------------------
# levels
# --------------------------------------------------------------------------

def cmd_levels(args: argparse.Namespace) -> int:
    session = Session.load()
    all_levels = list(level_registry.all_levels())

    if session.vibe and not args.campaign:
        ordered = recommend(all_levels, session.vibe)
        heading = "RECOMMENDED FOR YOUR VIBE"
    else:
        ordered = all_levels
        heading = "CAMPAIGN ORDER"

    print(_colour(f"\n  {heading}", BOLD))
    current_world = None
    for level in ordered:
        if args.campaign and level.world != current_world:
            current_world = level.world
            print(_colour(f"\n  World {level.world} - {level.world_title}", DIM))
        record = session.levels.get(level.id)
        stars = _stars(record.best_stars if record else 0)
        best = f"{record.best_total:6.1f}" if record else "     -"
        tags = ",".join(level.tags)
        print(f"    [{stars}] {best}  {level.id:<16} {level.title:<28} {DIM}{tags}{RESET}")

    if not session.vibe:
        print(
            f"\n  {DIM}No Vibe Vector yet. Run "
            f"`vibecoder profile <path>` to personalise this ordering.{RESET}"
        )
    print()
    return 0


# --------------------------------------------------------------------------
# play
# --------------------------------------------------------------------------

def _print_results(result: RunResult) -> None:
    if result.fatal:
        print(f"\n  {_colour(result.error_type or 'Error', RED)}: {result.error}")
        return
    print()
    for outcome in result.outcomes:
        if outcome.passed:
            print(f"  {_colour('PASS', GREEN)}  {outcome.name}")
        else:
            detail = outcome.error or f"got {outcome.got}, expected {outcome.expected}"
            print(f"  {_colour('FAIL', RED)}  {outcome.name}  {DIM}{detail}{RESET}")
    print(
        f"\n  {result.passed_count}/{result.total_count} passed"
        f"   {result.ops} ops   {result.peak_bytes / 1024:.1f} KiB peak"
    )
    if result.stdout.strip():
        print(f"\n  {DIM}stdout:{RESET}\n{result.stdout.rstrip()}")


def _edit(path: Path) -> None:
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    subprocess.call([*editor.split(), str(path)])


def _load_level(level_id: str) -> Level:
    try:
        return level_registry.get_level(level_id)
    except KeyError:
        known = ", ".join(lvl.id for lvl in level_registry.all_levels())
        raise SystemExit(f"unknown level {level_id!r}. Available: {known}")


def cmd_play(args: argparse.Namespace) -> int:
    level = _load_level(args.level_id)
    session = Session.load()
    seed = args.seed if args.seed is not None else session.next_seed(level.id)
    tests = level.tests_for(seed)

    print(_colour(f"\n  {level.title}", BOLD) + f"  {DIM}({level.id}, variant {seed}){RESET}")
    print(f"  World {level.world} - {level.world_title}")
    print(f"\n  {level.brief}\n")
    if level.style_goals:
        goals = "; ".join(style.DESCRIPTIONS[g] for g in level.style_goals)
        print(f"  {_colour('Style goal (+5%)', YELLOW)}: {goals}\n")
    print(f"  {DIM}par time: {level.par_seconds / 60:.0f} min{RESET}\n")

    workspace = Path(args.solution) if args.solution else None
    if workspace is None:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=f"_{level.func_name}.py", delete=False, encoding="utf-8"
        )
        handle.write(level.starter)
        handle.close()
        workspace = Path(handle.name)
        print(f"  editing {workspace}\n")

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
        result = run_submission(level, code, tests, record_trace=True)
        if attempt == 1:
            first_run_clean = not result.fatal
        _print_results(result)

        if result.all_passed or args.solution:
            break
        try:
            again = input(f"\n  {DIM}[enter] keep editing, 'q' to give up: {RESET}")
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

    print(_colour("\n  SCORE", BOLD))
    print(
        f"    accuracy    {_bar(score.accuracy)} {score.accuracy:6.1f}"
        f"  x{weights.accuracy:.2f}"
    )
    if practice:
        print(f"    speed       {DIM}{'not measured in practice mode':<24}{RESET}")
    else:
        print(
            f"    speed       {_bar(score.speed)} {score.speed:6.1f}"
            f"  x{weights.speed:.2f}  ({elapsed:.0f}s vs {level.par_seconds:.0f}s par)"
        )
    print(
        f"    functional  {_bar(score.functional)} {score.functional:6.1f}"
        f"  x{weights.functional:.2f}  ({result.ops} ops vs {ref_ops} reference)"
    )
    print(f"    {DIM}subtotal{RESET}    {score.subtotal:.1f}")
    for name, rate in score.bonuses.items():
        print(f"    {_colour('bonus', GREEN)}       +{rate:.0%}  {name}")
    print(f"\n    {_colour('TOTAL', BOLD)}       {score.total:.1f}   [{_stars(score.stars)}]")
    if practice:
        print(
            f"    {DIM}practice run - not banked. Pass --elapsed <seconds> "
            f"to score a ranked attempt.{RESET}"
        )

    if outcome["improved"]:
        print(f"    {_colour('new personal best', GREEN)}")
    if outcome["streak"] > 1:
        print(
            f"    streak {outcome['streak']} "
            f"(x{streak_multiplier(outcome['streak']):.1f} on the next perfect clear)"
        )

    advice = tips.generate(
        code,
        level.func_name,
        result,
        ref_ops=ref_ops,
        vibe=session.vibe,
        style_results=style_results,
    )
    if advice:
        print(_colour("\n  VIBE TIPS", BOLD))
        for tip in advice:
            print(f"    - {tip}")

    print(f"\n  {DIM}run saved as {run_id} - replay it with `vibecoder replay {run_id}`{RESET}\n")
    return 0


# --------------------------------------------------------------------------
# status / replay / verify / reset
# --------------------------------------------------------------------------

def cmd_status(args: argparse.Namespace) -> int:
    session = Session.load()
    all_levels = list(level_registry.all_levels())
    cleared = sum(1 for r in session.levels.values() if r.best_stars > 0)
    stars = sum(r.best_stars for r in session.levels.values())

    print(_colour("\n  PROGRESSION", BOLD))
    print(f"    global score   {session.total_score:.1f}")
    print(f"    levels cleared {cleared}/{len(all_levels)}")
    print(f"    stars          {stars}/{len(all_levels) * 3}")
    print(f"    streak         {session.streak}")
    print(f"    tokens         " + ", ".join(f"{k} x{v}" for k, v in session.tokens.items()))
    print(f"    vibe source    {session.vibe_source or '(not profiled)'}")

    if session.levels:
        print(_colour("\n  LEVELS", BOLD))
        for level in all_levels:
            record = session.levels.get(level.id)
            if not record:
                continue
            print(
                f"    [{_stars(record.best_stars)}] {record.best_total:6.1f}  "
                f"{level.id:<16} {DIM}{record.attempts} attempts, "
                f"{len(record.seeds_played)} variants{RESET}"
            )
    print(f"\n  {DIM}profile: {session.path}{RESET}\n")
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
    print(
        f"\n  replaying {args.run_id} "
        f"{DIM}(variant {payload.get('seed')}, {len(trace)} steps){RESET}"
    )
    play_replay(
        payload["code"],
        trace,
        delay=args.delay,
        interactive=args.step,
    )
    return 0


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
                print(f"  {_colour('FAIL', RED)}  {level.id} seed {seed}: {exc}")
                continue
            if args.verbose:
                print(
                    f"  {_colour('OK', GREEN)}    {level.id} seed {seed}: "
                    f"{ops} ops, {peak / 1024:.1f} KiB"
                )
    total = len(level_registry.all_levels()) * args.seeds
    print(f"\n  {total - failures}/{total} reference runs clean\n")
    return 1 if failures else 0


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
    p_profile.add_argument("path", help="directory or file to analyse")
    p_profile.add_argument("--json", action="store_true", help="emit raw JSON")
    p_profile.set_defaults(func=cmd_profile)

    p_levels = sub.add_parser("levels", help="list available levels")
    p_levels.add_argument(
        "--campaign", action="store_true", help="campaign order instead of vibe order"
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
    p_play.set_defaults(func=cmd_play)

    p_status = sub.add_parser("status", help="show progression")
    p_status.set_defaults(func=cmd_status)

    p_replay = sub.add_parser("replay", help="slow-motion playback of a run")
    p_replay.add_argument("run_id", nargs="?", help="omit to list recorded runs")
    p_replay.add_argument("--delay", type=float, default=0.35)
    p_replay.add_argument("--step", action="store_true", help="advance on Enter")
    p_replay.set_defaults(func=cmd_replay)

    p_verify = sub.add_parser("verify", help="check every level's reference solution")
    p_verify.add_argument("--seeds", type=int, default=3)
    p_verify.add_argument("--verbose", "-v", action="store_true")
    p_verify.set_defaults(func=cmd_verify)

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
