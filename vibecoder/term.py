"""Raw-mode terminal session: alt screen, hidden cursor, guaranteed restore.

T7 W1. Raw mode, the alternate screen and cursor visibility are three pieces
of global state on a resource this process does not own. Leaving any of them
set is the failure that teaches people to distrust terminal applications --
the shell comes back without an echo, or scrolled into a screen full of
someone else's frame.

Restoration is therefore driven three ways, because each one misses a case the
others catch:

* ``try/finally`` via the context manager -- covers normal exit and exceptions.
* ``atexit`` -- covers ``os._exit``-adjacent paths and interpreter shutdown
  after the frame is gone.
* signal handlers for ``SIGTERM`` and ``SIGHUP`` -- cover being killed, and
  the terminal emulator closing out from under the process.

``restore()`` is idempotent, so all three firing costs nothing.

``SIGINT`` is deliberately *not* in that list. Raw mode turns off ISIG, so
Ctrl-C arrives as a key event rather than a signal, and the application
decides what it means.
"""

from __future__ import annotations

import atexit
import os
import select
import signal
import sys
import termios
import tty

# Private-mode sequences. Paired so that every enable has a disable.
ALT_SCREEN_ON = "\033[?1049h"
ALT_SCREEN_OFF = "\033[?1049l"
CURSOR_HIDE = "\033[?25l"
CURSOR_SHOW = "\033[?25h"
PASTE_ON = "\033[?2004h"
PASTE_OFF = "\033[?2004l"
CLEAR = "\033[2J\033[H"

MIN_WIDTH = 48
MIN_HEIGHT = 12


def supported(stream=None, input_stream=None) -> bool:
    """Whether a full-screen session can run against these streams."""
    stream = stream or sys.stdout
    input_stream = input_stream or sys.stdin
    if os.environ.get("TERM", "") in ("", "dumb"):
        return False
    try:
        return bool(stream.isatty() and input_stream.isatty())
    except (AttributeError, ValueError):
        return False


class TerminalSession:
    """Owns the terminal for the duration of a ``with`` block.

    Use it as a context manager; ``restore`` on the way out is not optional
    and is not the caller's responsibility.
    """

    def __init__(self, stream=None, input_stream=None) -> None:
        self.stream = stream or sys.stdout
        self.input = input_stream or sys.stdin
        self._fd = self.input.fileno()
        self._saved: list | None = None
        self._previous_handlers: dict[int, object] = {}
        self._resized = True  # force a first layout
        self._active = False

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "TerminalSession":
        self.start()
        return self

    def __exit__(self, *exc_info) -> bool:
        self.restore()
        return False

    def start(self) -> None:
        if self._active:
            return
        self._saved = termios.tcgetattr(self._fd)
        # Registered *before* the mode changes, so a failure between here and
        # the end of this method still restores.
        atexit.register(self.restore)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            self._previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, self._on_fatal_signal)
        self._previous_handlers[signal.SIGWINCH] = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGWINCH, self._on_resize)

        tty.setraw(self._fd)
        self._write(ALT_SCREEN_ON + CURSOR_HIDE + PASTE_ON + CLEAR)
        self._active = True

    def restore(self) -> None:
        """Put the terminal back. Safe to call any number of times."""
        if not self._active:
            return
        self._active = False
        try:
            self._write(PASTE_OFF + CURSOR_SHOW + ALT_SCREEN_OFF)
        except Exception:  # noqa: BLE001 - restoring the mode matters more
            pass
        if self._saved is not None:
            try:
                termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved)
            except (termios.error, OSError):
                pass
        for sig, handler in self._previous_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError, TypeError):
                pass
        self._previous_handlers.clear()

    def _on_fatal_signal(self, signum, frame) -> None:
        self.restore()
        # Re-raise with the default handler so the exit status is honest about
        # having been killed rather than reporting a clean exit.
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    def _on_resize(self, signum, frame) -> None:
        self._resized = True

    # -- io ----------------------------------------------------------------

    def _write(self, text: str) -> None:
        self.stream.write(text)
        self.stream.flush()

    def write(self, text: str) -> None:
        if text:
            self._write(text)

    def read(self, timeout: float | None = None) -> bytes:
        """Read whatever input is available, waiting up to ``timeout``.

        Returns empty bytes on timeout. A signal arriving mid-wait surfaces as
        an empty read rather than an exception, so the caller's loop can notice
        a resize and carry on.
        """
        try:
            ready, _, _ = select.select([self._fd], [], [], timeout)
        except (InterruptedError, OSError):
            return b""
        if not ready:
            return b""
        try:
            return os.read(self._fd, 4096)
        except (InterruptedError, OSError):
            return b""

    # -- geometry ----------------------------------------------------------

    @property
    def resized(self) -> bool:
        """True once after each SIGWINCH. Reading it clears the flag."""
        was = self._resized
        self._resized = False
        return was

    def size(self) -> tuple[int, int]:
        """``(rows, columns)``, falling back to 80x24 when undetectable."""
        try:
            columns, rows = os.get_terminal_size(self.stream.fileno())
        except (OSError, ValueError, AttributeError):
            return 24, 80
        return max(rows, 1), max(columns, 1)

    def too_small(self) -> bool:
        rows, columns = self.size()
        return rows < MIN_HEIGHT or columns < MIN_WIDTH
