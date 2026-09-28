# Phone and browser builds

VibeCoder runs in three places from one engine:

| Client | Where the Python runs | Where submissions run |
| --- | --- | --- |
| CLI (`vibecoder`) | the player's CPython | a fresh child process per run (`runner.run_code`) |
| Browser | Pyodide (CPython 3.14 in WebAssembly) in a worker | a fresh Pyodide worker per run |
| Android app | the same browser build, in a WebView | the same, on the phone |

Nothing about the game is re-implemented in JavaScript. The browser loads the
`vibecoder` package itself (zipped from `vibecoder/` at build time) and drives
it through [`vibecoder/service.py`](../vibecoder/service.py), the same
use-case layer the tests exercise with real subprocesses. Scores come from
`scoring.py`; the reference is benchmarked in the same interpreter as the
submission, so the Functional axis compares like with like even though
Pyodide's op counts differ from the 3.11 baselines. Browser numbers are never
recorded as baselines.

## How a run works in the browser

```
page (js/app.js)           engine worker (workers/engine.js)        sandbox worker (workers/sandbox.js)
  intent ──call("run")──▶  boot.py → Service.run()
                             build_payload() ──vcExecute──▶ page ──▶ fresh Pyodide, `_harness.py` unchanged
                                                                      progress lines ──▶ page (live ✓/✗)
                             parse_reply()  ◀──── stdout ─────────── done / crash / page's deadline
  facts  ◀──reply──────────  score_submission(), tips, Session.save()
```

- **Isolation, not security (N4).** A worker is a good fence around the
  player's own infinite loop; the page terminates it at the payload's timeout
  plus two seconds, which is the browser's version of the host watchdog. It is
  declared non-isolating, so the service refuses third-party code on it (N9).
- **A fresh interpreter per run.** Workers are booted ahead of need (two
  spares) and thrown away after one run.
- **Progress** lives in `/home/pyodide/.vibecoder/profile.json` inside the
  engine worker, on an IndexedDB-backed filesystem that is flushed after every
  save. It is the same `Session` file format as the CLI's. Nothing leaves the
  device: no accounts, no analytics, no network calls with player data.
- **Boss fights** run each step free (the child is released immediately) and
  the page replays the recorded lines at the CLI's pace (0.35 s a line, three
  laps of a loop before fast-forwarding), pausing on the line that raised. The
  replay's own animation is reported back and taken off the Speed clock, the
  same subtraction `cli._Pacer` makes. Fights are scored, not banked (Q84).

## Building

```bash
python3.11 tools/web/build.py          # -> build/web (static site, ~14 MB)
python3.11 tools/web/serve.py          # http://127.0.0.1:8737 with production headers
python3.11 tools/web/smoke.py          # engine checks in headless Chromium
python3.11 tools/web/smoke.py --prefix vibecoder   # the same, hosted under a subpath
python3.11 tools/web/smoke.py --shots /tmp/shots   # walk every screen, screenshot each

python3.11 tools/android/build_apk.py              # dist/vibecoder-<version>.apk, release-signed
python3.11 tools/android/build_apk.py --debug --install   # debuggable build, separate app id
python3.11 tools/android/device_smoke.py           # engine checks inside the phone's WebView
```

Third-party files (Pyodide, JetBrains Mono, VT323) are downloaded by the build,
checked against [`tools/web/assets.lock.json`](../tools/web/assets.lock.json),
and never committed. Their licences are in [`web/licenses/`](../web/licenses/).

The APK is built with the SDK's own tools (`aapt2`, `javac`, `d8`, `zipalign`,
`apksigner`); there is no Gradle. The release key is created on first build in
`~/.config/vibecoder/` — **back it up**, because an APK signed with a different
key cannot update an installed one without uninstalling it, which deletes the
player's progress.

## Hosting the browser build

Every URL the page makes is relative, so the build works from any path
(`smoke.py --prefix` proves it). A host must send:

| Requirement | Why |
| --- | --- |
| `script-src 'self' 'wasm-unsafe-eval'` | compiling WebAssembly counts as eval under CSP; without it Python never starts |
| `worker-src 'self'` | the engine and every sandbox are module workers |
| `Content-Type: application/wasm` for `.wasm` | streaming compilation refuses anything else |
| `Content-Type: text/javascript` for `.mjs` | module workers refuse anything else |

The full policy is `serve.CSP` in [`tools/web/serve.py`](../tools/web/serve.py);
`tests/test_web.py` asserts that the page, the local server and the Android
shell send the same one.

### nginx

```nginx
location ^~ /vibecoder/ {
    alias /var/www/vibecoder/;
    types {
        text/html html; text/css css; text/javascript js mjs;
        application/json json; application/manifest+json webmanifest;
        application/wasm wasm; application/zip zip; font/woff2 woff2;
        image/svg+xml svg; image/png png; text/plain py txt;
    }
    # add_header here replaces any the server block sets, which is the point:
    # this path needs its own CSP.
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    add_header Cache-Control "no-cache" always;
}
```

### Caddy

```caddy
handle_path /vibecoder/* {
    root * /var/www/vibecoder
    header Content-Security-Policy "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; worker-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; font-src 'self'; img-src 'self' data:; manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'"
    header X-Content-Type-Options nosniff
    file_server
}
```

If a CDN in front of the site adds its own CSP (a Cloudflare transform rule,
for instance), exempt `/vibecoder/*` there too, and turn off anything that
rewrites scripts (Rocket Loader). Check what is really served:

```bash
curl -sI https://example.com/vibecoder/ | grep -i content-security
curl -sI https://example.com/vibecoder/vendor/pyodide/pyodide.asm.wasm | grep -i content-type
```

### Uploading

```bash
python3.11 tools/web/deploy.py user@host:/var/www/vibecoder --key ~/.ssh/key
```

`deploy.py` copies `build/web` into a new versioned directory beside the
target and then swaps a symlink, so a visitor never loads half of one build and
half of another. The offline worker (`sw.js`) is stamped with the build id,
so a new deploy replaces the cached copy on the next visit.
