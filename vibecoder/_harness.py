"""Sandbox child process. Runs one submission against one set of test cases.

This module is executed as a standalone script by ``runner.py`` -- never
imported by the parent -- so it must depend on nothing but the standard
library and must not import the ``vibecoder`` package. Communication is a
single JSON object on stdin and a single JSON object on stdout.

The reply is newline-delimited JSON. Zero or more ``{"event": "progress"}``
lines are written as each test finishes, then exactly one
``{"event": "result"}`` line carrying the whole run. A parent that does not
care about progress can read to the end and take the last line; one that does
can react as the lines arrive. Progress goes to the *real* stdout, captured at
import, because the submission's own stdout is redirected away from it -- a
submission that prints must not be able to forge an event.

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
import os
import sys
import time
import tracemalloc
from contextlib import redirect_stdout
from typing import Any

#: The genuine stdout, saved before anything redirects it. Every event is
#: written here, so a submission that prints cannot inject one.
REPLY = sys.stdout

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
    limits = [
        (resource.RLIMIT_AS, mem_bytes),
        (resource.RLIMIT_CPU, cpu_seconds),
    ]
    # RLIMIT_NPROC counts processes per real uid, so it is only meaningful
    # when the submission has a uid to itself. The parent decides that -- it
    # is the only side that knows which backend is running -- and says so by
    # sending proc_limit. Absent, no process cap is applied.
    proc_limit = payload.get("proc_limit")
    if proc_limit:
        limits.append((resource.RLIMIT_NPROC, int(proc_limit)))
    for limit, value in limits:
        try:
            soft, hard = resource.getrlimit(limit)
            ceiling = value if hard == resource.RLIM_INFINITY else min(value, hard)
            resource.setrlimit(limit, (ceiling, hard))
        except (ValueError, OSError):
            # A platform that refuses the limit still gets the parent's
            # wall-clock timeout, so this is a soft failure by design.
            pass


def _emit(payload: dict[str, Any], own_pid: int) -> None:
    """Write one event line, unless this process is a fork of the harness.

    A fork inherits the reply stream and would write a second, competing
    object into it. One reply per run is the whole contract with the parent.
    """
    if os.getpid() != own_pid:
        return
    json.dump(payload, REPLY)
    REPLY.write("\n")
    REPLY.flush()


class _Aborted(Exception):
    """The parent asked us to stop. Raised inside the trace hook to unwind."""


def _control(default: str = "step") -> str:
    """Block until the parent says what to do next.

    The child never sleeps and never decides pacing. It runs one line, reports
    it, and waits here -- so "paused" is simply the parent not answering yet,
    and needs no state on this side at all. Variable speed, fast-forward and
    the whole feel of the thing live in the parent, which is where the player
    is.

    EOF means the parent is gone. Continuing to execute at full speed for a
    parent that will never read the result is the one behaviour that is
    certainly wrong, so it reads as an abort.
    """
    line = sys.stdin.readline()
    if not line:
        return "abort"
    try:
        command = json.loads(line)
    except (TypeError, ValueError):
        return default
    return str(command.get("cmd", default))


def _run_stepped(fn, args, kwargs, filename: str, own_pid: int,
                 budget: float) -> tuple[list, str, str]:
    """Execute under ``settrace``, reporting each line and awaiting orders.

    Emits the same ``{line, func, locals}`` shape `_record_trace` produces, so
    the live engine and the recording feed one renderer rather than two. That
    shape is load-bearing in both directions now: `replay` and `vision` already
    read it.

    Two rules that look like details and are not:

    **Every line is reported; only the first `MAX_TRACE_STEPS` are kept.**
    Recording is what has to be bounded, because it is memory the parent will
    be handed. Reporting is what keeps the parent in control -- stopping it at
    the cap would leave a paused parent waiting forever for a line that never
    arrives.

    **The budget counts executing time, never time blocked on the parent.** A
    fight paused while somebody reads it must not time out for being watched
    carefully, and a loop that runs away after ``run`` still must not.
    """
    steps: list[dict[str, Any]] = []
    state = {"free": False, "blocked": 0.0, "reason": ""}
    started = time.perf_counter()

    def local_trace(frame, event, arg):
        if event != "line":
            return local_trace

        record = {
            "line": frame.f_lineno,
            "func": frame.f_code.co_name,
            "locals": {
                k: _short(v)
                for k, v in list(frame.f_locals.items())[:12]
                if not k.startswith("__")
            },
        }
        if len(steps) < MAX_TRACE_STEPS:
            steps.append(record)
        _emit(
            {"event": "step", "index": len(steps), "recorded": len(steps) < MAX_TRACE_STEPS + 1, **record},
            own_pid,
        )

        if not state["free"]:
            waited = time.perf_counter()
            command = _control()
            state["blocked"] += time.perf_counter() - waited
            if command == "abort":
                state["reason"] = "stopped by the player"
                raise _Aborted()
            if command == "run":
                state["free"] = True

        executing = (time.perf_counter() - started) - state["blocked"]
        if executing > budget:
            state["reason"] = f"step budget of {budget:g}s exceeded"
            raise _Aborted()
        return local_trace

    def global_trace(frame, event, arg):
        if frame.f_code.co_filename == filename:
            return local_trace
        return None

    error = ""
    error_type = ""
    sys.settrace(global_trace)
    try:
        fn(*args, **kwargs)
    except _Aborted:
        error_type = "Aborted"
        error = state["reason"] or "stopped"
    except BaseException as exc:  # noqa: BLE001 - a crash is a result to report
        error = f"{type(exc).__name__}: {exc}"
        error_type = type(exc).__name__
    finally:
        sys.settrace(None)
    return steps, error, error_type


def main() -> int:
    # One JSON object on one line, rather than everything up to EOF: stepping
    # keeps stdin open afterwards so the parent can steer, and `json.load`
    # would block waiting for a close that never comes.
    payload = json.loads(sys.stdin.readline() or "{}")
    _apply_limits(payload)
    # Anything this process forks inherits stdout, and would go on to write a
    # second result object into the same stream. One JSON reply per run is the
    # entire contract with the parent, so every descendant has to be silent.
    _own_pid = os.getpid()

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
        _emit({"event": "result", **result}, _own_pid)
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
        _emit({"event": "result", **result}, _own_pid)
        return 0

    fn = namespace.get(func_name)
    if not callable(fn):
        result["error"] = f"no function named {func_name!r} was defined"
        result["error_type"] = "MissingFunction"
        result["stdout"] = captured.getvalue()
        _emit({"event": "result", **result}, _own_pid)
        return 0

    if payload.get("mode") == "step":
        tests = payload["tests"]
        first = tests[0] if tests else {"args": [], "kwargs": {}}
        with redirect_stdout(captured):
            steps, error, error_type = _run_stepped(
                fn, first.get("args", []), first.get("kwargs", {}),
                filename, _own_pid, float(payload.get("timeout", 10.0)),
            )
        result["trace"] = steps
        result["error"] = error
        result["error_type"] = error_type
        result["stdout"] = captured.getvalue()[:4000]
        _emit({"event": "result", **result}, _own_pid)
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
            _emit({
                "event": "progress", "index": index, "total": len(tests),
                "name": outcome["name"], "passed": False,
            }, _own_pid)
            continue
        elapsed += time.perf_counter() - started
        peak_overall = max(peak_overall, tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()

        outcome["got"] = _short(got)
        outcome["passed"] = _equal(got, test.get("expected"))
        result["outcomes"].append(outcome)
        # The parent can draw this before the run is over. Emitted after pass
        # 1 rather than after pass 2, because the instrumented pass roughly
        # doubles the wait and a player watching the screen should not.
        _emit({
            "event": "progress", "index": index, "total": len(tests),
            "name": outcome["name"], "passed": outcome["passed"],
        }, _own_pid)

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
    if os.getpid() != _own_pid:
        # A fork of the harness, still running the tail of this function.
        # Leave without touching the reply stream and without running
        # interpreter shutdown, which would flush buffers the parent is
        # trying to parse.
        os._exit(0)
    _emit({"event": "result", **result}, _own_pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
