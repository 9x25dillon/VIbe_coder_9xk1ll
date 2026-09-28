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

The live build is at **https://vibecoder.astra-arcana.com**
([S043](../journal/2026-09-28-S043-going-live.md)).

Every URL the page makes is relative, so the build *can* run from a subpath
(`smoke.py --prefix` proves it). **Prefer its own origin anyway.** A host
whose other pages have a strict policy, or a service worker scoped to `/`,
would have to loosen the one or share its scope with the other; a subdomain
needs neither. That is what astra-arcana.com turned out to require (M65).

A host must send:

| Requirement | Why |
| --- | --- |
| `script-src 'self' 'wasm-unsafe-eval'` | compiling WebAssembly counts as eval under CSP; without it Python never starts |
| `worker-src 'self'` | the engine and every sandbox are module workers |
| `Content-Type: application/wasm` for `.wasm` | streaming compilation refuses anything else |
| a JavaScript type for `.mjs` | module workers refuse anything else, and nginx's `mime.types` has no `.mjs` |
| `Cache-Control: no-cache` | file names are not content-hashed, so a cached `app.js` from the last build would meet this build's HTML; revalidation is a 304, and the offline worker makes repeat visits fast |

The full policy is `serve.CSP` in [`tools/web/serve.py`](../tools/web/serve.py);
`tests/test_web.py` asserts that the page, the local server and the Android
shell send the same one.

### nginx (as deployed)

```nginx
server {
    listen 443 ssl;
    server_name vibecoder.example.com;
    # ssl_certificate ... as for the rest of the site

    root /usr/share/nginx/vibecoder/current;   # a link the deploy tool swaps
    index index.html;

    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; font-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'; frame-ancestors 'none'" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;
    add_header Cache-Control "no-cache" always;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml application/wasm text/plain;

    # No add_header in these, so they inherit the set above.
    location ~ \.mjs$         { types { } default_type application/javascript;    try_files $uri =404; }
    location ~ \.webmanifest$ { types { } default_type application/manifest+json; try_files $uri =404; }
    location /                { try_files $uri $uri/ =404; }
}
```

On astra-arcana.com this block lives in the site's own repository
(`astro_caster`, `frontend/nginx.conf`), where `test_edge_headers.py` polices
it with the rest, and the build directory is bind-mounted read-only into the
frontend container from `~/astro-aae/vibecoder-web`.

### Uploading

```bash
python3.11 tools/web/build.py
python3.11 tools/web/deploy.py astra@<host>:/home/astra/astro-aae/vibecoder-web \
    --key ~/.ssh/astra_hetzner
```

`deploy.py` unpacks each build into its own directory inside the target and
swaps a relative `current` link to it with one `rename`. The swap is *inside*
the directory because the directory is a container bind mount, and Docker
resolves a mount's source once, at container start: a link replaced at the
mount point itself would go unseen until a restart (M66). nginx resolves
`current` per request, so a deploy needs no restart, a visitor never loads
half of one build, and a rollback is pointing `current` back. The offline
worker (`sw.js`) is stamped with the build id, so browsers pick up a new build
on their next visit. Check what is really served, not what the config says:

```bash
curl -sI https://vibecoder.astra-arcana.com/ | grep -i content-security
curl -s -o /dev/null -w '%{content_type}\n' https://vibecoder.astra-arcana.com/vendor/pyodide/pyodide.asm.wasm
python3.11 tools/web/smoke.py --url https://vibecoder.astra-arcana.com/
```
