"""VibeCoder command line.

    vibecoder profile <path>        build a Vibe Vector from a codebase
    vibecoder levels                list levels, ordered by the Vibe Vector
    vibecoder play <level-id>       play a level
    vibecoder status                progression, stars and global score
    vibecoder replay <run-id>       slow-motion playback of a recorded run
    vibecoder verify                run every level's reference against its tests
    vibecoder showcase              render every visual element
    vibecoder reset                 delete the local profile

All output is drawn through the renderer in ``ui.py``, which detects what the
output stream can take. Piping any command produces plain text with no escape
sequences; ``NO_COLOR=1`` does the same on a terminal.
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

def cmd_profile(args: argparse.Namespace) -> int:
    vibe = profile_path(args.path)
    session = Session.load()
    session.vibe = vibe
    session.vibe_source = str(Path(args.path).resolve())
    session.save()

    if args.json:
        print(json.dumps(vibe.to_json(), indent=2))
        return 0

    print()
    print(UI.rule("VIBE VECTOR", width=64))
    stats = [
        f"{'source':<16}{session.vibe_source}",
        f"{'files':<16}{vibe.files}",
        f"{'functions':<16}{vibe.functions}",
        f"{'code lines':<16}{vibe.code_lines}",
        f"{'avg func lines':<16}{vibe.avg_function_lines}",
        f"{'max complexity':<16}{vibe.max_complexity}",
        f"{'docstrings':<16}{vibe.docstring_ratio:.0%} of functions",
    ]
    for line in UI.box(stats, width=64):
        print(line)

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
        print(f"\n  {UI.paint('NAMING', INK, bold=True)}")
        for name, share in list(vibe.naming.items())[:3]:
            print(f"    {name:<18} {UI.gauge(share * 100, width=22, rgb=VIOLET)} {share:5.0%}")

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
        for line in UI.level_map(entries):
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

def _print_results(result: RunResult) -> None:
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
        result = run_submission(level, code, tests, record_trace=True)
        if attempt == 1:
            first_run_clean = not result.fatal
        _print_results(result)

        if result.all_passed or args.solution:
            break
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
    total = len(level_registry.all_levels()) * args.seeds
    clean = total - failures
    print(
        f"\n  {UI.gauge(clean, width=30, maximum=max(1, total))}  "
        f"{clean}/{total} reference runs clean\n"
    )
    return 1 if failures else 0


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
    p_profile.add_argument("path", help="directory or file to analyse")
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

    p_showcase = sub.add_parser(
        "showcase", help="render every visual element and detected capabilities"
    )
    p_showcase.set_defaults(func=cmd_showcase)

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
