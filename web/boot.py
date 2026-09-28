"""Engine-worker bootstrap: the service, wired to the browser's executor.

Runs inside Pyodide in `workers/engine.js`. Everything game-shaped lives in
`vibecoder.service`; this file only adapts it to a worker -- an executor that
asks the page to run the harness, and a dispatcher the page calls with JSON.
"""

import inspect
import json
import os
import sys
import traceback

sys.path.insert(0, "/lib/vibecoder-engine")
os.environ["VIBECODER_HOME"] = "/home/pyodide/.vibecoder"

import js  # noqa: E402  (Pyodide's bridge to the worker's globals)

from vibecoder.sandbox import SandboxUnavailable  # noqa: E402
from vibecoder.service import ExecutionFailed, Service, ServiceError  # noqa: E402


class WorkerExecutor:
    """Runs `_harness.py` in a fresh Pyodide worker the page owns.

    Declared non-isolating (N4, N9): a WebAssembly worker is a good fence
    against a runaway loop and is still not claimed as protection from code
    somebody else wrote. The service refuses third-party source on it.
    """

    isolating = False

    async def run(self, payload, commands=()):
        reply = await js.vcExecute(json.dumps(payload), json.dumps(list(commands)))
        status = str(reply.status)
        if status == "timeout":
            raise TimeoutError()
        if status != "ok":
            raise ExecutionFailed(str(reply.error or "the sandbox stopped"))
        return str(reply.out)


service = Service(WorkerExecutor(), on_save=js.vcPersist)

#: Everything the page may ask for, and nothing else.
METHODS = {
    name: getattr(service, name)
    for name in (
        "hello", "catalogue", "player", "daily",
        "open_level", "run", "finish", "abandon",
        "open_boss", "boss_attempt", "boss_repair", "boss_finish",
        "reset",
    )
}


async def dispatch(method, args_json):
    """One request from the page, one JSON reply. Never raises."""
    handler = METHODS.get(method)
    if handler is None:
        return json.dumps({"ok": False, "error": {
            "code": "no_such_method", "message": str(method)}})
    try:
        value = handler(**json.loads(args_json))
        if inspect.isawaitable(value):
            value = await value
        return json.dumps({"ok": True, "value": value})
    except ServiceError as exc:
        return json.dumps({"ok": False, "error": exc.to_json()})
    except SandboxUnavailable as exc:
        return json.dumps({"ok": False, "error": {
            "code": "sandbox_unavailable", "message": str(exc)}})
    except Exception as exc:  # noqa: BLE001 - reported to the page, not lost
        return json.dumps({"ok": False, "error": {
            "code": "internal",
            "message": f"{type(exc).__name__}: {exc}",
            "trace": traceback.format_exc()[-2000:],
        }})
