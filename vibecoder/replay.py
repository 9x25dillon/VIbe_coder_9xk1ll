"""Slow-motion execution replay.

This is the playback half of the Boss Fight pillar. The sandbox records a
line-by-line trace with a snapshot of locals at each step; this module plays
that trace back against the source, one line at a time, with the current line
highlighted and the watched variables shown as they were at that instant.

What this is NOT, yet: it cannot pause, step backwards, edit and resume. Those
require driving ``sys.settrace`` interactively in a live process rather than
replaying a recording, and they are scheduled for Phase 2 (see
docs/trajectories/T3-boss-engine.md). Replay-only was built first because it
validates the trace format that the interactive engine will also consume.
"""

from __future__ import annotations

import shutil
import sys
import time
from typing import Any, Iterator, Sequence

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
ARROW = "\033[33m"
VAR = "\033[36m"


def _supports_colour(stream) -> bool:
    return hasattr(stream, "isatty") and stream.isatty()


def render_step(
    source_lines: Sequence[str],
    step: dict[str, Any],
    *,
    context: int = 3,
    colour: bool = True,
    width: int | None = None,
) -> str:
    """Render one frame of the replay: source window plus variable watch."""
    width = width or shutil.get_terminal_size((80, 24)).columns
    current = step["line"]
    start = max(1, current - context)
    end = min(len(source_lines), current + context)

    out: list[str] = []
    for number in range(start, end + 1):
        text = source_lines[number - 1].rstrip()
        marker = ">>" if number == current else "  "
        line = f" {marker} {number:>3} | {text}"
        if colour:
            line = (
                f"{ARROW}{line}{RESET}" if number == current else f"{DIM}{line}{RESET}"
            )
        out.append(line[: width - 1])

    watched = step.get("locals", {})
    if watched:
        out.append("")
        label = f"{BOLD}watch{RESET}" if colour else "watch"
        out.append(f" {label}  in {step.get('func', '?')}()")
        for name, value in watched.items():
            key = f"{VAR}{name}{RESET}" if colour else name
            out.append(f"   {key} = {value}"[: width - 1])
    return "\n".join(out)


def iter_frames(trace: Sequence[dict[str, Any]]) -> Iterator[tuple[int, dict]]:
    for index, step in enumerate(trace, start=1):
        yield index, step


def play(
    source: str,
    trace: Sequence[dict[str, Any]],
    *,
    delay: float = 0.35,
    context: int = 3,
    stream=None,
    interactive: bool = False,
) -> None:
    """Play a recorded trace back to ``stream``.

    With ``interactive=True`` the replay advances on Enter instead of a timer,
    which is how the boss fight will be driven once stepping is live. An EOF on
    stdin falls back to timed playback so the mode is safe in a pipeline.
    """
    stream = stream or sys.stdout
    colour = _supports_colour(stream)
    source_lines = source.splitlines()
    total = len(trace)

    if not trace:
        stream.write("no trace was recorded for this run\n")
        return

    for index, step in iter_frames(trace):
        header = f"  step {index}/{total}"
        stream.write("\n" + (f"{DIM}{header}{RESET}" if colour else header) + "\n")
        stream.write(render_step(source_lines, step, context=context, colour=colour))
        stream.write("\n")
        stream.flush()

        if interactive:
            try:
                input("  [enter] next  ")
                continue
            except EOFError:
                interactive = False
        time.sleep(delay)

    footer = f"\n  replay complete - {total} steps"
    stream.write((f"{DIM}{footer}{RESET}" if colour else footer) + "\n")
