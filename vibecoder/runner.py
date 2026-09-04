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
import subprocess
from pathlib import Path
from typing import Sequence

from . import sandbox
from .models import Level, RunResult, Source, TestCase, TestOutcome

HARNESS = Path(__file__).with_name("_harness.py")

DEFAULT_TIMEOUT = 10.0
DEFAULT_MEM_LIMIT_MB = 512
#: Processes a submission may own, when it owns a uid of its own. Generous for
#: anything a level needs, ruinous for a fork bomb.
PROC_LIMIT = 64

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
) -> RunResult:
    """Execute ``code`` against ``tests`` in a sandboxed child process.

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
            completed = subprocess.run(
                launch.argv,
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=timeout,
                pass_fds=launch.pass_fds,
            )
    except subprocess.TimeoutExpired:
        return RunResult(
            error=f"execution exceeded {timeout:g}s - check for an infinite loop",
            error_type="Timeout",
        )

    if completed.returncode != 0 or not completed.stdout.strip():
        detail = (completed.stderr or "").strip().splitlines()
        tail = detail[-1] if detail else f"exit code {completed.returncode}"
        label = "sandbox" if backend.name == "subprocess" else f"{backend.name} sandbox"
        return RunResult(error=f"{label} crashed: {tail}", error_type="SandboxCrash")

    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
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


def run_submission(
    level: Level,
    code: str,
    tests: Sequence[TestCase],
    *,
    record_trace: bool = False,
    source: Source = Source.PLAYER,
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
