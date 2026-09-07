"""Parent-side driver for the execution sandbox.

Submissions run in a separate process so that an infinite loop, a ``sys.exit``
or an exhausted memory limit takes down only the child. The parent enforces a
wall-clock timeout that the child cannot escape.

*Which* process is a question for :mod:`vibecoder.sandbox`. This module builds
the payload, spawns whatever argv the selected backend hands back, and parses
the reply; it holds no opinion about namespaces or containers. The seam exists
so that ``untrusted=True`` can move execution into an isolated backend without
anything else in the codebase noticing.
"""

from __future__ import annotations

import json
import os
import select
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from . import sandbox
from .timeline import Divergence, Timeline, compare
from .models import Level, RunResult, Source, TestCase, TestOutcome

HARNESS = Path(__file__).with_name("_harness.py")

DEFAULT_TIMEOUT = 10.0
DEFAULT_MEM_LIMIT_MB = 512
#: Processes a submission may own, when it owns a uid of its own. Generous for
#: anything a level needs, ruinous for a fork bomb.
PROC_LIMIT = 64

#: Called with ``(index, total, name, passed)`` as each test reports.
ProgressHook = Callable[[int, int, str, bool], None]

SUBMISSION_FILENAME = "<vibecoder-submission>"
REFERENCE_FILENAME = "<vibecoder-reference>"


def run_code(
    code: str,
    func_name: str,
    tests: Sequence[TestCase],
    *,
    source: Source,
    timeout: float = DEFAULT_TIMEOUT,
    mem_limit_mb: int = DEFAULT_MEM_LIMIT_MB,
    record_trace: bool = False,
    filename: str = SUBMISSION_FILENAME,
    on_progress: "ProgressHook | None" = None,
) -> RunResult:
    """Execute ``code`` against ``tests`` in a sandboxed child process.

    ``on_progress`` is called as each test reports, before the run finishes,
    which is what lets a front-end show results assembling rather than
    appearing. Omitting it takes the simpler path that waits for the child --
    the reply is the same either way, so nothing downstream can tell which was
    used.

    ``source`` says where the code came from, and has no default **on
    purpose**. A default would mean that the one thing a future caller can
    forget is the thing that decides whether a stranger's Python runs on the
    player's machine -- and forgetting would be silent, because the fast path
    works perfectly right up until it matters. Without a default, forgetting
    is a ``TypeError`` at the call site.

    :class:`~vibecoder.models.Source` decides; this function only asks. A
    source that requires isolation and finds none available raises rather than
    downgrading, because rlimits are not a fence against someone who meant it.
    """
    payload = {
        "code": code,
        "func_name": func_name,
        "tests": [t.to_json() for t in tests],
        "timeout": timeout,
        "mem_limit_mb": mem_limit_mb,
        "record_trace": record_trace,
        "filename": filename,
    }

    backend = sandbox.select(untrusted=source.requires_isolation)

    # A fork bomb is only contained by the wall clock unless the child caps
    # its own process count, and RLIMIT_NPROC counts every process owned by
    # the real uid -- so on the host path it would count the player's whole
    # login session and fail instantly. It is only safe where the submission
    # has a uid to itself, which is exactly what an isolating backend gives.
    if backend.isolating:
        payload["proc_limit"] = PROC_LIMIT

    try:
        with backend.launch(HARNESS, mem_limit_mb=mem_limit_mb) as launch:
            if on_progress is None:
                completed = subprocess.run(
                    launch.argv,
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    pass_fds=launch.pass_fds,
                )
                code, out, err = (
                    completed.returncode, completed.stdout, completed.stderr
                )
            else:
                code, out, err = _stream(
                    launch, json.dumps(payload), timeout, on_progress
                )
    except subprocess.TimeoutExpired:
        return RunResult(
            error=f"execution exceeded {timeout:g}s - check for an infinite loop",
            error_type="Timeout",
        )

    if code != 0 or not out.strip():
        detail = (err or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit code {code}"
        label = "sandbox" if backend.name == "subprocess" else f"{backend.name} sandbox"
        return RunResult(error=f"{label} crashed: {tail}", error_type="SandboxCrash")

    raw = _final_event(out)
    if raw is None:
        return RunResult(
            error="sandbox returned malformed output", error_type="SandboxCrash"
        )

    return _result_from(raw)


def _result_from(raw: dict) -> RunResult:
    """Turn a harness ``result`` event into a `RunResult`.

    Shared with `LiveRun`, which receives the same event over a pipe it is
    still holding open rather than from a finished process.
    """
    return RunResult(
        outcomes=[TestOutcome(**o) for o in raw.get("outcomes", [])],
        wall_seconds=raw.get("wall_seconds", 0.0),
        ops=raw.get("ops", 0),
        peak_bytes=raw.get("peak_bytes", 0),
        stdout=raw.get("stdout", ""),
        error=raw.get("error", ""),
        error_type=raw.get("error_type", ""),
        trace=raw.get("trace", []),
    )


def _final_event(out: str) -> dict | None:
    """The one ``result`` line out of the reply stream.

    Scanned from the end, because progress lines precede it and a submission
    cannot append to the stream after it -- the harness writes it last and the
    child then exits.
    """
    for line in reversed(out.strip().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("event") == "result":
            return event
    return None


def _stream(launch, payload: str, timeout: float,
            on_progress: ProgressHook) -> tuple[int, str, str]:
    """Spawn, feed stdin, and read the reply as it arrives.

    The parent enforces the wall clock itself here, because ``communicate``
    would block until the child is finished and there would be nothing left to
    stream. Reading is a ``select`` loop over the raw descriptor rather than
    ``readline``, which can block past the deadline.
    """
    process = subprocess.Popen(
        launch.argv,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=launch.pass_fds,
    )
    try:
        process.stdin.write(payload.encode())
        process.stdin.close()
    except BrokenPipeError:
        pass  # the child died early; the exit code will say so

    deadline = time.monotonic() + timeout
    out = bytearray()
    pending = ""
    stream = process.stdout

    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.wait()
                raise subprocess.TimeoutExpired(launch.argv, timeout)
            try:
                ready, _, _ = select.select([stream], [], [], min(0.05, remaining))
            except (OSError, ValueError):
                break
            if not ready:
                if process.poll() is not None:
                    break
                continue
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                break
            out += chunk
            pending += chunk.decode("utf-8", "replace")
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                _dispatch(line, on_progress)

        stderr = process.stderr.read().decode("utf-8", "replace")
        process.wait()
        return process.returncode, out.decode("utf-8", "replace"), stderr
    finally:
        # The timeout path leaves by exception, and both pipes are ours to
        # close either way.
        for pipe in (process.stdout, process.stderr):
            try:
                pipe.close()
            except OSError:
                pass


def _dispatch(line: str, on_progress: ProgressHook) -> None:
    line = line.strip()
    if not line:
        return
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return
    if not isinstance(event, dict) or event.get("event") != "progress":
        return
    try:
        on_progress(
            int(event["index"]), int(event["total"]),
            str(event.get("name", "")), bool(event.get("passed")),
        )
    except (KeyError, TypeError, ValueError):
        return  # a malformed event must not take down the run


def run_submission(
    level: Level,
    code: str,
    tests: Sequence[TestCase],
    *,
    record_trace: bool = False,
    source: Source = Source.PLAYER,
    on_progress: "ProgressHook | None" = None,
) -> RunResult:
    """Run a player's attempt at ``level``.

    The provenance here is the *submission's*, not the level's: a player
    solving a community level is still typing their own code. The level's own
    code -- its reference solution -- goes through
    :func:`reference_benchmark`, which uses ``level.source`` instead.
    """
    return run_code(
        code,
        level.func_name,
        tests,
        source=source,
        record_trace=record_trace,
        filename=SUBMISSION_FILENAME,
        on_progress=on_progress,
    )


_REFERENCE_BENCHMARKS: dict[tuple[str, int], tuple[int, int]] = {}


def reference_benchmark(level: Level, seed: int) -> tuple[int, int]:
    """Return ``(ops, peak_bytes)`` for the level's reference solution.

    The reference is benchmarked against the *same* generated test data the
    player faces, because a variant with 10x the input rows would otherwise be
    compared against a benchmark from a much smaller run. Results are cached
    per (level, seed) since the reference never changes within a variant.
    """
    key = (level.id, seed)
    if key in _REFERENCE_BENCHMARKS:
        return _REFERENCE_BENCHMARKS[key]

    tests = level.tests_for(seed)
    # The reference solution is the *level author's* code. For everything in
    # this repository that is BUNDLED and takes the fast path; for a community
    # level it is a stranger's Python, and this is the call site that would
    # otherwise run it on the host.
    result = run_code(
        level.reference,
        level.func_name,
        tests,
        source=level.source,
        filename=REFERENCE_FILENAME,
    )
    if result.fatal:
        raise RuntimeError(
            f"reference solution for level {level.id} failed: {result.error}"
        )
    if not result.all_passed:
        failed = [o.name for o in result.outcomes if not o.passed]
        raise RuntimeError(
            f"reference solution for level {level.id} does not pass its own "
            f"tests (seed {seed}): {', '.join(failed)}"
        )

    benchmark = (result.ops, result.peak_bytes)
    _REFERENCE_BENCHMARKS[key] = benchmark
    return benchmark


# --------------------------------------------------------------------------
# Live stepping (T3 W2)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    """One line, as it executed.

    Deliberately the same ``{line, func, locals}`` shape `_record_trace`
    produces, because `replay` and `vision` already read that and a second
    shape would mean a second renderer. ``index`` is the parent's convenience
    and is ignored by anything consuming a recorded trace.
    """

    index: int
    line: int
    func: str
    locals: dict[str, str]
    #: Set on the step where an exception was *raised*, while the frame was
    #: still on that line. Deliberately absent from `to_trace`: the recorded
    #: shape stays the three fields `replay` and `vision` already read, and a
    #: fourth key would be a second shape for them to know about.
    error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error)

    def to_trace(self) -> dict:
        return {"line": self.line, "func": self.func, "locals": dict(self.locals)}


class LiveRun:
    """A submission executing under the parent's control, one line at a time.

    The child runs a line, reports it, and blocks waiting to be told what to
    do next, so **pause needs no implementation**: it is the parent not
    answering yet. That also means the child never sleeps, so pacing, variable
    speed and fast-forward all live here, where the player is -- and a paused
    fight cannot time out for being watched carefully, because the child's
    budget counts executing time only.

    Not a context manager by accident: `close` is idempotent and safe to call
    twice, and the caller almost always wants ``with``.
    """

    def __init__(
        self,
        code: str,
        func_name: str,
        test: TestCase,
        *,
        source: Source,
        timeout: float = DEFAULT_TIMEOUT,
        mem_limit_mb: int = DEFAULT_MEM_LIMIT_MB,
        filename: str = SUBMISSION_FILENAME,
    ) -> None:
        self._payload = {
            "code": code,
            "func_name": func_name,
            "tests": [test.to_json()],
            "timeout": timeout,
            "mem_limit_mb": mem_limit_mb,
            "record_trace": False,
            "filename": filename,
            "mode": "step",
        }
        self._source = source
        self._mem_limit_mb = mem_limit_mb
        self._context = None
        self._process = None
        self._pending = ""
        self._result: dict | None = None
        self._steps: list[Step] = []
        self._history = Timeline()
        # History from before the last edit, and whether re-running the edited
        # source reproduced it (T3 W4/W5). Empty until somebody edits.
        self._origin: list[Step] = []
        self._divergence: Divergence | None = None
        self._free = False
        self._told_free = False
        # The child emits a step and then blocks, whether or not we have read
        # it yet. Tracking that explicitly is what stops `resume` before the
        # first `step` from deadlocking: the parent owes a command it does not
        # otherwise know about.
        self._awaiting = False
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

    def __enter__(self) -> "LiveRun":
        self.start()
        return self

    def __exit__(self, *exc_info) -> bool:
        self.close()
        return False

    def start(self) -> None:
        backend = sandbox.select(untrusted=self._source.requires_isolation)
        if backend.isolating:
            self._payload["proc_limit"] = PROC_LIMIT
        self._context = backend.launch(HARNESS, mem_limit_mb=self._mem_limit_mb)
        launch = self._context.__enter__()
        self._process = subprocess.Popen(
            launch.argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            pass_fds=launch.pass_fds,
        )
        # One line, and stdin stays open: the payload and the control channel
        # share the pipe, which is what makes this steerable at all.
        self._write(json.dumps(self._payload))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._teardown()

    def _teardown(self) -> None:
        """Shut the child down without deciding whether we are done with it.

        Split out of `close` because an edit needs exactly this and then a
        fresh child, while `close` also means "and never again".
        """
        if self._process is not None:
            for pipe in (self._process.stdin, self._process.stdout,
                         self._process.stderr):
                try:
                    if pipe is not None:
                        pipe.close()
                except OSError:
                    pass
            if self._process.poll() is None:
                self._process.kill()
            self._process.wait()
        if self._context is not None:
            self._context.__exit__(None, None, None)
        self._process = None
        self._context = None

    # -- driving -----------------------------------------------------------

    def step(self) -> Step | None:
        """Advance one line and return it, or ``None`` when the run is over.

        Returning ``None`` rather than raising, because reaching the end of a
        function is the ordinary case here and a loop that stops is easier to
        read than one that catches.
        """
        if self._result is not None:
            return None
        if self._awaiting:
            self._write('{"cmd": "step"}')
            self._awaiting = False
        return self._read_step()

    def back(self) -> Step | None:
        """The previous step, from history. Nothing is re-executed.

        The child is not told and does not care: it is still blocked exactly
        where it was, and the reader is simply looking at an earlier page of
        what already happened.
        """
        return self._history.back()

    def forward(self) -> Step | None:
        """The next step, from history if there is one, otherwise from the child.

        This is the one place the two ideas meet. Inside history it is a
        cursor move; at the edge it drives the run. Callers get one verb
        because they should not have to know which they are doing.
        """
        replayed = self._history.forward()
        if replayed is not None:
            return replayed
        return self.step()

    @property
    def browsing(self) -> bool:
        """Whether the reader has stepped back into history."""
        return not self._history.at_edge

    @property
    def cursor(self) -> int:
        return self._history.cursor

    # -- editing -----------------------------------------------------------

    def edit(self, code: str) -> Divergence | None:
        """Replace the source and carry on from where the reader is looking.

        CPython will not swap the code object of a running frame, so "edit
        line 7 and continue" is not something the interpreter offers at all.
        This is T3's **strategy A**: run the edited source again from the top
        against the same recorded inputs, and fast-forward silently to the
        edit point.

        The memo strategy A needs is already here. The inputs are the test
        payload -- data the parent holds -- so replaying them costs nothing
        and cannot drift, which is why A is a better bet for the shapes this
        game poses than its general reputation suggests.

        Fast-forward stops **at** the step the reader is on, never through it.
        That step is the one whose behaviour the player just changed, so
        replaying it would replay the edit away. The run is left blocked just
        before it, ready to execute the edited line as the next step.

        Every fast-forwarded step is checked against the original (W5) and the
        first that does not match ends the fast-forward there and is returned.
        Going on past it would present a different execution as a continuation
        of the one the player watched, which is the lie exit criterion 4
        exists to forbid. Returning the finding rather than raising or
        printing keeps the decision about how loudly to say so with the
        caller, which is the only party that knows who is watching.
        """
        target = max(self._history.cursor, 0)
        original = self._steps
        self._teardown()
        self._payload = dict(self._payload, code=code)
        self._restart()

        divergence = None
        while len(self._steps) < target:
            if self.step() is None:
                break
            divergence = compare(original, self._steps, upto=len(self._steps))
            if divergence is not None:
                break
        if divergence is None:
            # The loop also exits when the edited run ends early. That prefix
            # is short rather than different, and `compare` is what knows the
            # difference between the two.
            divergence = compare(original, self._steps, upto=target)

        self._origin = original
        self._divergence = divergence
        return divergence

    def _restart(self) -> None:
        """A fresh child on the same payload, with history emptied.

        Stepping is restored even if the player had let the old run go free:
        after an edit they are driving again, from the edit point.
        """
        self._pending = ""
        self._result = None
        self._steps = []
        self._history = Timeline()
        self._free = False
        self._told_free = False
        self._awaiting = False
        self._closed = False
        self.start()

    def resume(self) -> None:
        """Let it run to completion without waiting for us again."""
        if self._result is not None:
            return
        self._free = True
        self._release()

    def abort(self) -> None:
        """Stop the run where it stands."""
        if self._result is not None:
            return
        if self._awaiting:
            self._write('{"cmd": "abort"}')
            self._awaiting = False
        self.drain()

    def drain(self) -> RunResult:
        """Read to the end and return the result, whatever is left to happen."""
        while self._result is None:
            if self._read_step() is None:
                break
        return self.result()

    def result(self) -> RunResult:
        payload = self._result or {
            "outcomes": [], "wall_seconds": 0.0, "ops": 0, "peak_bytes": 0,
            "stdout": "", "error": "the run produced no result",
            "error_type": "NoReply", "trace": [t.to_trace() for t in self._steps],
        }
        return _result_from(payload)

    @property
    def steps(self) -> list[Step]:
        return list(self._steps)

    @property
    def code(self) -> str:
        """The source the child is running.

        After an edit this is the edited text, which is what makes T3's exit
        criterion 3 -- the edit reflected in the final submitted source --
        something a caller can read rather than assume.
        """
        return str(self._payload["code"])

    @property
    def origin(self) -> list[Step]:
        """The history the last edit replaced. Empty until one happens."""
        return list(self._origin)

    @property
    def divergence(self) -> "Divergence | None":
        """Whether the last edit's fast-forward reproduced what it replaced."""
        return self._divergence

    @property
    def finished(self) -> bool:
        return self._result is not None

    # -- plumbing ----------------------------------------------------------

    def _release(self) -> None:
        """Tell a blocked child to stop waiting for us, once."""
        if self._free and self._awaiting and not self._told_free:
            self._write('{"cmd": "run"}')
            self._told_free = True
            self._awaiting = False

    def _write(self, line: str) -> None:
        try:
            self._process.stdin.write((line + "\n").encode())
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, AttributeError, ValueError):
            # The child is gone. `_read_step` will see EOF and settle it.
            pass

    def _read_step(self) -> Step | None:
        while True:
            line = self._readline()
            if line is None:
                return None
            try:
                event = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get("event") == "step":
                step = Step(
                    index=int(event.get("index", len(self._steps) + 1)),
                    line=int(event.get("line", 0)),
                    func=str(event.get("func", "")),
                    locals={str(k): str(v)
                            for k, v in (event.get("locals") or {}).items()},
                    error=str(event.get("error", "")),
                )
                self._history.append(step)
                self._steps.append(step)
                self._awaiting = True
                self._release()
                return step
            if event.get("event") == "result":
                self._result = event
                return None

    def _readline(self) -> str | None:
        if "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            return line
        while True:
            try:
                chunk = self._process.stdout.readline()
            except (OSError, ValueError, AttributeError):
                return None
            if not chunk:
                return None
            self._pending += chunk.decode("utf-8", "replace")
            if "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                return line
