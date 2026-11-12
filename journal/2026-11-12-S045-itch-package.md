# S045 — The browser build, packaged for itch.io

**Date:** 2026-11-12 · **Duration:** not tracked · **Trajectory:** T9 ·
**Competency band:** `Apply` ·
**Data:** [data twin](../data/sessions/2026-11-12-S045.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | One command produces a zip itch.io accepts as an HTML5 upload, with every documented limit checked before it is written | met |
| 2 | Nothing in the package depends on a header itch.io's CDN may not send | partial |
| 3 | The game still boots in a frame that is refused IndexedDB | partial |

Objectives 2 and 3 are partial because no browser was available in this
session: the packaged engine was loaded in Node, not in itch's iframe.

## What was built

[`tools/itch/package.py`](../tools/itch/package.py) copies a web build, adapts
the copy and zips it deterministically to `dist/vibecoder-itch-<version>.zip`.
The adaptations answer the three ways itch.io differs from a host we run
(table in [`docs/WEB.md`](../docs/WEB.md#itchio)): Pyodide's `.mjs` files ship
as `.js` because we cannot choose the type itch sends for `.mjs`; `sw.js` is
left out of an embed; `build-info.json` is rewritten to list what ships, with
`"target": "itch.io"`. Each string rewrite asserts an exact count, so a Pyodide
upgrade that moves a name fails the packager instead of an upload.

[`web/workers/engine.js`](../web/workers/engine.js) gained `mountSaves`: if
IndexedDB is refused (a third-party frame in a browser that blocks third-party
cookies), the engine keeps the profile in memory, warns once, and boots. Before
this, a refused mount rejected `boot()` and the game showed a fatal error. The
change affects every client only on that failure path.

[`tools/itch/cover.png`](../tools/itch/cover.png) is the 630 × 500 store cover,
drawn from the logo in `web/js/ascii.js`, the CSS palette and the bundled fonts.

[`tests/test_itch.py`](../tests/test_itch.py) runs the packager over a
miniature build with the same strings, since the real build downloads Pyodide
and the suite never touches the network. Half its tests are refusals.

## Evidence

```
$ python3.11 tools/itch/package.py
wrote dist/vibecoder-itch-0.2.0.zip -- engine 0.2.0, 32 files, 6.9 MB zipped
$ python3.11 tools/itch/package.py --from build/web; sha256sum dist/*.zip   # twice
4ee2eccb...  (identical both times)
$ node nodecheck.mjs <unzipped package>    # loadPyodide from vendor/pyodide/pyodide.js
python 3.14.2
engine 0.2.0 imported
$ python3.11 -m unittest tests.test_itch
Ran 15 tests ... OK
$ python3.11 -m unittest discover -s tests   # this container: no bwrap, no Docker
Ran 1478 tests ... FAILED (failures=3, errors=1, skipped=33)
$ python3.11 -m vibecoder.cli verify --seeds 3
54/54 reference runs clean
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| The zip has index.html at its root, 32 files, no `.mjs`, no `sw.js` | `unzip -l` of the package | verified |
| The renamed loader finds `pyodide.asm.js` and the engine imports | Node 22 loaded the unzipped package's `pyodide.js` and imported `vibecoder.service` | verified |
| Every file is reachable under a subdirectory | served the unzipped package at `/html/12345/` with `http.server`; all 32 answered 200, every `.js` as JavaScript | verified |
| The four suite failures are this host, not this change | all four are present on `main` before any edit: one needs an isolating sandbox, three are the count check, which discovers fewer escape tests without one | verified |
| The game runs inside itch.io's iframe | no browser in this session | `UNVERIFIED` |
| The memory fallback boots when IndexedDB is refused | only the source is checked (`test_the_engine_boots_without_storage`); no browser exercised the path | `UNVERIFIED` |

## Misconceptions and corrections

### M68 — Pyodide names one file, not two

**Believed:** renaming `pyodide.asm.mjs` meant rewriting the loader's one
reference to it.
**Revealed by:** a search of both files for `.mjs`: `pyodide.asm.mjs` names
itself in its stack-frame filter, which hides the interpreter's own frames from
a player's traceback by file name.
**Corrected to:** both strings are rewritten, each with an exact count.
**Cost:** none; caught before the first package.

## Friction

No Chromium in the container, so `smoke.py` could not run against the package.
Node stood in for the loader check only.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D252 | Ship Pyodide's `.mjs` files as `.js` in the itch.io package | Trust itch's CDN to type `.mjs`; ask itch support | Nothing documents the type; `.js` is typed correctly by every host, and the rewrite is checked | yes |
| D253 | Leave the offline worker out of the itch.io package | Ship it; patch `app.js` not to register when framed | Offline play is not a feature of an embed; leaving the file out changes no shared code | yes |
| D254 | A refused IndexedDB costs the save, not the game | Keep the fatal error; detect itch specifically | A playable game without saves beats an error screen, on any host | yes |

## Handoff

- **State:** `tools/itch/package.py` builds an itch.io zip of 0.2.0; not yet uploaded or played on itch.io.
- **Next action:** the user uploads the zip to an itch.io draft and plays one level in the preview; record what happens.
- **Blockers:** none.
- **Context required:** [`docs/WEB.md`](../docs/WEB.md#itchio), this entry.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q109 | What type does itch.io's CDN send for `.mjs`? If JavaScript, D252 can be dropped. | T9 | open |
