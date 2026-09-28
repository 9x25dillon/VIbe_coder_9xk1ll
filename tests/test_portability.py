"""Real process failures behind the desktop runtime gate; stdlib only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from vibecoder._process import OutputLimit, Process
from vibecoder.models import Source, TestCase as Case
from vibecoder.runner import LiveRun, run_code
from vibecoder.sandbox import Launch, SandboxUnavailable


class TestPortablePipes(unittest.TestCase):
    def child(self, code):
        child = Process(Launch([sys.executable, "-I", "-c", code]),
                        mem_limit_mb=256, timeout=5)
        self.addCleanup(child.close)
        return child

    def test_utf8_survives_a_codepoint_split_across_writes(self):
        child = self.child("import os,time; os.write(1,b'\\xe2'); "
                           "time.sleep(.05); os.write(1,b'\\x98\\x83\\n')")
        self.assertEqual(child.readline(5), "☃")

    def test_stderr_is_drained_while_stdout_is_pending(self):
        child = self.child("import os; os.write(2,b'x'*1000000); os.write(1,b'done\\n')")
        self.assertEqual(child.readline(5), "done")
        child.wait(5)
        self.assertLessEqual(len(child.stderr), 65536)

    def test_partial_line_is_delivered_at_eof(self):
        child = self.child("import os; os.write(1,b'tail')")
        self.assertEqual(child.readline(5), "tail")
        self.assertIsNone(child.readline(5))

    def test_unterminated_line_has_a_memory_bound(self):
        child = self.child("import os; os.write(1,b'x'*10000)")
        with mock.patch('vibecoder._process.MAX_LINE', 4096):
            with self.assertRaises(OutputLimit):
                child.readline(5)

    def test_output_budget_counts_consumed_lines_too(self):
        child = self.child("import os; os.write(1,b'a\\n'*10000)")
        with mock.patch('vibecoder._process.MAX_OUTPUT', 4096):
            with self.assertRaises(OutputLimit):
                while child.readline(5) is not None:
                    pass

    def test_blocked_input_writer_does_not_disable_deadline(self):
        child = self.child("import time; time.sleep(60)")
        child.send(b'x' * 1000000)
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            child.readline(.15)
        child.close()
        self.assertLess(time.monotonic() - started, 3)

    def test_close_interrupts_a_blocked_reader_and_joins_threads(self):
        child = self.child("import time; time.sleep(60)")
        thread = threading.Thread(target=lambda: child.readline(60))
        thread.start()
        child.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(all(not t.is_alive() for t in child._threads))

    def test_owned_descendant_is_killed_when_root_has_exited(self):
        # A harmless child writes a marker only if ownership is broken. The
        # fallback lifetime is finite even on a failing platform.
        with tempfile.TemporaryDirectory() as directory:
            marker = str(Path(directory) / 'leaked')
            grandchild = f"import time,pathlib; time.sleep(1); pathlib.Path({marker!r}).touch()"
            code = ("import subprocess,sys; "
                    "sys.stdin.buffer.read(1); "
                    f"subprocess.Popen([sys.executable,'-I','-c',{grandchild!r}]); "
                    "print('started',flush=True)")
            child = self.child(code)
            child.send(b'x')  # Job assignment has happened before any fork.
            self.assertEqual(child.readline(5), 'started')
            child.wait(5)
            child.close()
            time.sleep(1.2)
            self.assertFalse(Path(marker).exists())


class TestPortableRunner(unittest.TestCase):
    def setUp(self):
        # These check the local runtime transport. The existing escape suite
        # separately exercises every real isolating backend on Linux.
        patch = mock.patch.dict(os.environ, {'VIBECODER_SANDBOX': 'subprocess'})
        patch.start()
        self.addCleanup(patch.stop)

    def test_streamed_submission_uses_no_select_on_pipes(self):
        with mock.patch('select.select', side_effect=AssertionError('pipe select')):
            progress = []
            result = run_code('def f():\n    return 1\n', 'f',
                              [Case('✓', [], expected=1)], source=Source.PLAYER,
                              on_progress=lambda *args: progress.append(args))
        self.assertTrue(result.all_passed, result.error)
        self.assertEqual(progress[0][2], '✓')

    def test_callback_exception_reaps_io_threads(self):
        before = {t.ident for t in threading.enumerate()}
        def fail(*args):
            raise RuntimeError('renderer failed')
        with self.assertRaisesRegex(RuntimeError, 'renderer failed'):
            run_code('def f():\n    return 1\n', 'f', [Case('t', [], expected=1)],
                     source=Source.PLAYER, on_progress=fail)
        leaked = [t.name for t in threading.enumerate()
                  if t.ident not in before and t.name.startswith('vibecoder-')]
        self.assertEqual(leaked, [])

    def test_pin_cannot_execute_third_party_source(self):
        with self.assertRaises(SandboxUnavailable):
            run_code('def f():\n    return 1\n', 'f', [], source=Source.THIRD_PARTY)
        with self.assertRaises(SandboxUnavailable):
            with LiveRun('def f():\n    return 1\n', 'f', Case('t', []),
                         source=Source.THIRD_PARTY):
                pass

    def test_live_abort_before_first_event_is_immediate(self):
        with LiveRun('import time\ntime.sleep(60)\ndef f():\n    return 1\n',
                     'f', Case('t', [], expected=1), source=Source.PLAYER) as live:
            started = time.monotonic()
            live.abort()
            self.assertLess(time.monotonic() - started, 2)
            self.assertEqual(live.result().error_type, 'Aborted')

    def test_live_native_call_without_trace_events_has_parent_watchdog(self):
        code = 'import time\ndef f():\n    time.sleep(60)\n    return 1\n'
        with LiveRun(code, 'f', Case('t', [], expected=1), source=Source.PLAYER,
                     timeout=.5) as live:
            self.assertIsNotNone(live.step())
            started = time.monotonic()
            self.assertIsNone(live.step())
            self.assertLess(time.monotonic() - started, 2)
            self.assertIn('budget', live.result().error)

    def test_live_closed_output_is_a_diagnosable_failure(self):
        with LiveRun('import os\nos._exit(7)\ndef f():\n    return 1\n',
                     'f', Case('t', []), source=Source.PLAYER) as live:
            self.assertIsNone(live.step())
            self.assertTrue(live.finished)
            self.assertEqual(live.result().error_type, 'SandboxCrash')

    def test_memory_limit_stops_oversized_local_allocation(self):
        result = run_code('def f():\n    return len(bytearray(256*1024*1024))\n',
                          'f', [Case('t', [], expected=256*1024*1024)],
                          source=Source.PLAYER, mem_limit_mb=128, timeout=5)
        self.assertFalse(result.all_passed, 'platform did not enforce the memory cap')

    def test_cli_can_import_without_posix_terminal_modules(self):
        script = ("import sys; sys.modules['termios']=None; sys.modules['tty']=None; "
                  "import vibecoder.cli; from vibecoder.term import supported; "
                  "assert not supported(); assert vibecoder.cli.main(['--help']) is None")
        # argparse's help intentionally exits 0 before reaching the last assert.
        result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                                text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('usage: vibecoder', result.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows Job Object failure path")
    def test_windows_job_assignment_failure_never_runs_user_code(self):
        with mock.patch('vibecoder._windows_job.Job', side_effect=OSError('job denied')):
            with self.assertRaisesRegex(OSError, 'job denied'):
                run_code('def f():\n    return 1\n', 'f', [], source=Source.PLAYER)


if __name__ == '__main__':
    unittest.main()
