"""Bounded, portable pipes and ownership for a harness process.

Windows select() cannot read anonymous pipes. Reader threads work on every
supported OS and also drain stderr while stdout is being consumed. The queue
is bounded, decoding happens after complete byte lines, and every exit owns
cleanup. Nothing here interprets a game event or imports the standalone child.
"""
from __future__ import annotations

from collections import deque
import os
import queue
import signal
import subprocess
import threading
import time

CHUNK = 65536
MAX_LINE = 8 * 1024 * 1024
MAX_OUTPUT = 64 * 1024 * 1024
STDERR_TAIL = 65536


class OutputLimit(RuntimeError):
    """A child exceeded the bounded protocol channel, not a scoring limit."""


class Process:
    """A child whose pipes never require the UI thread to do blocking I/O."""

    def __init__(self, launch, *, mem_limit_mb: int, timeout: float) -> None:
        options = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, bufsize=0)
        if os.name == "nt":
            if launch.pass_fds:
                raise OSError("file-descriptor inheritance is not supported on Windows")
            options["creationflags"] = subprocess.CREATE_NO_WINDOW
        else:
            options.update(pass_fds=launch.pass_fds, start_new_session=True)
        self.process = subprocess.Popen(launch.argv, **options)
        self._job = None
        try:
            if os.name == "nt":
                from ._windows_job import Job
                self._job = Job(self.process, mem_limit_mb=mem_limit_mb, timeout=timeout)
        except BaseException:
            self.process.kill()
            self.process.communicate()
            raise
        self._closed = threading.Event()
        self._output = queue.Queue(maxsize=32)
        self._input = queue.Queue(maxsize=4)
        self._errors = deque(maxlen=STDERR_TAIL // CHUNK + 1)
        self._pending = bytearray()
        self._eof = False
        self._total = 0
        self._threads = [
            threading.Thread(target=self._read, name="vibecoder-stdout", daemon=True),
            threading.Thread(target=self._read_errors, name="vibecoder-stderr", daemon=True),
            threading.Thread(target=self._write, name="vibecoder-stdin", daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _put(self, value) -> None:
        while not self._closed.is_set():
            try:
                self._output.put(value, timeout=0.05)
                return
            except queue.Full:
                continue

    def _read(self) -> None:
        try:
            while not self._closed.is_set():
                chunk = os.read(self.process.stdout.fileno(), CHUNK)
                if not chunk:
                    break
                self._put(chunk)
        except (OSError, ValueError):
            pass
        finally:
            self._put(None)

    def _read_errors(self) -> None:
        try:
            while not self._closed.is_set():
                chunk = os.read(self.process.stderr.fileno(), CHUNK)
                if not chunk:
                    break
                self._errors.append(chunk)
        except (OSError, ValueError):
            pass

    def _write(self) -> None:
        try:
            while not self._closed.is_set():
                try:
                    data = self._input.get(timeout=0.05)
                except queue.Empty:
                    continue
                if data is None:
                    self.process.stdin.close()
                    return
                view = memoryview(data)
                while view and not self._closed.is_set():
                    written = os.write(self.process.stdin.fileno(), view)
                    view = view[written:]
        except (OSError, ValueError):
            pass  # EOF/exit is reported on the result channel.

    def send(self, data: bytes, *, eof: bool = False) -> None:
        """Queue input without blocking behind a child that stopped reading."""
        if self._closed.is_set():
            return
        try:
            self._input.put_nowait(data)
            if eof:
                self._input.put_nowait(None)
        except queue.Full as exc:
            raise OutputLimit("child control queue is full") from exc

    def readline(self, timeout: float) -> str | None:
        """Return one complete UTF-8 line, EOF, or a bounded-time failure."""
        deadline = time.monotonic() + timeout
        while True:
            newline = self._pending.find(b"\n")
            if newline >= 0:
                if newline > MAX_LINE:
                    raise OutputLimit("child protocol line exceeds 8 MiB")
                line = self._pending[:newline]
                del self._pending[:newline + 1]
                return line.decode("utf-8", "replace")
            if len(self._pending) > MAX_LINE:
                raise OutputLimit("child protocol line exceeds 8 MiB")
            if self._eof or self._closed.is_set():
                if self._pending:
                    line = bytes(self._pending)
                    self._pending.clear()
                    return line.decode("utf-8", "replace")
                return None
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(self.process.args, timeout)
            try:
                chunk = self._output.get(timeout=min(remaining, 0.05))
            except queue.Empty:
                continue
            if chunk is None:
                self._eof = True
            else:
                self._total += len(chunk)
                if self._total > MAX_OUTPUT:
                    raise OutputLimit("child protocol output exceeds 64 MiB")
                self._pending.extend(chunk)

    def wait(self, timeout: float) -> int:
        return self.process.wait(timeout=max(0.001, timeout))

    @property
    def stderr(self) -> str:
        return b"".join(list(self._errors))[-STDERR_TAIL:].decode("utf-8", "replace")

    def close(self) -> None:
        """Kill owned processes before closing pipes; otherwise close can hang.

        POSIX local children stay in the new process group. An intentionally
        hostile process may escape that group; provenance requires a real
        isolating backend for that threat model. Windows descendants stay in
        the Job Object, including after the root process has exited.
        """
        if self._closed.is_set():
            return
        self._closed.set()
        if self._job is not None:
            self._job.close()
        elif os.name != "nt":
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait()
        for thread in self._threads:
            thread.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
