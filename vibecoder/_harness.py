"""Sandbox child process. Runs one submission against one set of test cases.

This module is executed as a standalone script by ``runner.py`` -- never
imported by the parent -- so it must depend on nothing but the standard
library and must not import the ``vibecoder`` package. Communication is a
single JSON object on stdin and a single JSON object on stdout.

SECURITY NOTE: this is an *isolation* boundary, not a *security* boundary. It
protects the game from runaway loops and memory hogs in code the player wrote
themselves on their own machine. It does not protect against hostile code, and
must not be used to execute submissions from other players. Phase 1 replaces it
with a container-backed runner (see docs/trajectories/T2-sandbox.md).
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
import tracemalloc
from contextlib import redirect_stdout
from typing import Any

USER_FILENAME = "<vibecoder-submission>"
MAX_TRACE_STEPS = 400
MAX_REPR = 120


# --------------------------------------------------------------------------
# Result comparison
# --------------------------------------------------------------------------

def _normalise(value: Any) -> Any:
    """Make a value comparable across the JSON round-trip.

    Tuples become lists because JSON has no tuple, and sets become sorted lists
    because JSON has no set and iteration order is not meaningful.
    """
    if isinstance(value, tuple) or isinstance(value, list):
        return [_normalise(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_normalise(v) for v in value)
    if isinstance(value, dict):
        return {str(k): _normalise(v) for k, v in value.items()}
    return value


def _equal(got: Any, expected: Any) -> bool:
    got, expected = _normalise(got), _normalise(expected)
    if isinstance(got, float) or isinstance(expected, float):
        if isinstance(got, (int, float)) and isinstance(expected, (int, float)):
            return math.isclose(got, expected, rel_tol=1e-9, abs_tol=1e-9)
        return False
    if isinstance(got, list) and isinstance(expected, list):
        return len(got) == len(expected) and all(
            _equal(a, b) for a, b in zip(got, expected)
        )
    if isinstance(got, dict) and isinstance(expected, dict):
        return got.keys() == expected.keys() and all(
            _equal(got[k], expected[k]) for k in got
        )
    return got == expected


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= MAX_REPR else text[: MAX_REPR - 3] + "..."


# --------------------------------------------------------------------------
# Instrumentation
# --------------------------------------------------------------------------

def _count_ops(fn, args, kwargs, filename: str) -> int:
    """Count line executions occurring inside the submitted code.

    Only frames whose filename matches the compiled submission are traced, so
    time spent inside ``sorted`` or ``sum`` costs one op rather than many. That
    is intentional: it makes the functional axis reward built-ins and library
    calls over hand-rolled loops, which is the behaviour the game wants to
    teach.
    """
    count = 0

    def local_trace(frame, event, arg):
        nonlocal count
        if event == "line":
            count += 1
        return local_trace

    def global_trace(frame, event, arg):
        if frame.f_code.co_filename == filename:
            return local_trace
        return None

    sys.settrace(global_trace)
    try:
        fn(*args, **kwargs)
    finally:
        sys.settrace(None)
    return count


def _record_trace(fn, args, kwargs, filename: str) -> list[dict[str, Any]]:
    """Capture a line-by-line execution trace for slow-motion replay.

    Locals are snapshotted as short reprs rather than references, so the replay
    shows the value at that instant instead of the final value of a mutated
    object.
    """
    steps: list[dict[str, Any]] = []

    def local_trace(frame, event, arg):
        if event == "line" and len(steps) < MAX_TRACE_STEPS:
            steps.append(
                {
                    "line": frame.f_lineno,
                    "func": frame.f_code.co_name,
                    "locals": {
                        k: _short(v)
                        for k, v in list(frame.f_locals.items())[:12]
                        if not k.startswith("__")
                    },
                }
            )
        return local_trace

    def global_trace(frame, event, arg):
        if frame.f_code.co_filename == filename:
            return local_trace
        return None

    sys.settrace(global_trace)
    try:
        fn(*args, **kwargs)
    except Exception:
        pass
    finally:
        sys.settrace(None)
    return steps


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def _apply_limits(payload: dict[str, Any]) -> None:
    try:
        import resource
    except ImportError:  # Windows
        return
    mem_bytes = int(payload.get("mem_limit_mb", 512)) * 1024 * 1024
    cpu_seconds = int(payload.get("timeout", 10)) + 1
    for limit, value in (
        (resource.RLIMIT_AS, mem_bytes),
        (resource.RLIMIT_CPU, cpu_seconds),
    ):
        try:
            soft, hard = resource.getrlimit(limit)
            ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(limit, (ceiling, hard))
        except (ValueError, OSError):
            # A platform that refuses the limit still gets the parent's
            # wall-clock timeout, so this is a soft failure by design.
            pass


def main() -> int:
    payload = json.load(sys.stdin)
    _apply_limits(payload)

    result: dict[str, Any] = {
        "outcomes": [],
        "wall_seconds": 0.0,
        "ops": 0,
        "peak_bytes": 0,
        "stdout": "",
        "error": "",
        "error_type": "",
        "trace": [],
    }

    source = payload["code"]
    func_name = payload["func_name"]
    filename = payload.get("filename", USER_FILENAME)

    try:
        compiled = compile(source, filename, "exec")
    except SyntaxError as exc:
        result["error"] = f"{exc.msg} (line {exc.lineno})"
        result["error_type"] = "SyntaxError"
        json.dump(result, sys.stdout)
        return 0

    namespace: dict[str, Any] = {"__name__": "__vibecoder__"}
    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            exec(compiled, namespace)
    except BaseException as exc:  # noqa: BLE001 - report anything module-level
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["error_type"] = "ImportTimeError"
        result["stdout"] = captured.getvalue()
        json.dump(result, sys.stdout)
        return 0

    fn = namespace.get(func_name)
    if not callable(fn):
        result["error"] = f"no function named {func_name!r} was defined"
        result["error_type"] = "MissingFunction"
        result["stdout"] = captured.getvalue()
        json.dump(result, sys.stdout)
        return 0

    tests = payload["tests"]
    total_ops = 0
    peak_overall = 0
    elapsed = 0.0

    for index, test in enumerate(tests):
        args = test.get("args", [])
        kwargs = test.get("kwargs", {})
        outcome = {
            "name": test.get("name", f"test_{index}"),
            "passed": False,
            "got": "",
            "expected": _short(test.get("expected")),
            "error": "",
        }

        # Pass 1: untraced, for honest wall time and memory.
        tracemalloc.start()
        started = time.perf_counter()
        try:
            with redirect_stdout(captured):
                got = fn(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - a crash is a failed test
            elapsed += time.perf_counter() - started
            tracemalloc.stop()
            outcome["error"] = f"{type(exc).__name__}: {exc}"
            result["outcomes"].append(outcome)
            continue
        elapsed += time.perf_counter() - started
        peak_overall = max(peak_overall, tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()

        outcome["got"] = _short(got)
        outcome["passed"] = _equal(got, test.get("expected"))
        result["outcomes"].append(outcome)

        # Pass 2: traced, for the op count. Tracing roughly doubles runtime,
        # which is why timing is taken from the untraced pass above.
        try:
            with redirect_stdout(captured):
                total_ops += _count_ops(fn, args, kwargs, filename)
        except BaseException:  # noqa: BLE001 - already reported by pass 1
            pass

    if payload.get("record_trace") and tests:
        first = tests[0]
        with redirect_stdout(captured):
            result["trace"] = _record_trace(
                fn, first.get("args", []), first.get("kwargs", {}), filename
            )

    result["wall_seconds"] = round(elapsed, 6)
    result["ops"] = total_ops
    result["peak_bytes"] = peak_overall
    result["stdout"] = captured.getvalue()[:4000]
    json.dump(result, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
