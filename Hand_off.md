# Hand_off.md — orientation for the next session

**Composed:** 2026-09-28, at the close of S044 · **In flight:** T9 (phone and
browser; W1–W5 landed, W6 open) and T8 (desktop; paused on Q103) · **Read
next:** [`journal/2026-09-28-S044-review.md`](journal/2026-09-28-S044-review.md),
then [`docs/trajectories/T9-mobile-web.md`](docs/trajectories/T9-mobile-web.md)
and [`docs/WEB.md`](docs/WEB.md).

This file is the point of entry. It does not replace [`CLAUDE.md`](CLAUDE.md)
(the invariants and the definition of done) or the journal (the history). It
says what is true now, how to do the common things, and what to do next.

---

## 1. First sixty seconds

- **The shell is zsh**, whatever the environment line says. Unmatched globs
  abort the command (`rm dist/*.whl` with no match fails), bare `=====` is
  expanded, and an unquoted variable holding two flags is *not* split. Quote,
  and use `find` or Python for file lists.
- **Run every gate as `python3.11`.** `python3` here is 3.14; the op-count
  baselines were recorded on 3.11.15 and ~25 of them fail under 3.14 with no
  code wrong (M61). `python3.11` is uv-managed: `pip install --user` is refused
  (PEP 668), so use `uvx <tool>` or a venv for build tooling.
- **Save full logs, then grep them.** Piping a 90-second suite through
  `tail -4` hides which test failed. `> log 2>&1; grep -E '^(FAIL|ERROR)' log`.
- **Scratch `VIBECODER_HOME`** for anything that writes progress.

```bash
VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests   # inner loop, ~60s
python3.11 -m unittest discover -s tests                           # before commit (N8): 1487
python3.11 -m vibecoder.cli verify --seeds 3                       # 54/54
```

## 2. What exists now

One engine, three clients, all at **v0.2.0**:

| Client | Where | How it runs Python |
| --- | --- | --- |
| Terminal | `pipx install git+https://github.com/9x25dillon/VIbe_coder_9xk1ll` | the player's CPython; each submission a fresh child process |
| Browser | **https://vibecoder.astra-arcana.com** (offline after one visit) | Pyodide (CPython 3.14.2 in WebAssembly) in an engine worker; each submission a fresh sandbox worker |
| Android | `vibecoder-0.2.0.apk` on the [v0.2.0 release](https://github.com/9x25dillon/VIbe_coder_9xk1ll/releases/tag/v0.2.0); installed on the user's Pixel 10a | the browser build in a WebView, served from APK assets; **no INTERNET permission** |

**PyPI is out of scope** by the user's decision (D251). Do not reintroduce
`pip install vibecoder` in docs unless that changes.

### New code, one line each

| Path | What it is |
| --- | --- |
| `vibecoder/service.py` | The game as async use cases (levels, bosses, daily, stats, reset). Owns seed, difficulty, attempts, clock and saves. Execution is an injected `Executor`. The **only** surface a non-terminal client uses. |
| `vibecoder/runner.py` | `build_payload` / `parse_reply` split out of `run_code` so every transport sends and reads the same thing. |
| `web/` | The client: no framework, no build step, no CDN. `boot.py` is the engine worker's allow-list (`METHODS`); `js/app.js` renders and never decides. |
| `android/` | One Java activity. Serves `assets/www` on `https://appassets.androidplatform.net/`, pads for the keyboard itself (edge-to-edge), routes Back through the page. |
| `tools/web/` | `build.py` (hash-pinned Pyodide + fonts), `serve.py` (the headers), `smoke.py` (stdlib WebDriver: engine checks, `--shots`, `--prefix`, `--url`), `deploy.py`, `icon.py`. |
| `tools/android/` | `build_apk.py` (aapt2 → javac → d8 → zipalign → apksigner, no Gradle), `device_smoke.py` (stdlib DevTools client into the phone's WebView). |
| `tests/test_service.py`, `tests/test_web.py` | 31 + 19 tests: scoring parity with the CLI, bad solutions, N9, one CSP in three places, no network, engine surface. |

## 3. Invariants most directly in play

- **N1 / D242**: the Python package has no dependency. Pyodide is bundled in
  the web and Android builds only, pinned in `tools/web/assets.lock.json`.
- **N4 / N9**: a sandbox worker is an isolation boundary and declares itself
  non-isolating; `Service._execute` refuses third-party code on it and takes
  `source` with no default.
- **Browser op counts are never baselines.** Functional stays fair because the
  reference is measured in the same interpreter as the submission.
- **One CSP in three places** — `web/index.html`, `tools/web/serve.py`,
  `android/.../MainActivity.java` — and a fourth copy lives in the site repo's
  nginx block. `tests/test_web.py` guards the first three.
- **`<pre>` must inherit the bundled font** (M63). A character grid in the
  platform monospace is ~18% too wide on Android.
- **Boss results are scored, never banked** (Q84), on every client.

## 4. Cookbook

```bash
# Browser build: build, serve locally, check
python3.11 tools/web/build.py
python3.11 tools/web/serve.py                       # http://127.0.0.1:8737
python3.11 tools/web/smoke.py                       # engine checks, headless Chromium
python3.11 tools/web/smoke.py --shots /tmp/shots    # every screen, phone-sized; then LOOK at them

# Phone: debug build (separate app id, DevTools on), then engine checks on the device
python3.11 tools/android/build_apk.py --debug --install
python3.11 tools/android/device_smoke.py
python3.11 tools/android/device_smoke.py --eval 'document.title'
adb exec-out screencap -p > /tmp/phone.png          # then read the image

# Release APK (signed with the release key; updates the installed app in place)
python3.11 tools/android/build_apk.py && adb install -r dist/vibecoder-<version>.apk

# Ship a new web build to production (no container restart)
python3.11 tools/web/deploy.py astra@178.104.120.219:/home/astra/astro-aae/vibecoder-web \
    --key ~/.ssh/astra_hetzner
python3.11 tools/web/smoke.py --url https://vibecoder.astra-arcana.com/

# Cut a release: bump vibecoder/__init__.py + pyproject.toml, rebuild from a
# clean commit, checksum, tag, gh release create (see S042 for the exact set)
```

**Test on the phone early.** Headless Chromium at the phone's viewport does not
have the phone's fonts or keyboard; the only layout bug of the session was
invisible everywhere but the device.

## 5. The live site — handle with care

- **Server**: `astra@178.104.120.219`, key `~/.ssh/astra_hetzner`. SSH is
  allow-listed by **source** address; if it times out, the user's home IP has
  probably changed (`curl -4 ifconfig.me`) and the Hetzner firewall needs it.
- **It is a production site with payments.** The stack is the user's other
  project, `9x25dillon/astro_caster` (`~/astro-aae` on both machines), run with
  Docker Compose: `astra-backend-1` (API, Stripe, AI) and `astra-frontend-1`
  (nginx, TLS, three hosts). Never touch `.env`, the backend, or `certs/`.
- **The game's block** is the third `server` in `frontend/nginx.conf` of that
  repo, policed by its `backend/tests/test_edge_headers.py`. Files are mounted
  read-only from `~/astro-aae/vibecoder-web/current`.
- **Changing nginx** goes through that repo: commit, push, then on the box
  `bash ops/deploy_frontend.sh` (pulls `main`, rebuilds only the frontend).
  Check `git log HEAD..origin/main` on the box first — the script ships
  whatever is on `main`. Validate a config change in a local
  `nginx:1.27-alpine` container before it goes anywhere near the box.
- **DNS** is `ops/cloudflare_dns.sh` (preflight by default, `--apply` to write),
  with the token in `~/.cloudflare-token` on this machine. Read before writing.
- The local clone has an untracked personal file in its root. Never `git add -A`
  there; stage files by name.

## 6. What remains unproven (do not assert these)

- **Human play** (T9 W6): nobody has played a level or a boss through on the
  phone by hand.
- Firefox, Safari, iOS; older Android WebViews; low-memory phones running three
  Pyodide instances at once.
- First-visit load on a phone network (10.3 s measured on desktop broadband).
- A memory bomb in the browser sandbox: WebAssembly has no rlimit, so it can
  only be caught as a worker crash — expected, not tested.

## 7. The single next action

**T9 W6.** Have the user play the release APK: clear one level by typing (use
the symbol row), then fight *The Feed* to the end. Record what they found in a
journal entry. That is the only T9 exit criterion (7) nothing automated can
satisfy, and it lands the trajectory's last waypoint.

Candidates after that, each needing the user's call first:
**Q105** ship `vibecoder web` in the package (serve this client over the native
engine) · **Q106** Google Play (AAB, developer account, privacy policy) ·
**Q107** content-hashed web files so the CDN can cache them · **Q84** bank boss
results · **Q108** delete the stale `feat/terminal-cockpit` branch (its patch is
already on `main` as `7a5940c`) · **T8** resumes when native runners exist (Q103).

## 8. Working agreement, sharpened by this session

From the S044 review — for whoever reads this next:

- **Read the host before offering a choice about it.** The URL question was
  asked before the server was seen, and had to be asked again (M65).
- **Ask for prerequisites in the first round**: accounts, credentials, SSH
  user, firewall. Each one missing became a blocker hours later.
- **Keep the blast radius explicit** when touching anything live: say what will
  restart, what will not, and read before writing.
- **A status like "okay" needs its content.** If the user reports a change,
  ask what exactly changed rather than retrying blind.

### Vocabulary in use

- **Idempotent** — same result however many times it runs (finish, daily and
  reset cannot double-bank).
- **Provenance** — where code came from, deciding whether it may run (N9).
- **Origin** — scheme + host + port; the unit browsers isolate storage, service
  workers and policy by. Why the game is on its own subdomain.
- **Blast radius** — everything a change could break; keep it named and small.
