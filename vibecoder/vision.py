"""The machine view: a function drawn as apparatus, with its own run inside it.

A score tells a player *that* their solution cost 5,958 operations. It does not
show them why, and "why" is the thing the Functional axis exists to teach. This
module draws the submitted function as a machine -- statements are boxes wired
top to bottom, a loop is a box with a return line down its left side -- and then
walks the recorded execution through it. The token carrying the live value moves
from box to box, the loop counter climbs every time control comes back round,
and an O(n squared) solution is visibly a machine whose inner ring spins while
the outer one barely turns.

Two things make that honest rather than decorative:

**It is driven by the recording, never by the source.** Frames come from the
same line-by-line trace `replay` consumes and T3's live engine will consume.
Nothing here re-executes anything, and nothing here guesses: if the trace says
control was on line 7, the box holding line 7 lights up. A branch that was never
taken never lights up, which is a thing worth being able to see.

**Every frame is built as plain text first and painted last.** `render` returns
a `Screen`, so a test asserts on `as_text()` with no terminal involved, and the
escape-stripped output is identical at every colour depth (the T6 rule). This
module writes no escape sequence of its own; styles arrive through `styler` and
the escapes are `Screen.diff`'s business.

The layout is deliberately not a flowchart. Arbitrary control flow needs edge
routing, which needs a graph layout engine, which is a dependency (N1) and a
large pile of code that would mostly draw diagonal lines. A vertical spine with
loops as left-hand return rails covers what player solutions actually look like
-- sequence, loop, branch, return -- and stays readable in eighty columns.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Sequence

from .screen import Screen

#: Statement label width before it is elided. Wide enough for the loop headers
#: and assignments in real submissions, narrow enough that a deeply nested
#: machine still fits beside its gutters in eighty columns.
LABEL_WIDTH = 34

#: Locals shown in the footer. The trace already caps what it records; this is
#: about the footer staying one line rather than about the data.
FOOTER_LOCALS = 4


# --------------------------------------------------------------------------
# The machine
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Part:
    """One piece of apparatus: a box, and the source lines that light it up.

    ``lines`` holds only the lines that belong to *this* part. A loop's body is
    made of its own parts, so the loop owns its header line alone -- otherwise
    every line in the body would light the loop box as well as the box it is
    really in, and the token would appear to be in two places.
    """

    kind: str           # "block" | "loop" | "branch" | "return"
    label: str
    depth: int
    lines: tuple[int, ...]
    #: Index of the part that encloses this one, or -1 at the top level. Used
    #: to draw the return rail and to attribute an iteration to its loop.
    parent: int = -1


@dataclass(frozen=True)
class Machine:
    name: str
    args: str
    parts: tuple[Part, ...]
    by_line: dict[int, int]

    @property
    def title(self) -> str:
        return f"{self.name}({self.args})"

    def part_for_line(self, line: int) -> int:
        return self.by_line.get(line, -1)


def _label_for(node: ast.AST) -> str:
    """A statement rendered the way a person would read it aloud.

    Compound statements are reduced to their header: the body is drawn as its
    own boxes below, so repeating it inside the header would draw the same code
    twice and make the machine taller than the function.
    """
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return f"for {ast.unparse(node.target)} in {ast.unparse(node.iter)}"
    if isinstance(node, ast.While):
        return f"while {ast.unparse(node.test)}"
    if isinstance(node, ast.If):
        return f"if {ast.unparse(node.test)}"
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return "with " + ", ".join(ast.unparse(i) for i in node.items)
    if isinstance(node, ast.Try):
        return "try"
    if isinstance(node, ast.ExceptHandler):
        kind = ast.unparse(node.type) if node.type else ""
        return f"except {kind}".strip()
    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):  # pragma: no cover - defensive
        return type(node).__name__


def _own_lines(node: ast.AST, compound: bool) -> tuple[int, ...]:
    """Lines that should light this part up.

    A compound statement owns its header line only. A simple statement owns
    every line it spans, because a call broken across four lines is still one
    box and the trace may report any of those lines.
    """
    start = getattr(node, "lineno", 0)
    if compound or not hasattr(node, "end_lineno"):
        return (start,)
    return tuple(range(start, (node.end_lineno or start) + 1))


COMPOUND = (
    ast.For, ast.AsyncFor, ast.While, ast.If,
    ast.With, ast.AsyncWith, ast.Try,
)

LOOPS = (ast.For, ast.AsyncFor, ast.While)


def _collect(body: Sequence[ast.stmt], depth: int, parent: int,
             parts: list[Part]) -> None:
    """Flatten a suite into parts in the order they are drawn."""
    for node in body:
        compound = isinstance(node, COMPOUND)
        if isinstance(node, LOOPS):
            kind = "loop"
        elif isinstance(node, (ast.If, ast.Try)):
            kind = "branch"
        elif isinstance(node, ast.Return):
            kind = "return"
        else:
            kind = "block"

        index = len(parts)
        parts.append(
            Part(kind, _label_for(node), depth, _own_lines(node, compound), parent)
        )
        if compound:
            _collect(node.body, depth + 1, index, parts)
            for handler in getattr(node, "handlers", []):
                parts.append(
                    Part("branch", _label_for(handler), depth,
                         _own_lines(handler, True), parent)
                )
                _collect(handler.body, depth + 1, len(parts) - 1, parts)
            if getattr(node, "orelse", None):
                # An ``elif`` is an ``If`` inside ``orelse``; drawing an "else"
                # box in front of it would invent a step the reader never
                # wrote. Same reasoning as the profiler's nesting metric.
                inner = node.orelse
                if not (len(inner) == 1 and isinstance(inner[0], ast.If)):
                    parts.append(
                        Part("branch", "else", depth, (), parent)
                    )
                    _collect(inner, depth + 1, len(parts) - 1, parts)
                else:
                    _collect(inner, depth, parent, parts)
            for extra in getattr(node, "finalbody", []) or []:
                _collect([extra], depth + 1, index, parts)


def _target_function(tree: ast.Module, name: str | None) -> ast.FunctionDef | None:
    """The function to draw.

    Defaults to ``solve`` because that is what a level's starter defines, then
    falls back to the last function in the file -- which for a submission built
    up from helpers is the one that ties them together.
    """
    functions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not functions:
        return None
    if name:
        for node in functions:
            if node.name == name:
                return node
        return None
    for node in functions:
        if node.name == "solve":
            return node
    return functions[-1]


def build_machine(source: str, function: str | None = None) -> Machine:
    """Draw the apparatus for one function in ``source``.

    Raises `ValueError` when the source does not parse or holds no such
    function, because there is nothing honest to draw in either case.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise ValueError(f"cannot draw code that does not parse: {exc}")

    node = _target_function(tree, function)
    if node is None:
        wanted = f"no function named {function!r}" if function else "no function"
        raise ValueError(f"{wanted} to draw")

    parts: list[Part] = []
    _collect(node.body, 0, -1, parts)

    by_line: dict[int, int] = {}
    for index, part in enumerate(parts):
        for line in part.lines:
            by_line[line] = index

    args = ", ".join(a.arg for a in node.args.args)
    return Machine(node.name, args, tuple(parts), by_line)


# --------------------------------------------------------------------------
# Frames, from the recording
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    """One instant: which box is live, what it is holding, how far in."""

    step: int
    total: int
    part: int
    line: int
    where: str
    locals: dict[str, str] = field(default_factory=dict)
    iterations: dict[int, int] = field(default_factory=dict)
    changed: str = ""


def frames(machine: Machine, trace: Sequence[dict[str, Any]]) -> list[Frame]:
    """Turn a recorded trace into the frames that drive the animation.

    Steps inside a function we are not drawing keep the previous box lit and
    say where control actually is. Dropping them instead would make a helper
    call look instantaneous, and a solution that pushes its work into a helper
    is exactly the one whose cost a player most needs to see.
    """
    built: list[Frame] = []
    iterations: dict[int, int] = {}
    previous_part = -1
    previous_locals: dict[str, str] = {}
    total = len(trace)

    for step, record in enumerate(trace, start=1):
        line = int(record.get("line", 0))
        func = str(record.get("func", ""))
        values = {str(k): str(v) for k, v in (record.get("locals") or {}).items()}

        if func and func != machine.name:
            part = previous_part
            where = f"in {func}()"
        else:
            part = machine.part_for_line(line)
            if part < 0:
                part = previous_part
            where = ""

        if part >= 0 and machine.parts[part].kind == "loop" and part != previous_part:
            iterations[part] = iterations.get(part, 0) + 1

        changed = ""
        for key, value in values.items():
            if previous_locals.get(key) != value:
                changed = key
        built.append(
            Frame(
                step=step,
                total=total,
                part=part,
                line=line,
                where=where,
                locals=values,
                iterations=dict(iterations),
                changed=changed,
            )
        )
        previous_part = part
        previous_locals = values

    return built


# --------------------------------------------------------------------------
# Layout
# --------------------------------------------------------------------------

#: Columns consumed by one level of nesting: a return rail and a gap.
INDENT = 3

#: Row roles, in drawing order for one part.
TOP, BODY, BOTTOM = "top", "body", "bottom"


@dataclass(frozen=True)
class Row:
    part: int
    role: str
    depth: int


def layout(machine: Machine) -> list[Row]:
    """Rows for the whole machine, before anything is painted.

    Separated from `render` so the geometry can be reasoned about -- and
    tested -- without a Screen, and so the viewport can find the active row
    without drawing every row first.
    """
    rows: list[Row] = []
    for index, part in enumerate(machine.parts):
        rows.append(Row(index, TOP, part.depth))
        rows.append(Row(index, BODY, part.depth))
        rows.append(Row(index, BOTTOM, part.depth))
    return rows


def _rail_span(machine: Machine, rows: list[Row], part: int) -> tuple[int, int]:
    """First and last row a loop's return rail spans.

    From the loop's own box down to the last row of the last part nested
    inside it, which is what the rail has to reach back from.
    """
    start = next(i for i, row in enumerate(rows) if row.part == part)
    end = start
    depth = machine.parts[part].depth
    for index, row in enumerate(rows):
        if index <= start:
            continue
        if row.part == part:
            # The loop's own three rows sit between its header and its body.
            # Treating them as "not nested" ends the rail before it starts.
            end = index
            continue
        if machine.parts[row.part].depth > depth:
            end = index
        else:
            break
    return start, end


def _elide(text: str, width: int) -> str:
    """Shorten a label from the right, keeping the start that names it.

    ASCII marker so the width cannot depend on the terminal's Unicode support.
    """
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

Styler = Callable[..., str]


def _plain_styler(*args: Any, **kwargs: Any) -> str:
    return ""


def render(
    machine: Machine,
    frame: Frame,
    *,
    rows: int = 24,
    columns: int = 80,
    styler: Styler | None = None,
    glyph: Callable[[str], str] | None = None,
    palette: dict[str, Any] | None = None,
) -> Screen:
    """Build one complete frame. Pure: no terminal, no side effects.

    ``styler`` and ``glyph`` are injected rather than imported so this can be
    rendered headlessly at any capability level, which is how the tests assert
    layout parity between Unicode and ASCII.
    """
    styler = styler or _plain_styler
    glyph = glyph or (lambda name: _ASCII[name])
    palette = palette or {}
    screen = Screen(rows, columns)

    plan = layout(machine)
    active_row = next(
        (i for i, row in enumerate(plan) if row.part == frame.part and row.role == BODY),
        0,
    )

    # -- viewport: keep the live box in view without letting it sit on an edge
    body_rows = rows - 4  # title, two footer lines, and the closing rule
    top = 0
    if len(plan) > body_rows:
        top = max(0, min(active_row - body_rows // 2, len(plan) - body_rows))

    dim = styler(palette.get("faint"))
    live = styler(palette.get("live"), bold=True)
    label_style = styler(palette.get("ink"))

    # -- title
    title = f" {machine.title} "
    screen.put(0, 0, glyph("tl") + glyph("h"), dim)
    end = screen.put(0, 2, title, styler(palette.get("accent"), bold=True))
    screen.hline(0, end, max(0, columns - end - 1), glyph("h"), dim)
    screen.put(0, columns - 1, glyph("tr"), dim)

    # -- return rails, drawn under the boxes so a box always wins the cell
    for index, part in enumerate(machine.parts):
        if part.kind != "loop":
            continue
        start, stop = _rail_span(machine, plan, index)
        column = part.depth * INDENT
        for row_index in range(start, stop + 1):
            screen_row = row_index - top + 1
            if not (1 <= screen_row < rows - 3):
                continue
            spinning = frame.part == index or (
                frame.part >= 0
                and machine.parts[frame.part].depth > part.depth
                and start <= active_row <= stop
            )
            rail = live if spinning else dim
            if row_index == start:
                screen.put(screen_row, column, glyph("rail_top"), rail)
            elif row_index == stop:
                screen.put(screen_row, column, glyph("rail_bottom"), rail)
                screen.put(screen_row, column + 1, glyph("h"), rail)
            else:
                screen.put(screen_row, column, glyph("v"), rail)

    # -- boxes
    for row_index in range(top, min(len(plan), top + body_rows)):
        row = plan[row_index]
        screen_row = row_index - top + 1
        if screen_row >= rows - 3:
            break
        part = machine.parts[row.part]
        column = 2 + part.depth * INDENT
        is_live = row.part == frame.part
        base = min(LABEL_WIDTH + 4, columns - 16)
        width = base - part.depth * INDENT
        if width < 8:
            continue
        edge = live if is_live else dim

        if row.role == TOP:
            screen.put(screen_row, column, glyph("box_tl"), edge)
            screen.hline(screen_row, column + 1, width - 2, glyph("h"), edge)
            screen.put(screen_row, column + width - 1, glyph("box_tr"), edge)
        elif row.role == BOTTOM:
            screen.put(screen_row, column, glyph("box_bl"), edge)
            screen.hline(screen_row, column + 1, width - 2, glyph("h"), edge)
            screen.put(screen_row, column + width - 1, glyph("box_br"), edge)
        else:
            screen.put(screen_row, column, glyph("v"), edge)
            label = _elide(part.label, width - 4)
            screen.put(screen_row, column + 2, label,
                       live if is_live else label_style)
            screen.put(screen_row, column + width - 1, glyph("v"), edge)

            after = column + width + 1
            if is_live:
                # The token rides in the margin the rails leave free, so it is
                # visible whatever the box is -- a spinning loop needs it most.
                screen.put(screen_row, max(0, column - 2), glyph("token"),
                           styler(palette.get("token"), bold=True))
            spin = frame.iterations.get(row.part)
            if part.kind == "loop" and spin:
                after = screen.put(
                    screen_row, after, f"{glyph('loop')} {spin}",
                    styler(palette.get("accent")),
                ) + 2
            if is_live:
                if frame.where:
                    screen.put(screen_row, after, frame.where, dim)
                elif frame.changed:
                    value = _elide(
                        f"{frame.changed} = {frame.locals.get(frame.changed, '')}",
                        max(0, columns - after - 1),
                    )
                    screen.put(screen_row, after, value,
                               styler(palette.get("token")))

    # -- footer
    rule_row = rows - 3
    screen.put(rule_row, 0, glyph("bl"), dim)
    screen.hline(rule_row, 1, columns - 2, glyph("h"), dim)
    screen.put(rule_row, columns - 1, glyph("br"), dim)

    progress = f"step {frame.step}/{frame.total}"
    screen.put(rows - 2, 2, progress, styler(palette.get("ink")))
    shown = [
        f"{name} = {value}"
        for name, value in list(frame.locals.items())[:FOOTER_LOCALS]
    ]
    if shown:
        text = "   ".join(shown)
        screen.put(rows - 2, 2 + len(progress) + 3,
                   _elide(text, max(0, columns - len(progress) - 7)),
                   styler(palette.get("faint")))
    return screen


#: ASCII fallbacks, used when no glyph resolver is supplied. Every pair is one
#: character wide in both modes, so the layout is identical at any capability.
_ASCII = {
    "tl": "+", "tr": "+", "bl": "+", "br": "+",
    "box_tl": "+", "box_tr": "+", "box_bl": "+", "box_br": "+",
    "h": "-", "v": "|",
    "rail_top": "+", "rail_bottom": "+",
    "loop": "o", "token": "@", "down": "v",
}


# --------------------------------------------------------------------------
# Driving it
# --------------------------------------------------------------------------

#: Which palette role paints what. Named here rather than inline so the whole
#: look of the machine is one block to read and one block to change.
PALETTE_ROLES = ("faint", "ink", "accent", "live", "token")


def palette_from(ui: Any) -> dict[str, Any]:
    from .ui import ACCENT, FAINT, GOLD, INK

    return {
        "faint": FAINT, "ink": INK, "accent": ACCENT,
        "live": ACCENT, "token": GOLD,
    }


def sample(built: Sequence[Frame], limit: int) -> list[Frame]:
    """At most ``limit`` frames, evenly spaced, always keeping the last.

    A trace runs to 400 steps, which at a watchable frame rate is half a
    minute -- fine when a player asked for the animation, far too long in the
    score reveal, which is the hottest path in the product.

    Sampling is honest here in a way that shortening the delay is not. Every
    `Frame` already carries its own state, computed over the *whole* trace, so
    a sampled frame's loop counter is the true count at that instant rather
    than a count of the frames that survived. The step number jumping from 40
    to 52 is visible, which is the reader's cue that instants were skipped.
    """
    if limit <= 0 or len(built) <= limit:
        return list(built)
    stride = len(built) / limit
    kept = [built[min(len(built) - 1, int(i * stride))] for i in range(limit)]
    if kept[-1] is not built[-1]:
        kept[-1] = built[-1]
    return kept


def still(
    source: str,
    trace: Sequence[dict[str, Any]],
    *,
    function: str | None = None,
    step: int | None = None,
    rows: int = 24,
    columns: int = 80,
    glyph: Callable[[str], str] | None = None,
) -> str:
    """One frame as plain text, with no terminal and no escapes.

    What `vibecoder vision` prints when its output is not a terminal. A pipe
    gets the machine and the step it was asked for rather than either nothing
    or a screenful of cursor movement.
    """
    machine = build_machine(source, function)
    built = frames(machine, trace)
    if not built:
        return render(machine, Frame(0, 0, -1, 0, ""),
                      rows=rows, columns=columns, glyph=glyph).as_text()
    index = len(built) - 1 if step is None else max(0, min(step - 1, len(built) - 1))
    return render(machine, built[index], rows=rows, columns=columns,
                  glyph=glyph).as_text()


def play(
    source: str,
    trace: Sequence[dict[str, Any]],
    *,
    function: str | None = None,
    delay: float = 0.08,
    stream: Any = None,
    interactive: bool = False,
    budget: float | None = None,
    limit: int = 0,
) -> int:
    """Animate a recorded run through its machine. Returns frames drawn.

    Falls back to a single still frame whenever the stream cannot animate --
    a pipe, a CI log, ``VIBECODER_NO_ANIM`` -- because a recording of cursor
    movement is not a useful artifact and escape codes in a log file are a bug.
    """
    import sys as _sys
    import time as _time

    from . import term
    from .ui import renderer_for

    stream = stream or _sys.stdout
    ui = renderer_for(stream)
    machine = build_machine(source, function)
    built = frames(machine, trace)
    if not built:
        return 0

    if not ui.caps.animate or not term.supported(stream):
        # Unicode is a capability of the stream; colour is a capability of the
        # terminal. A UTF-8 pipe gets box-drawing characters and no escapes,
        # which is how the rest of the product behaves.
        stream.write(
            still(source, trace, function=function,
                  columns=min(ui.caps.width, 100), glyph=ui.glyph)
            + "\n"
        )
        return 1

    if limit:
        built = sample(built, limit)
    if budget is not None and built:
        # The budget is a ceiling, never a floor: a six-frame run stays at its
        # natural pace rather than being stretched to fill the time.
        delay = min(delay, budget / len(built))

    palette = palette_from(ui)
    drawn = 0
    with term.TerminalSession(stream) as session:
        rows, columns = session.size()
        previous: Screen | None = None
        for frame in built:
            if session.resized():
                rows, columns = session.size()
                previous = None
            screen = render(
                machine, frame, rows=rows, columns=columns,
                styler=ui.style, glyph=ui.glyph, palette=palette,
            )
            patch, _, _ = screen.diff(previous)
            session.write(patch)
            previous = screen
            drawn += 1
            if interactive:
                if session.read(timeout=None) in (b"q", b"\x03"):
                    break
            else:
                _time.sleep(delay)
                if session.read(timeout=0) in (b"q", b"\x03"):
                    break
    return drawn
