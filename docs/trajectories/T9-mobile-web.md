# T9 — Phone and browser play

**Status:** `IN FLIGHT` · **Started:** 2026-09-28 · **Target:** 2026-10-18
**Depends on:** the existing engine; the user's approval of Pyodide for the
browser and Android builds only (D242, [S042](../../journal/2026-09-28-S042-phone-and-browser.md)).

## Heading

Put the real game on a phone and in a browser without re-implementing any of
it. The engine -- levels, scoring, tips, mastery, persistence -- is the same
`vibecoder` package, running under Pyodide (CPython compiled to WebAssembly);
every submission runs the unchanged `_harness.py` in a fresh WebAssembly
worker. The Android app is a WebView over the same files with no network
permission. The Python package stays dependency-free and the CLI unchanged.

T8 (the Tauri desktop client) is **paused, not landed**: its W1 native gate is
blocked on Windows/macOS runners (Q103), and this trajectory started at the
user's request while it waits. Recorded here rather than absorbed.

## Waypoints

| ID | Outcome | State |
| --- | --- | --- |
| W1 | An async use-case layer (`vibecoder.service`) plays levels and bosses with CLI-equivalent rules through an injected executor | landed (S042) |
| W2 | A static browser build runs that engine in Pyodide, executes submissions in a fresh sandbox worker per run, and persists progress locally | landed (S042) |
| W3 | An acid-punk touch-first client: campaign, level editor with a symbol row, scoring, replay, boss fight, stats, settings | landed (S042) |
| W4 | A signed Android APK with no network permission, installable from a GitHub release | landed (S042) |
| W5 | The browser build is served from the user's domain with the headers it needs, and works offline after the first visit | pending: server unreachable from the build host |
| W6 | Human play on a phone: every level cleared by typing, and a boss fought to the end, recorded with observations | pending |

## Exit criteria

1. A level scored in the browser or the app produces the same Accuracy and
   Functional values as the CLI for the same code, seed and interpreter, and
   Speed from the same clock rule (open to first passing run).
2. Every submission runs in an interpreter no other submission has touched, and
   a non-terminating submission is stopped by the page within its time budget
   plus a fixed grace, on a real device.
3. Third-party source is refused by the browser engine exactly as by a
   non-isolating host backend (N9).
4. The APK requests no network permission and loads nothing from outside its
   own assets; the hosted build loads nothing from outside its own origin.
5. Progress survives closing the app, and a finish or a daily cannot be banked
   twice by repeating the request.
6. The Python package gains no runtime dependency, and both original gates stay
   green under the baseline interpreter.
7. A person plays the phone build through a level and a boss fight on the
   keyboard of a real device, and what they found is recorded.

## Known hazards

- Pyodide's CPython is not the baseline interpreter, so absolute op counts
  differ from `data/baselines/`. Functional compares against a reference
  measured in the *same* interpreter, which is what keeps the axis honest; no
  baseline may be re-recorded from a browser.
- A WebView's edge-to-edge window and the soft keyboard: from target SDK 35 the
  app must pad for the IME itself, or the symbol row sits under the keyboard.
- `<pre>` defaults to the platform `monospace`, whose block glyphs are not
  0.6em on Android; any character grid must use the bundled font (M63).
- The hosted site sends its own CSP; WebAssembly needs `'wasm-unsafe-eval'` on
  the game's path and nowhere else.
- Boss fights are scored but not banked (Q84); the phone must not imply otherwise.

## Instrument checks

Engine boot, reference benchmark and warm submission latency on the phone
(`tools/android/device_smoke.py`), and the same in headless Chromium
(`tools/web/smoke.py`). APK size and signature (`apksigner verify`). The
headers actually served by the host, fetched with `curl -I`, not read off a
config file.
