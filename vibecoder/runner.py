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
from pathlib import Path
from typing import Callable, Sequence

from . import sandbox
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

    return RunResult(
        outcomes=[TestOutcome(**o) for o in raw["outcomes"]],
        wall_seconds=raw["wall_seconds"],
        ops=raw["ops"],
        peak_bytes=raw["peak_bytes"],
        stdout=raw["stdout"],
        error=raw["error"],
        error_type=raw["error_type"],
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
