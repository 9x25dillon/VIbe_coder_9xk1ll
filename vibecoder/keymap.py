"""What each key does. T7 W7.

Kept out of `editor.py` on purpose: a keymap is a table, and a table that
lives in its own module can be read, tested and rebound without touching the
application. Every action takes the editor and returns nothing.

The bindings avoid the terminal's own reserved characters. Ctrl-S and Ctrl-Q
are flow control on many terminals -- pressing them can freeze output until
Ctrl-Q is pressed again, which looks exactly like a hung program -- so "run"
is Ctrl-R and "quit" is Ctrl-X.
"""

from __future__ import annotations

from typing import Callable

from .keys import Key

Action = Callable[["Editor"], None]  # noqa: F821 - avoids a circular import


def binding(key: Key) -> str:
    """The table key for a key press.

    Lives here rather than on the application because two applications now
    share this table -- the editor and the boss-fight repair pane -- and a
    binding that resolved differently in each would make the table a lie.
    """
    if key.ctrl and key.char:
        return f"ctrl-{key.char}"
    return key.name


def _page(editor, direction: int) -> None:
    """Move a screenful. The editor owns the height, so ten is a stand-in
    until the frame passes its own geometry down."""
    editor.buffer.move(d_row=direction * 10)


def _quit(editor) -> None:
    editor.running = False


def _repaint(editor) -> None:
    """Force a full redraw. The escape hatch for a stale damage cache."""
    editor._previous = None


KEYMAP: dict[str, Action] = {
    # motion
    "up": lambda e: e.buffer.move(d_row=-1),
    "down": lambda e: e.buffer.move(d_row=1),
    "left": lambda e: e.buffer.move(d_column=-1),
    "right": lambda e: e.buffer.move(d_column=1),
    "home": lambda e: e.buffer.home(),
    "end": lambda e: e.buffer.end(),
    "pgup": lambda e: _page(e, -1),
    "pgdn": lambda e: _page(e, 1),
    "ctrl-a": lambda e: e.buffer.home(),
    "ctrl-e": lambda e: e.buffer.end(),

    # editing
    "enter": lambda e: e.buffer.newline(),
    "tab": lambda e: e.buffer.tab(),
    "backtab": lambda e: e.buffer.dedent(),
    "backspace": lambda e: e.buffer.backspace(),
    "delete": lambda e: e.buffer.delete(),
    "ctrl-k": lambda e: e.buffer.kill_line(),
    "ctrl-z": lambda e: e.buffer.undo(),
    "ctrl-y": lambda e: e.buffer.redo(),

    # application
    "ctrl-r": lambda e: e.execute(),
    "ctrl-x": _quit,
    "ctrl-c": _quit,
    "ctrl-l": _repaint,
}


#: Shown along the bottom of the editor, trimmed to fit.
HELP = (
    ("ctrl-r", "run"),
    ("ctrl-z", "undo"),
    ("ctrl-k", "kill line"),
    ("ctrl-l", "redraw"),
    ("ctrl-x", "quit"),
)

#: The same bindings in the boss-fight repair pane, where they mean the same
#: thing pointed at a paused child: ctrl-r runs the level there and resumes
#: the fight here. Only the labels differ, because only the labels should.
REPAIR_HELP = (
    ("ctrl-r", "resume"),
    ("ctrl-z", "undo"),
    ("ctrl-k", "kill line"),
    ("ctrl-x", "give up"),
)


def describe_keys(entries: "tuple[tuple[str, str], ...]" = HELP) -> str:
    return "   ".join(f"{key} {label}" for key, label in entries)
