# S042 — Phone and browser: the real engine, in WebAssembly

**Date:** 2026-09-28 · **Duration:** not tracked · **Trajectory:** T9 ·
**Competency band:** `Create` ·
**Data:** [data twin](../data/sessions/2026-09-28-S042.json)

## Objectives

| # | Objective | Result |
| --- | --- | --- |
| 1 | A level and a boss fight can be played through an async use-case layer, with CLI-equivalent scoring, by a client that owns no terminal | met |
| 2 | The unmodified `vibecoder` package and `_harness.py` run in a browser, one fresh interpreter per submission, and a runaway loop is stopped | met |
| 3 | A signed Android APK with no network permission runs the game on a real phone, keyboard included | met |
| 4 | The Python package is releasable to PyPI with no new dependency | met |
| 5 | The browser build is served from astra-arcana.com/vibecoder/ | missed |
| 6 | A person plays the phone build end to end | deferred |

## What was built

The user asked for a phone app, a web UI in an acid-punk ASCII style, the
desktop CLI, and releases of each. The request did not map to T8's waypoint
(which is waiting on Windows/macOS runners anyway), so T9 was opened and T8
recorded as paused rather than slipped silently.

**The one decision everything else rests on (D242):** the phone runs the real
engine. Pyodide is CPython compiled to WebAssembly, and it imports every module
in the package unchanged — probed first, before anything was designed around
it. The user approved bundling it in the browser and Android builds as the
single exception to N1; the Python package still has no dependency.

- [`vibecoder/service.py`](../vibecoder/service.py) — the game as async use
  cases: open/run/finish a level, attempt/repair/finish a fight, catalogue,
  player sheet, daily, reset. It owns seed, difficulty, attempt count, first-run
  state, the clock and persistence, and follows `cmd_play`'s banking rules. Code
  execution is an injected `Executor`; `Source` has no default on the service's
  `_execute` either (N9), and third-party code is refused on a non-isolating
  executor.
- [`vibecoder/runner.py`](../vibecoder/runner.py) — `build_payload` and
  `parse_reply` split out of `run_code` (signature unchanged) so every
  transport sends the same payload and reads the reply the same way.
  `LiveRun` now builds its payload through the same function.
- [`vibecoder/models.py`](../vibecoder/models.py) — `BossStep.with_stub`, the
  "grow the file as the fight grows" rule, moved out of `cli.py` so the
  terminal and browser fights cannot diverge on it.
- [`web/`](../web/) — the client, with no framework, build step or CDN. An engine
  worker runs Pyodide + the package + `boot.py`; the page runs each submission
  in a fresh sandbox worker and kills it at the payload's timeout plus two
  seconds. Progress is the ordinary `profile.json` on an IndexedDB-backed
  filesystem. Screens: boot log, campaign with daily and world panels, briefing,
  editor (textarea + highlighted mirror, auto-indent, a symbol row for phone
  keyboards), result sheet with first failure and hints, score card with the
  three axes as text meters, trace replay, boss fight (ASCII boss, HP, repair
  pips, the watched run replayed at the CLI's pace with the repair pane on a
  raise), stats, settings.
- [`android/`](../android/) — one Java activity serving the build from APK
  assets on `https://appassets.androidplatform.net/`, same CSP, **no INTERNET
  permission**, `allowBackup="false"`, edge-to-edge insets padded by hand so the
  symbol row sits on the keyboard, and the back key routed through the page.
- [`tools/web/`](../tools/web/) — `build.py` (pinned, hash-checked Pyodide and
  fonts; engine zipped from the package; reproducible), `serve.py` (the headers
  in one place), `smoke.py` (a stdlib WebDriver client: engine checks and a
  screenshot tour, optionally under a subpath), `deploy.py`, `icon.py` (one
  16×16 pixel map → SVG, PNGs and the Android adaptive icon).
- [`tools/android/`](../tools/android/) — `build_apk.py` (aapt2 → javac → d8 →
  zipalign → apksigner, no Gradle; release key created once in
  `~/.config/vibecoder/`), `device_smoke.py` (a stdlib DevTools client that runs
  the engine checks inside the phone's WebView).
- Tests: [`test_service.py`](../tests/test_service.py) (31, real subprocess
  executor, bad solutions included) and [`test_web.py`](../tests/test_web.py)
  (19: one CSP in three places, no external URL, no network permission, every
  page call exposed and nothing private, reproducible engine archive, icon).
- Docs: [`docs/WEB.md`](../docs/WEB.md), [T9](../docs/trajectories/T9-mobile-web.md),
  the flight board, README, ARCHITECTURE, GLOSSARY, CLAUDE.md (N1 exception,
  commands, the service rule). Version 0.1.0 → 0.2.0.

The boss fight is the one place the browser differs in mechanism (D244): each
step runs free and the page replays the recorded lines, because a worker
cannot block on the page for its next command without cross-origin isolation.
What the player sees and is scored on is preserved — the pause lands on the
line that raised, a repair re-runs against the same input and is checked
against the watched prefix (strategy A), the heal is priced on the code as it
failed, and the replay's animation is reported back and taken off Speed.

## Evidence

```
$ VIBECODER_SANDBOX=bwrap python3.11 -m unittest tests.test_service
Ran 31 tests  OK
$ python3.11 -m unittest tests.test_web
Ran 19 tests  OK
$ python3.11 -m unittest discover -s tests           # unpinned, before this entry existed
Ran 1487 tests in 89.685s  FAILED (failures=1)       # the flight board's link to this file
$ python3.11 -m vibecoder.cli verify --seeds 3
54/54 reference runs clean
$ python3.11 tools/web/smoke.py                       # headless Chromium, production CSP
boot 3617 ms, open 164 ms, run 170 ms; w2-l3-join 5/5, 120.0, ops 1364 = ref 1364;
while True -> Timeout; boss starter -> wrong (9 events)        SMOKE OK
$ python3.11 tools/web/smoke.py --prefix vibecoder     SMOKE OK
$ python3.11 tools/android/device_smoke.py              # Pixel 10a, Android 17, WebView 153
boot 4368 ms (alongside the app's own engine), open 143 ms, run 153 ms,
hang stopped at 12007 ms, ops 1364 = ref 1364              DEVICE SMOKE OK
$ apksigner verify --print-certs dist/vibecoder-0.2.0.apk
v2: true, v3: true; CN=VibeCoder, O=Astra Arcana; SHA-256 502ebc8f1deeb7a1…a0d48
$ aapt2 dump badging dist/vibecoder-0.2.0.apk
com.astraarcana.vibecoder 0.2.0 (200), target 36; uses-permission: VIBRATE only
$ twine check dist/vibecoder-0.2.0-py3-none-any.whl dist/vibecoder-0.2.0.tar.gz
PASSED PASSED
$ <clean venv>/bin/vibecoder play w1-l1-greet --solution ref.py
8/8 passed, TOTAL 120.0 (practice)
$ ssh -i ~/.ssh/astra_hetzner root@178.104.120.219
connect to host 178.104.120.219 port 22: Connection timed out
```

| Claim | Evidence | Verdict |
| --- | --- | --- |
| The browser engine scores the same code the same way as the CLI path | `test_a_reference_solve_scores_like_the_cli` (ops equal to `runner.run_submission`, score equal to `score_submission` on the measured values); browser and phone both report ops 1364 = reference 1364 for w2-l3-join seed 1 | verified |
| A bad solution is penalised on Functional, not only rewarded when good (M1) | `test_a_naive_solution_is_correct_and_costs_functional`: accuracy 100, functional < 60 | verified |
| A runaway submission is stopped on a real phone | device smoke: `while True` returned `Timeout` at 12.0 s | verified |
| Finish, daily and reset cannot double-bank | `test_finish_banks_exactly_once`, `test_a_daily_is_served_fixed_and_ranked_once`, `test_reset_removes_progress_and_saved_code` | verified |
| Third-party code is refused on the browser executor | `test_third_party_code_is_refused_without_isolation`; `test_execute_has_no_default_source` | verified |
| The APK cannot reach the network | `aapt2 dump badging`: VIBRATE is the only permission; `test_the_app_cannot_open_a_socket` | verified |
| The page loads nothing from another origin | `test_the_client_references_no_external_url`, one CSP asserted in three places | verified |
| The phone keyboard does not cover the editor's controls | on-device: key row bottom 435 px < 498 px visible height with Gboard up; `(` inserted a pair, Enter auto-indented, focus kept | verified |
| Progress survives the app being killed | on-device: score 132 still shown after `am force-stop` and relaunch | verified |
| The browser build is served from astra-arcana.com/vibecoder/ | server unreachable from the build host on every port | `UNVERIFIED` |
| A person has played the phone build through | only automated taps and screenshots so far | `UNVERIFIED` |
| Firefox, Safari and iOS work | only Chromium and Android WebView were run | `UNVERIFIED` |

## Misconceptions and corrections

### M62 — A skip guarding an M1 test is harmless

**Believed:** guarding the naive-solution test with `skipTest` if the fixture
stopped passing would only ever fire if the level's contract changed later.
**Revealed by:** it fired on its first run. The fixture returned `{**e, 'name':
...}` where the level wants `{'name', 'action'}`, so the one test written
because of M1 was reported as a skip, not a failure — and a skip is green.
**Corrected to:** the fixture matches the level and the test asserts. **Cost:**
one run; it would have been the whole point of the test. **Lesson:** a test
that skips on its own precondition can hide exactly the thing it exists for;
assert the precondition.

### M63 — A phone-sized desktop browser shows what the phone shows

**Believed:** screenshots from headless Chromium with the Pixel's viewport and
pixel ratio were a faithful preview of the app. **Revealed by:** on the actual
phone the ASCII logo overflowed by ~10%. DevTools on the device showed the
bold block glyph measuring 0.708 em and the ExtraBold face never requested:
`<pre>` takes `monospace` from the UA stylesheet, so the art was never in the
bundled font at all. On the desktop the platform monospace (DejaVu Sans Mono)
happens to be 0.6 em too, which hid it. **Corrected to:** `pre, textarea
{ font-family: inherit }`; the grid is now the bundled font everywhere.
**Cost:** a rebuild and a device round-trip. **Lesson:** emulating a viewport
emulates the viewport, not the fonts. Look at the real device before calling a
character grid done.

### M64 — Pyodide's stdin callback hands Python whatever string it returns

**Believed:** returning the whole payload from `setStdin({stdin})` gives the
harness the whole line. **Revealed by:** `JSONDecodeError: Unterminated string
... char 8190` on the first real payload. **Corrected to:** the byte-level
`read(buffer)` form, which the harness drains exactly like a pipe. **Cost:**
one probe. **Lesson:** probe a new transport with a production-sized payload,
not a toy one.

## Friction

- XML comments may not contain `--`; the first manifest failed to link on a
  prose dash.
- `apksigner` reads a *second line* for `--key-pass` when it names the same file
  as `--ks-pass`; signing failed with "end of file" until the key password was
  left implied.
- The permission classifier failed to answer for several minutes early on,
  which cost idle time, not work.
- **The deploy target was unreachable.** Every port on 178.104.120.219 timed out
  from this host, and the shell history shows the site is administered as
  `astra` (a Docker Compose stack), not `root`. A live site with payments is
  not reconfigured blind, so the build, its exact nginx/Caddy blocks and an
  atomic-swap deploy tool were prepared instead. W5 stays open.

## Decisions

| # | Decision | Alternatives considered | Rationale | Reversible? |
| --- | --- | --- | --- | --- |
| D242 | Run the real engine on phones and in browsers via Pyodide, bundled in those builds only (user-approved N1 exception) | Termux-only CLI (no APK); Chaquopy/BeeWare native Python (Gradle, larger third-party surface); re-implement scoring in JavaScript | The only option that keeps one engine: scores come from `scoring.py`, not a copy; the package itself stays dependency-free | yes |
| D243 | An async `Service` with an injected executor, not synchronous `run_code` inside Pyodide | Block the engine worker on a sandbox via SharedArrayBuffer + Atomics | Needs cross-origin isolation, which a static host behind a CDN cannot always promise; the executor seam also makes the layer testable with real subprocesses | yes (behind `Executor`) |
| D244 | Boss steps run free and are replayed at the CLI's pace, instead of stepping a blocked child | Live stepping over a blocking stdin (needs SharedArrayBuffer) | Same visible behaviour and scoring: pause on the raising line, strategy-A divergence check, heal priced on the failing code, animation off the clock | yes |
| D245 | Hand-built Android shell: one activity, SDK tools only, no INTERNET permission, no cloud backup | Gradle + AndroidX `WebViewAssetLoader`; Capacitor/Cordova | Nothing to download, nothing third-party in the APK but Pyodide, and a privacy promise the OS enforces rather than one the app makes | yes |
| D246 | The phone's "reset progress" also deletes saved runs | Match `vibecoder reset` (profile only) | A run artifact is the player's code, and a phone offers no terminal to find it afterwards | yes |
| D247 | A boss attempt runs the watched step and the full verdict concurrently | Sequentially, as the CLI does | The CLI waits because its child is blocked on a person; here neither waits on anyone, and the second worker is already warm | yes |

## Handoff

- **State:** T9 W1–W4 landed: `vibecoder.service`, the browser build, the acid-punk
  client and a signed APK (0.2.0, installed on the user's Pixel). Wheel and
  sdist built and checked; the user uploads them to PyPI. W5 (hosting on
  astra-arcana.com/vibecoder/) is prepared but not done; W6 (human play) not done.
- **Next action:** once the server is reachable, run
  `python3.11 tools/web/deploy.py astra@<host>:<path> --key ~/.ssh/astra_hetzner`,
  add the `location ^~ /vibecoder/` block from `docs/WEB.md` to the site's
  proxy, and confirm the headers with `curl -I` (T9 W5).
- **Blockers:** SSH to 178.104.120.219 times out from the build host (firewall
  or changed address, Q104).
- **Context required:** `docs/WEB.md` end to end; `service.py` is the only
  surface a non-terminal client uses; browser op counts are never baselines;
  the release key in `~/.config/vibecoder/` must be backed up.

## Open questions

| # | Question | Owner trajectory | Status |
| --- | --- | --- | --- |
| Q104 | How is astra-arcana.com served (proxy in the Compose stack or on the host), and from where is SSH allowed? | T9 | open |
| Q105 | Should `pip install vibecoder` also ship `vibecoder web`, serving this client over the native engine? | T9 | open |
| Q106 | Publish to Google Play (needs an AAB, a developer account and a privacy policy), or stay sideload-only? | T9 | open |
