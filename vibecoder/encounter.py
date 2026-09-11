"""Live boss apparatus with persistent resources and a values inspector.

The driver closes this screen before offering a repair, so terminal ownership
never nests. Piped and reduced-motion runs keep the existing transcript.
"""

from __future__ import annotations

from . import cockpit, vision
from .screen import Screen
from .term import MIN_HEIGHT, MIN_WIDTH, TerminalSession, supported
from .ui import ACCENT, BAD, FAINT, WARN, Renderer, detect


def compose(machine, frame, fight, title, ui, rows, columns) -> Screen:
    """Render only interpreter-recorded state; health comes from the fight."""
    screen = Screen(rows, columns)
    if rows < MIN_HEIGHT or columns < MIN_WIDTH:
        cockpit.put(screen, 0, 0, "Terminal too small / resize or press q to stop", columns)
        return screen
    cockpit.header(screen, ui, "BOSS / " + title,
                   f"step {fight.cleared + 1}/{fight.steps}")
    resources = f"HP {fight.remaining}/{fight.hp}  /  repairs {fight.repairs_left}"
    cockpit.put(screen, 1, 1, resources, columns - 2, ui.style(WARN, bold=True))
    if columns >= 76:
        filled = round(18 * fight.remaining / fight.hp)
        col = len(resources) + 3
        screen.put(1, col, ui.glyph("bar_full") * filled, ui.style(BAD))
        screen.put(1, col + filled, ui.glyph("bar_empty") * (18 - filled), ui.style(FAINT))
    cockpit.divider(screen, ui, 2)
    machine_width = columns - 38 if columns >= cockpit.WIDE else columns
    apparatus = vision.render(machine, frame, rows=rows - 5, columns=machine_width,
                              styler=ui.style, glyph=ui.glyph,
                              palette=vision.palette_from(ui))
    # A live trace has no known final length. Never present N/N as completion.
    apparatus.fill(apparatus.rows - 2, 0, machine_width)
    values = "   ".join(f"{key} = {value}" for key, value in frame.locals.items())
    cockpit.put(apparatus, apparatus.rows - 2, 2,
                f"event {frame.step} / live   {values}", machine_width - 4,
                ui.style(WARN))
    for index, row in enumerate(apparatus.grid):
        screen.grid[index + 3][:machine_width] = row
    if machine_width < columns:
        text = "\n".join(f"{key} = {value}" for key, value in frame.locals.items())
        lines = cockpit.section("LIVE VALUES", text or "Waiting for values.", 34)
        cockpit.document(screen, ui, lines, top=4, left=machine_width + 2,
                         height=rows - 7, width=34, more="inspect on failure")
    cockpit.divider(screen, ui, rows - 2)
    cockpit.put(screen, rows - 1, 1, "LIVE / follow the execution token    q stop", columns - 2,
                ui.style(ACCENT))
    return screen


class Encounter:
    """Lazy terminal ownership, safely released before repair or exceptions."""

    def __init__(self, title, function, fight):
        self.title, self.function, self.fight = title, function, fight
        self.ui = Renderer(detect())
        self.enabled = self.ui.caps.animate and supported()
        self.terminal = None
        self.previous = None
        self.source = None
        self.machine = None
        self.cancelled = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        """Return to the transcript before printing a failure or opening repair."""
        if self.terminal is not None:
            self.terminal.restore()
            self.terminal = None
        self.previous = None

    def show(self, source, steps):
        """Follow the actual live trace, rebuilding apparatus after an edit."""
        if not self.enabled:
            return
        if source != self.source:
            try:
                self.machine = vision.build_machine(source, self.function)
            except ValueError:
                self.enabled = False
                self.close()
                return
            self.source = source
        built = vision.frames(self.machine, [step.to_trace() for step in steps])
        if not built:
            return
        if self.terminal is None:
            self.terminal = TerminalSession()
            self.terminal.start()
        if self.terminal.resized:
            self.previous = None
        frame = compose(self.machine, built[-1], self.fight, self.title,
                        self.ui, *self.terminal.size())
        patch, _, _ = frame.diff(self.previous)
        self.terminal.write(patch)
        self.previous = frame
        self.cancelled = self.terminal.read(0) in (b"q", b"\x03", b"\x18")
