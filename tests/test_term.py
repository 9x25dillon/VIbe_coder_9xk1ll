"""Terminal restoration. Exit criterion 1, driven through a real pty.

The hazard note calls restoration "the whole ballgame": raw mode, the
alternate screen and a hidden cursor are global state on a resource the
process does not own, and leaving any of them set is what teaches people to
distrust terminal applications. So these tests do not inspect the code, they
run a child process against a pty and check what state the terminal is left
in afterwards.
"""

import os
import pty
import subprocess
import sys
import tempfile
import termios
import textwrap
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from vibecoder.term import CURSOR_HIDE, CURSOR_SHOW  # noqa: E402

#: Prepended to every child script. Dedented here so that callers can indent
#: their own bodies to taste without the two disagreeing.
PROLOGUE = "import os, signal, sys, termios\nfrom vibecoder.term import TerminalSession\n"


def run_on_pty(body: str = "", *, prologue: bool = True,
               timeout: float = 30.0) -> tuple[int, list, str]:
    """Run ``body`` with a pty on stdin/stdout. Returns the terminal state.

    The child gets a real pty so that ``termios`` and ``isatty`` behave; the
    parent reads back the attributes afterwards to see what was left behind.
    """
    primary, secondary = pty.openpty()
    original = termios.tcgetattr(secondary)
    script = (PROLOGUE if prologue else "") + textwrap.dedent(body)
    try:
        child = subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=secondary, stdout=secondary, stderr=subprocess.PIPE,
            cwd=REPO, env={**os.environ, "PYTHONPATH": REPO, "TERM": "xterm"},
            close_fds=True,
        )
        _, stderr = child.communicate(timeout=timeout)
        after = termios.tcgetattr(secondary)
        return child.returncode, [original, after], stderr.decode()
    finally:
        os.close(primary)
        os.close(secondary)


class TestRestoration(unittest.TestCase):
    def test_a_normal_exit_restores_the_terminal(self):
        code, (before, after), err = run_on_pty("""
            with TerminalSession() as t:
                pass
        """)
        self.assertEqual(code, 0, err)
        self.assertEqual(before, after)

    def test_an_exception_restores_the_terminal(self):
        code, (before, after), err = run_on_pty("""
            try:
                with TerminalSession() as t:
                    raise ValueError("boom")
            except ValueError:
                pass
        """)
        self.assertEqual(code, 0, err)
        self.assertEqual(before, after)

    def test_an_uncaught_exception_restores_the_terminal(self):
        """The traceback is useless if it prints into raw mode."""
        code, (before, after), _ = run_on_pty("""
            with TerminalSession() as t:
                raise ValueError("boom")
        """)
        self.assertNotEqual(code, 0)
        self.assertEqual(before, after)

    def test_sigterm_restores_the_terminal(self):
        code, (before, after), err = run_on_pty("""
            t = TerminalSession()
            t.start()
            os.kill(os.getpid(), signal.SIGTERM)
        """)
        self.assertEqual(before, after)
        # Killed by SIGTERM, not exited cleanly: the handler re-raises with the
        # default disposition so the exit status stays honest.
        self.assertEqual(code, -15, err)

    def test_sighup_restores_the_terminal(self):
        code, (before, after), err = run_on_pty("""
            t = TerminalSession()
            t.start()
            os.kill(os.getpid(), signal.SIGHUP)
        """)
        self.assertEqual(before, after)

    def test_sigint_restores_the_terminal(self):
        """Criterion 1 names SIGINT, and `term` deliberately installs no
        handler for it.

        That is not an omission: raw mode turns off ISIG, so Ctrl-C reaches
        the application as a key rather than a signal. But a SIGINT delivered
        from outside -- `kill -INT`, a process group being interrupted -- still
        arrives, raises `KeyboardInterrupt`, and must leave the terminal as it
        was. `KeyboardInterrupt` derives from `BaseException` rather than
        `Exception`, which is exactly the kind of thing an `except Exception`
        somewhere in the stack would swallow the cleanup for.
        """
        code, (before, after), err = run_on_pty("""
            try:
                with TerminalSession() as t:
                    os.kill(os.getpid(), signal.SIGINT)
            except KeyboardInterrupt:
                pass
        """)
        self.assertEqual(code, 0, err)
        self.assertEqual(before, after)

    def test_ctrl_c_is_a_key_rather_than_a_signal_in_raw_mode(self):
        """The premise of the test above, asserted rather than assumed.

        If ISIG were left on, Ctrl-C would kill the editor instead of reaching
        the key decoder, and the reason SIGINT is absent from the handler list
        would stop being true.
        """
        code, _, err = run_on_pty("""
            t = TerminalSession()
            t.start()
            attrs = termios.tcgetattr(sys.stdin.fileno())
            t.restore()
            assert not (attrs[3] & termios.ISIG), "ISIG is still on in raw mode"
        """)
        self.assertEqual(code, 0, err)

    def test_forgetting_to_restore_is_caught_by_atexit(self):
        """The last line of defence: no context manager, no signal, no finally."""
        code, (before, after), err = run_on_pty("""
            t = TerminalSession()
            t.start()
            sys.exit(0)
        """)
        self.assertEqual(code, 0, err)
        self.assertEqual(before, after)

    def test_restore_is_idempotent(self):
        code, (before, after), err = run_on_pty("""
            t = TerminalSession()
            t.start()
            t.restore()
            t.restore()
            t.restore()
        """)
        self.assertEqual(code, 0, err)
        self.assertEqual(before, after)

    def test_raw_mode_is_actually_entered(self):
        """A restoration test proves nothing if the mode never changed."""
        code, _, err = run_on_pty("""
            saved = termios.tcgetattr(sys.stdin.fileno())
            t = TerminalSession()
            t.start()
            inside = termios.tcgetattr(sys.stdin.fileno())
            t.restore()
            assert inside != saved, "raw mode was never entered"
        """)
        self.assertEqual(code, 0, err)


class TestScreenState(unittest.TestCase):
    def test_the_alternate_screen_is_left_on_exit(self):
        code, _, err = run_on_pty(prologue=False, body="""
            import sys
            from vibecoder.term import ALT_SCREEN_OFF, CURSOR_SHOW, TerminalSession
            import io
            out = io.StringIO()
            t = TerminalSession(stream=out)
            t.start()
            t.restore()
            written = out.getvalue()
            assert ALT_SCREEN_OFF in written, "never left the alternate screen"
            assert CURSOR_SHOW in written, "never restored the cursor"
            assert written.index(CURSOR_SHOW) < written.index(ALT_SCREEN_OFF)
        """)
        self.assertEqual(code, 0, err)

    def test_bracketed_paste_is_turned_back_off(self):
        code, _, err = run_on_pty(prologue=False, body="""
            import io
            from vibecoder.term import PASTE_OFF, PASTE_ON, TerminalSession
            out = io.StringIO()
            t = TerminalSession(stream=out)
            t.start()
            t.restore()
            written = out.getvalue()
            assert PASTE_ON in written and PASTE_OFF in written
        """)
        self.assertEqual(code, 0, err)


class TestTheCursorComesBack(unittest.TestCase):
    """Criterion 1 says "in its original mode **with the cursor visible**".

    The restoration tests above compare `termios` attributes, which say
    nothing about the cursor: it is hidden with a private-mode sequence, not a
    terminal flag. Only the normal-exit path asserted `CURSOR_SHOW` until
    2026-09-08, so the half of the criterion a player would actually notice
    was untested on every abnormal path.
    """

    def leaves_cursor_shown(self, body: str) -> tuple[int, str]:
        """Run ``body`` with the session writing to a file, and read it back.

        A file rather than a `StringIO` because two of these paths end with
        the process being killed by the signal it re-raised, so the assertion
        has to survive the child. `TerminalSession._write` flushes, so what
        reaches the file is what reached the terminal.
        """
        with tempfile.TemporaryDirectory() as tmp:
            log = os.path.join(tmp, "out")
            code, _, err = run_on_pty(f"""
                from vibecoder.term import CURSOR_SHOW
                stream = open({log!r}, "w")
                {body}
            """)
            with open(log, encoding="utf-8", errors="replace") as fh:
                return code, fh.read()

    def test_the_cursor_is_restored_after_sigterm(self):
        _, written = self.leaves_cursor_shown("""
                t = TerminalSession(stream=stream)
                t.start()
                os.kill(os.getpid(), signal.SIGTERM)
        """)
        self.assertIn(CURSOR_SHOW, written)

    def test_the_cursor_is_restored_after_sighup(self):
        _, written = self.leaves_cursor_shown("""
                t = TerminalSession(stream=stream)
                t.start()
                os.kill(os.getpid(), signal.SIGHUP)
        """)
        self.assertIn(CURSOR_SHOW, written)

    def test_the_cursor_is_restored_after_sigint(self):
        _, written = self.leaves_cursor_shown("""
                try:
                    with TerminalSession(stream=stream) as t:
                        os.kill(os.getpid(), signal.SIGINT)
                except KeyboardInterrupt:
                    pass
        """)
        self.assertIn(CURSOR_SHOW, written)

    def test_the_cursor_is_restored_after_an_uncaught_exception(self):
        _, written = self.leaves_cursor_shown("""
                try:
                    with TerminalSession(stream=stream) as t:
                        raise ValueError("boom")
                except ValueError:
                    pass
        """)
        self.assertIn(CURSOR_SHOW, written)

    def test_the_cursor_is_restored_by_atexit_alone(self):
        _, written = self.leaves_cursor_shown("""
                t = TerminalSession(stream=stream)
                t.start()
                sys.exit(0)
        """)
        self.assertIn(CURSOR_SHOW, written)

    def test_the_cursor_is_hidden_in_the_first_place(self):
        """A restoration assertion proves nothing if it was never hidden."""
        _, written = self.leaves_cursor_shown("""
                from vibecoder.term import CURSOR_HIDE
                t = TerminalSession(stream=stream)
                t.start()
                t.restore()
        """)
        self.assertIn(CURSOR_HIDE, written)
        self.assertLess(written.index(CURSOR_HIDE), written.index(CURSOR_SHOW))


class TestSupported(unittest.TestCase):
    def test_a_pipe_is_not_a_terminal(self):
        from vibecoder.term import supported

        with open(os.devnull, "w") as sink:
            self.assertFalse(supported(stream=sink))

    def test_a_dumb_terminal_is_refused(self):
        code, _, err = run_on_pty(prologue=False, body="""
            import os
            os.environ["TERM"] = "dumb"
            from vibecoder.term import supported
            assert not supported(), "a dumb terminal should be refused"
        """)
        self.assertEqual(code, 0, err)

    def test_a_real_pty_is_supported(self):
        code, _, err = run_on_pty(prologue=False, body="""
            from vibecoder.term import supported
            assert supported(), "a real pty should be supported"
        """)
        self.assertEqual(code, 0, err)


class TestGeometry(unittest.TestCase):
    def test_size_falls_back_when_undetectable(self):
        import io

        from vibecoder.term import TerminalSession

        session = TerminalSession.__new__(TerminalSession)
        session.stream = io.StringIO()
        self.assertEqual(session.size(), (24, 80))

    def test_the_resize_flag_is_set_once_then_cleared(self):
        import io

        from vibecoder.term import TerminalSession

        session = TerminalSession.__new__(TerminalSession)
        session._resized = True
        self.assertTrue(session.resized)
        self.assertFalse(session.resized)


if __name__ == "__main__":
    unittest.main()
