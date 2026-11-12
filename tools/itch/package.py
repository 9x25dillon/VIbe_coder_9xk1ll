"""Package the browser build for itch.io: one zip, `index.html` at its root.

Build-time tool, stdlib only, like the rest of `tools/web/`. It takes the
static site `tools/web/build.py` makes and adapts it to a host we do not
control, then refuses to write a zip that itch.io would reject.

itch.io serves an HTML5 upload from a subdirectory of its own CDN, inside an
iframe on the game's page. Three things about that host differ from the one
the build was written for (docs/WEB.md, "Hosting the browser build"):

* **We cannot set headers.** `serve.py` sends a JavaScript type for `.mjs`
  because module workers refuse anything else; nobody documents what itch's
  CDN sends for `.mjs`. Every host serves `.js` as JavaScript, so Pyodide's
  two `.mjs` files are renamed and the four strings that name them are
  rewritten. Each rewrite must match an exact number of times, so a Pyodide
  upgrade that moves a name fails here, loudly, instead of on itch.
* **The page is someone else's frame.** The offline worker (`sw.js`) is left
  out: offline play is not a feature of an embed, and a cache-first worker
  in a partitioned third-party frame is one more way to serve last week's
  build. The page already tolerates a failed registration.
* **Uploads have limits** (itch.io/docs/creators/html5): at most 1,000
  files, 500 MB in total, 200 MB per file, 240 characters per path, and
  relative paths only. All are checked before the zip is written.

`build-info.json` is rewritten to describe the files actually shipped, with
`"target": "itch.io"`, so the build id on the About screen names this zip.

    python3.11 tools/itch/package.py        # build, then dist/vibecoder-itch-<version>.zip
    python3.11 tools/itch/package.py --from build/web   # package an existing build
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "web"))

import build as web_build  # noqa: E402

#: Same fixed timestamp as the engine archive: one build, one zip, one hash.
EPOCH = web_build.EPOCH

#: Files whose type the host must get right, renamed to an extension every
#: host gets right.
RENAMES = {
    "vendor/pyodide/pyodide.mjs": "vendor/pyodide/pyodide.js",
    "vendor/pyodide/pyodide.asm.mjs": "vendor/pyodide/pyodide.asm.js",
}

#: (file after renaming, text, replacement, exact number of occurrences).
#: The two worker imports are ours; the two Pyodide strings are its loader
#: (`${indexURL}pyodide.asm.mjs`) and its stack-frame filter, which hides the
#: interpreter's own frames from a player's traceback by file name.
PATCHES = (
    ("workers/engine.js", '"../vendor/pyodide/pyodide.mjs"', '"../vendor/pyodide/pyodide.js"', 1),
    ("workers/sandbox.js", '"../vendor/pyodide/pyodide.mjs"', '"../vendor/pyodide/pyodide.js"', 1),
    ("vendor/pyodide/pyodide.js", "pyodide.asm.mjs", "pyodide.asm.js", 1),
    ("vendor/pyodide/pyodide.asm.js", "pyodide.asm.mjs", "pyodide.asm.js", 1),
)

#: Shipped by the web build, not wanted inside someone else's frame.
DROP = ("sw.js",)

#: itch.io's documented upload limits.
MAX_FILES = 1000
MAX_TOTAL = 500 * 1024 * 1024
MAX_FILE = 200 * 1024 * 1024
MAX_PATH = 240

#: A reference that starts at the host's root escapes the upload's
#: subdirectory and 404s (itch answers 403) on the CDN.
ROOT_REFERENCE = re.compile(
    r"""(?:\b(?:src|href)\s*=\s*["']/(?!/)|\burl\(\s*["']?/(?!/)|\bfrom\s+["']/(?!/)|\bimport\(\s*["']/(?!/))"""
)
TEXT = (".html", ".js", ".css")


class PackageError(SystemExit):
    """A zip itch.io would reject, or a build this tool no longer understands."""


def transform(site: Path) -> None:
    """Rewrite a copy of the web build, in place, into what itch.io serves."""
    for name in DROP:
        target = site / name
        if not target.exists():
            raise PackageError(f"{name} missing from the build; has the web build changed?")
        target.unlink()
    for old, new in RENAMES.items():
        source = site / old
        if not source.exists():
            raise PackageError(f"{old} missing from the build; was Pyodide's layout changed?")
        source.rename(site / new)
    for name, text, replacement, expected in PATCHES:
        path = site / name
        content = path.read_text(encoding="utf-8")
        found = content.count(text)
        if found != expected:
            raise PackageError(
                f"{name}: expected {expected} occurrence(s) of {text!r}, found {found}; "
                "update PATCHES for the new build before packaging")
        path.write_text(content.replace(text, replacement), encoding="utf-8")
    leftovers = sorted(p.relative_to(site).as_posix() for p in site.rglob("*.mjs"))
    if leftovers:
        raise PackageError(f"unrenamed module files would depend on the host's types: {leftovers}")


def describe(site: Path) -> dict:
    """Rewrite `build-info.json` to list exactly the files in this package."""
    info_path = site / "build-info.json"
    info = json.loads(info_path.read_text(encoding="utf-8"))
    files = {
        path.relative_to(site).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(site.rglob("*"))
        if path.is_file() and path.name != "build-info.json"
    }
    info["files"] = files
    info["build"] = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:16]
    info["target"] = "itch.io"
    info_path.write_text(json.dumps(info, indent=1) + "\n", encoding="utf-8")
    return info


def check(site: Path) -> list[Path]:
    """Every limit itch.io documents, checked here rather than after an upload."""
    if not (site / "index.html").is_file():
        raise PackageError("index.html must be at the root of the zip")
    files = sorted(p for p in site.rglob("*") if p.is_file())
    if len(files) > MAX_FILES:
        raise PackageError(f"{len(files)} files; itch.io accepts at most {MAX_FILES}")
    total = 0
    for path in files:
        name = path.relative_to(site).as_posix()
        size = path.stat().st_size
        total += size
        if size > MAX_FILE:
            raise PackageError(f"{name} is {size} bytes; itch.io accepts at most {MAX_FILE} per file")
        if len(name) > MAX_PATH:
            raise PackageError(f"{name} is {len(name)} characters; itch.io accepts at most {MAX_PATH}")
        if path.suffix in TEXT:
            match = ROOT_REFERENCE.search(path.read_text(encoding="utf-8", errors="replace"))
            if match:
                raise PackageError(f"{name} has a root-relative reference ({match.group(0)!r}); "
                                   "it would escape the upload's directory on itch.io")
    if total > MAX_TOTAL:
        raise PackageError(f"{total} bytes in total; itch.io accepts at most {MAX_TOTAL}")
    return files


def write_zip(site: Path, files: list[Path], destination: Path) -> None:
    """Deterministic: sorted entries, one timestamp, so one build gives one hash."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".zip.part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(site).as_posix(), date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    partial.replace(destination)


def package(build_dir: Path, destination: Path) -> dict:
    """Copy `build_dir`, adapt the copy for itch.io, check it, zip it."""
    if not (build_dir / "build-info.json").is_file():
        raise PackageError(f"{build_dir} is not a web build (no build-info.json); "
                           "run tools/web/build.py first")
    with tempfile.TemporaryDirectory(prefix="vibecoder-itch-") as scratch:
        site = Path(scratch) / "site"
        shutil.copytree(build_dir, site)
        transform(site)
        info = describe(site)
        files = check(site)
        write_zip(site, files, destination)
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="source", type=Path,
                        help="an existing web build; default: build one into build/web")
    parser.add_argument("--output", type=Path,
                        help="the zip to write; default: dist/vibecoder-itch-<version>.zip")
    parser.add_argument("--cache", type=Path, default=ROOT / "build" / "web-cache")
    args = parser.parse_args(argv)

    source = args.source
    if source is None:
        source = ROOT / "build" / "web"
        source.parent.mkdir(parents=True, exist_ok=True)
        web_build.build(source.resolve(), args.cache.resolve())
    output = args.output or ROOT / "dist" / f"vibecoder-itch-{web_build.engine_version()}.zip"
    info = package(source.resolve(), output.resolve())
    size = output.stat().st_size
    print(f"wrote {output} -- engine {info['engine']}, {len(info['files']) + 1} files, "
          f"{size / 1e6:.1f} MB zipped, build {info['build']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
