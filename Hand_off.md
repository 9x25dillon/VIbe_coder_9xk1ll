# Hand_off.md — orientation for the next session

**Composed:** 2026-09-28, at the close of S043 · **Trajectories in flight:** T9
(phone and browser) and T8 (desktop, paused on Q103) · **Consult after** the
newest [`journal/`](journal/) entry and
[`docs/trajectories/T9-mobile-web.md`](docs/trajectories/T9-mobile-web.md).

This is a point of entry, not a replacement for [`CLAUDE.md`](CLAUDE.md) or the
record system. It describes the present and the next step only.

---

## 1. The pitfalls you will meet first

- **Run every gate under `python3.11`, never bare `python3`.** This host's
  `python3` is 3.14 and the op-count baselines were recorded on 3.11.15; under
  3.14 about 25 baseline tests fail without any code being wrong (M61).
- **Browser op counts are not baselines.** The phone and browser run CPython
  3.14.2 in Pyodide. Functional stays honest because the reference is measured
  in the same interpreter; never record a browser figure in `data/baselines/`.
- **Point `VIBECODER_HOME` at a scratch directory** for anything that writes
  progress.

```bash
VIBECODER_SANDBOX=bwrap python3.11 -m unittest discover -s tests   # inner loop
python3.11 -m unittest discover -s tests                           # before commit (N8): 1487
python3.11 -m vibecoder.cli verify --seeds 3                       # 54/54
```

## 2. Present state

- **Released 0.2.0**: the CLI package (wheel + sdist, uploaded to PyPI by the
  user), a signed Android APK on the GitHub release, and the browser build
  **live at https://vibecoder.astra-arcana.com** (S043), all one engine. See
  [`docs/WEB.md`](docs/WEB.md) for the whole path.
- **`vibecoder/service.py`** is the game as async use cases (levels, bosses,
  daily, stats, reset) with an injected executor. It is the only surface the
  browser uses, through `web/boot.py`'s allow-list, and a first draft of the
  service T8 W2 asks for.
- **Android**: `com.astraarcana.vibecoder`, no INTERNET permission, no cloud
  backup. The release key is `~/.config/vibecoder/android-release.jks` with its
  password file beside it — **it must be backed up**; a different key cannot
  update an installed app.
- **Hosting**: the site's repository is `9x25dillon/astro_caster`
  (`~/astro-aae` locally and on the box). The game has its own server block in
  its `frontend/nginx.conf`, policed by that repo's `test_edge_headers.py`,
  and its files live in `~/astro-aae/vibecoder-web` on the server, mounted
  read-only. SSH is `astra@178.104.120.219` with `~/.ssh/astra_hetzner`,
  allowed only from an allow-listed source address.

## 3. What remains unproven (do not assert these)

- Human play on the phone (T9 W6), Firefox, Safari and iOS.
- First-visit load time on a phone network (10.3 s measured on a desktop
  connection; after that the offline worker serves everything locally).

## 4. The single next action (T9 W6)

Play the phone build as a person: clear a level by typing and fight a boss to
the end, then record what was found. To ship a new web build:

```bash
python3.11 tools/web/build.py
python3.11 tools/web/deploy.py astra@178.104.120.219:/home/astra/astro-aae/vibecoder-web \
    --key ~/.ssh/astra_hetzner
python3.11 tools/web/smoke.py --url https://vibecoder.astra-arcana.com/
```

## 5. Invariants most directly in play

- **N1**: the Python package has no dependency. Pyodide is bundled in the web
  and Android builds only (D242), pinned by hash in `tools/web/assets.lock.json`.
- **N4 / N9**: a sandbox worker is an isolation boundary, declared
  non-isolating; the service refuses third-party code on it.
- **One CSP in three places** — `web/index.html`, `tools/web/serve.py`,
  `MainActivity.java`. `tests/test_web.py` fails if they drift.
- **`<pre>` must inherit the bundled font** (M63); a character grid in the
  platform monospace is 18% too wide on Android.

## 6. Open questions carried forward

- **Q107** — content-hashed file names, so the CDN can cache the build.
- **Q105** — should the pip package ship `vibecoder web`?
- **Q106** — Google Play, or sideload-only?
- **Q103** (T8) — native Windows/macOS runners and signing identity.
- **Q84** — boss results are scored but not banked, on every client.
- **Q100** (T5) — server leaderboards cannot verify human solve time.
