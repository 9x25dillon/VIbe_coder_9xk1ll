// The page's side of the engine: an RPC client for the engine worker, and
// the pool of sandbox workers that actually run code.

export class EngineError extends Error {
  constructor({ code, message, trace }) {
    super(message);
    this.code = code;
    this.trace = trace || "";
  }
}

// A fresh interpreter per run is the rule; booting one takes a second or two
// on a phone. So spares are started ahead of need, and a run takes one that is
// already warm while a replacement boots behind it.
export class SandboxPool {
  constructor(size, { onBoot } = {}) {
    this.size = size;
    this.spares = [];
    this.onBoot = onBoot || (() => {});
    this.booted = 0;
    this.fill();
  }

  spawn() {
    const worker = new Worker(new URL("../workers/sandbox.js", import.meta.url), { type: "module" });
    const slot = { worker, messages: [] };
    slot.ready = new Promise((resolve, reject) => {
      worker.onmessage = ({ data }) => {
        if (data.type === "ready") {
          this.booted += 1;
          this.onBoot(this.booted);
          resolve();
        } else if (data.type === "crash") reject(new Error(data.error));
      };
      worker.onerror = (event) => reject(new Error(event.message || "sandbox failed to start"));
    });
    slot.ready.catch(() => {});
    return slot;
  }

  fill() {
    while (this.spares.length < this.size) this.spares.push(this.spawn());
  }

  warm() {
    return Promise.allSettled(this.spares.map((slot) => slot.ready));
  }

  // Resolves {status: "ok"|"timeout"|"crash", out, error}. Never rejects:
  // every way a run can end is an answer the engine interprets.
  async run(payload, commands, { onProgress } = {}) {
    const slot = this.spares.shift() || this.spawn();
    this.fill();
    const seconds = JSON.parse(payload).timeout || 10;
    try {
      await withTimeout(slot.ready, 120000, "the sandbox took too long to start");
    } catch (error) {
      slot.worker.terminate();
      return { status: "crash", error: String(error.message || error) };
    }
    return new Promise((resolve) => {
      let settled = false;
      const finish = (result) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        slot.worker.terminate();
        resolve(result);
      };
      // The wall clock the harness cannot see: its own budget counts only
      // executing time, and a loop that never traces never checks it.
      const timer = setTimeout(() => finish({ status: "timeout" }), (seconds + 2) * 1000);
      slot.worker.onmessage = ({ data }) => {
        if (data.type === "progress") {
          if (onProgress) {
            try { onProgress(JSON.parse(data.line)); } catch { /* malformed: ignore */ }
          }
        } else if (data.type === "done") finish({ status: "ok", out: data.out });
        else if (data.type === "crash") finish({ status: "crash", error: data.error });
      };
      slot.worker.onerror = (event) => {
        event.preventDefault();
        finish({ status: "crash", error: event.message || "the sandbox stopped" });
      };
      slot.worker.postMessage({ payload, commands: commands.map((c) => JSON.stringify(c)) });
    });
  }
}

function withTimeout(promise, ms, message) {
  let timer;
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); }),
  ]);
}

export class Engine {
  constructor({ onStatus, onWarn, poolSize = 2 } = {}) {
    this.onStatus = onStatus || (() => {});
    this.onWarn = onWarn || (() => {});
    this.onProgress = null;
    this.calls = new Map();
    this.sequence = 0;
    this.pool = new SandboxPool(poolSize);
    this.worker = new Worker(new URL("../workers/engine.js", import.meta.url), { type: "module" });
    this.ready = new Promise((resolve, reject) => {
      this.worker.onmessage = ({ data }) => this.receive(data, resolve, reject);
      this.worker.onerror = (event) => reject(new Error(event.message || "engine failed to start"));
    });
  }

  receive(data, resolve, reject) {
    switch (data.type) {
      case "status": this.onStatus(data.text); break;
      case "warn": this.onWarn(data.text); break;
      case "ready": resolve(); break;
      case "fatal": reject(new Error(data.error)); break;
      case "exec":
        this.pool
          .run(data.payload, data.commands, { onProgress: (event) => this.onProgress && this.onProgress(event) })
          .then((result) => this.worker.postMessage({ type: "result", id: data.id, result }));
        break;
      case "reply": {
        const pending = this.calls.get(data.id);
        this.calls.delete(data.id);
        if (!pending) break;
        if (data.ok) pending.resolve(data.value);
        else pending.reject(new EngineError(data.error));
        break;
      }
      default: break;
    }
  }

  call(method, args = {}) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.calls.set(id, { resolve, reject });
      this.worker.postMessage({ type: "call", id, method, args });
    });
  }
}
