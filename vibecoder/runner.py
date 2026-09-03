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
from .models import Level, RunResult, TestCase, TestOutcome

HARNESS = Path(__file__).with_name("_harness.py")

DEFAULT_TIMEOUT = 10.0
DEFAULT_MEM_LIMIT_MB = 512

SUBMISSION_FILENAME = "<vibecoder-submission>"
REFERENCE_FILENAME = "<vibecoder-reference>"


def run_code(
    code: str,
    func_name: str,
    tests: Sequence[TestCase],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    mem_limit_mb: int = DEFAULT_MEM_LIMIT_MB,
    record_trace: bool = False,
    filename: str = SUBMISSION_FILENAME,
    untrusted: bool = False,
) -> RunResult:
    """Execute ``code`` against ``tests`` in a sandboxed child process.

    ``untrusted`` marks code that did not come from the player at this
    keyboard -- a community level, a daily challenge. It forces an isolating
    backend and fails loudly when none is available, because the alternative
    is running a stranger's Python on the host with rlimits for a fence.
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

    backend = sandbox.select(untrusted=untrusted)
    argv = backend.command(HARNESS, mem_limit_mb=mem_limit_mb)

    try:
        completed = subprocess.run(
            argv,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=timeout,
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
) -> RunResult:
    return run_code(
        code,
        level.func_name,
        tests,
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
    result = run_code(
        level.reference,
        level.func_name,
        tests,
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
