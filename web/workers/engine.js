// The engine: the real `vibecoder` package, running in Pyodide in a worker.
//
// Game rules, scoring, test generation, persistence and tips are all Python,
// imported from the same sources the test suite runs (`py/vibecoder.zip` is
// zipped from the package at build time). This worker never executes a
// submission: it asks the page to, and the page runs each one in a fresh
// sandbox worker. Scores are therefore computed by `scoring.py`, against a
// reference measured in the same interpreter build, never re-implemented in
// JavaScript (ADR-001: "do not substitute ... a JavaScript interpreter").

import { loadPyodide } from "../vendor/pyodide/pyodide.mjs";

// The player's profile lives here, backed by IndexedDB: `Session` writes
// `profile.json` exactly as it does on a desktop, and a save is flushed to
// the browser's storage straight after.
const HOME = "/home/pyodide/.vibecoder";

let py = null;
let dispatch = null;
let sequence = 0;
const executing = new Map();
let flushing = Promise.resolve();

function status(text) {
  postMessage({ type: "status", text });
}

// Called from Python (`boot.py`) with a JSON payload and JSON commands; the
// page answers with {status, out, error}.
self.vcExecute = (payload, commands) =>
  new Promise((resolve) => {
    const id = ++sequence;
    executing.set(id, resolve);
    postMessage({ type: "exec", id, payload, commands: JSON.parse(commands) });
  });

// Called from Python after every save. Serialised, because two overlapping
// syncs of one mount race each other.
self.vcPersist = () => {
  flushing = flushing.then(
    () =>
      new Promise((resolve) => {
        py.FS.syncfs(false, (error) => {
          if (error) postMessage({ type: "warn", text: `could not save progress: ${error}` });
          resolve();
        });
      }),
  );
};

async function boot() {
  status("loading python runtime");
  py = await loadPyodide({ indexURL: new URL("../vendor/pyodide/", import.meta.url).href });

  status("mounting save file");
  py.FS.mkdirTree(HOME);
  py.FS.mount(py.FS.filesystems.IDBFS, {}, HOME);
  await new Promise((resolve, reject) =>
    py.FS.syncfs(true, (error) => (error ? reject(error) : resolve())),
  );

  status("unpacking engine");
  const archive = await fetch(new URL("../py/vibecoder.zip", import.meta.url));
  py.unpackArchive(await archive.arrayBuffer(), "zip", { extractDir: "/lib/vibecoder-engine" });
  const bootstrap = await fetch(new URL("../boot.py", import.meta.url));

  status("waking the engine");
  await py.runPythonAsync(await bootstrap.text());
  dispatch = py.globals.get("dispatch");
}

const ready = boot();
ready.then(
  () => postMessage({ type: "ready" }),
  (error) => postMessage({ type: "fatal", error: String((error && error.message) || error) }),
);

self.onmessage = async ({ data }) => {
  if (data.type === "result") {
    const resolve = executing.get(data.id);
    executing.delete(data.id);
    if (resolve) resolve(data.result);
    return;
  }
  if (data.type !== "call") return;
  try {
    await ready;
  } catch (error) {
    postMessage({ type: "reply", id: data.id, ok: false,
                  error: { code: "boot", message: String(error) } });
    return;
  }
  const text = await dispatch(data.method, JSON.stringify(data.args || {}));
  postMessage({ type: "reply", id: data.id, ...JSON.parse(text) });
};
