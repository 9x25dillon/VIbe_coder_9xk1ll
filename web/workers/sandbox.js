// One submission, one interpreter.
//
// The desktop runs every submission in a fresh child process; this worker is
// the same promise in a browser: a fresh Pyodide per run, thrown away after.
// It executes `_harness.py` unchanged, as a script, without importing the
// game package (N2). The page kills the worker on a wall-clock deadline, which
// is the browser's equivalent of the host watchdog: a `while True` blocks this
// thread for good, and nothing inside it could ever notice.
//
// An isolation boundary against the player's own runaway loop -- not a
// security boundary (N4). Third-party code never reaches it: the engine
// refuses that before a payload is built.

import { loadPyodide } from "../vendor/pyodide/pyodide.mjs";

// Stepped runs report every line so that a paused parent is never left
// waiting. Nobody is paused here, so beyond this many the lines are counted
// and dropped rather than shipped to a renderer that could never show them.
const STEP_CAP = 2000;

const booting = (async () => {
  const py = await loadPyodide({
    indexURL: new URL("../vendor/pyodide/", import.meta.url).href,
  });
  const response = await fetch(new URL("../py/_harness.py", import.meta.url));
  py.FS.writeFile("/tmp/_harness.py", await response.text());
  return py;
})();

booting.then(
  () => postMessage({ type: "ready" }),
  (error) => postMessage({ type: "crash", error: `sandbox failed to start: ${error}` }),
);

self.onmessage = async ({ data }) => {
  const py = await booting;
  // Byte-level stdin: the line-based callback hands Python 8 KB at a time
  // and truncates a large payload mid-string.
  const input = new TextEncoder().encode([data.payload, ...data.commands].join("\n") + "\n");
  let at = 0;
  py.setStdin({
    read(buffer) {
      const count = Math.min(buffer.length, input.length - at);
      buffer.set(input.subarray(at, at + count));
      at += count;
      return count;
    },
  });

  const kept = [];
  const stderr = [];
  let steps = 0;
  py.setStdout({
    batched(line) {
      if (line.startsWith('{"event": "step"')) {
        steps += 1;
        if (steps > STEP_CAP) return;
      } else if (line.startsWith('{"event": "progress"')) {
        postMessage({ type: "progress", line });
      }
      kept.push(line);
    },
  });
  py.setStderr({
    batched(line) {
      stderr.push(line);
      if (stderr.length > 40) stderr.shift();
    },
  });

  try {
    py.runPython(
      "import runpy\n" +
      "try:\n" +
      "    runpy.run_path('/tmp/_harness.py', run_name='__main__')\n" +
      "except SystemExit:\n" +
      "    pass\n",
    );
    postMessage({ type: "done", out: kept.join("\n"), steps });
  } catch (error) {
    const text = String((error && error.message) || error).trim().split("\n");
    postMessage({
      type: "crash",
      error: text[text.length - 1] || "the sandbox stopped",
      stderr: stderr.join("\n"),
    });
  }
};
