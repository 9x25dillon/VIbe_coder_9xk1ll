"""Assemble the browser build: the web client, the engine, and a pinned Pyodide.

Build-time tool, stdlib only (N1 covers the shipped core and the tests; this is
neither, and it still needs nothing). The output directory is a static site:
it runs from any HTTP server that sends the headers in `serve.py`, from the
Android shell's asset loader, and from nothing else -- there is no CDN, and no
file is fetched at runtime from anywhere but its own origin.

Every third-party byte is checked against `assets.lock.json` before it is
unpacked. The engine is zipped straight from `vibecoder/`, so the browser runs
exactly the package the test suite ran.

    python3.11 tools/web/build.py            # -> build/web
    python3.11 tools/web/serve.py            # serve it on 127.0.0.1:8737
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import icon  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
LOCK = Path(__file__).with_name("assets.lock.json")
CLIENT = ROOT / "web"
PACKAGE = ROOT / "vibecoder"

#: Fixed timestamp for every zip entry, so two builds of one commit produce
#: the same engine archive and the same hash in `build-info.json`.
EPOCH = (2026, 1, 1, 0, 0, 0)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, digest: str, cache: Path) -> bytes:
    """Download once into the cache, and refuse anything that does not match."""
    cache.mkdir(parents=True, exist_ok=True)
    cached = cache / digest
    if cached.exists():
        data = cached.read_bytes()
        if sha256(data) == digest:
            return data
        cached.unlink()
    print(f"  fetching {url}", file=sys.stderr)
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    actual = sha256(data)
    if actual != digest:
        raise SystemExit(f"checksum mismatch for {url}\n  want {digest}\n  got  {actual}")
    cached.write_bytes(data)
    return data


def engine_archive() -> bytes:
    """The `vibecoder` package as a zip, sources only, deterministic order."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PACKAGE.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            name = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(name, date_time=EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def engine_version() -> str:
    for line in (PACKAGE / "__init__.py").read_text().splitlines():
        if line.startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise SystemExit("no __version__ in vibecoder/__init__.py")


def commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return head + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build(output: Path, cache: Path) -> dict:
    lock = json.loads(LOCK.read_text())
    staging = Path(tempfile.mkdtemp(prefix="vibecoder-web-", dir=output.parent))
    try:
        shutil.copytree(CLIENT, staging, dirs_exist_ok=True)

        pyodide = lock["pyodide"]
        tgz = fetch(pyodide["url"], pyodide["sha256"], cache)
        with tarfile.open(fileobj=io.BytesIO(tgz), mode="r:gz") as archive:
            for member, target in pyodide["files"].items():
                data = archive.extractfile(member)
                if data is None:
                    raise SystemExit(f"{member} missing from Pyodide archive")
                destination = staging / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data.read())

        mono = lock["jetbrains_mono"]
        with zipfile.ZipFile(io.BytesIO(fetch(mono["url"], mono["sha256"], cache))) as archive:
            for member, target in mono["files"].items():
                destination = staging / target
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(member))

        vt = lock["vt323"]
        destination = staging / vt["file"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(fetch(vt["url"], vt["sha256"], cache))

        (staging / "py").mkdir(exist_ok=True)
        (staging / "py" / "vibecoder.zip").write_bytes(engine_archive())
        # The sandbox worker runs the harness as a script and never imports
        # the package (N2), so it gets the one file on its own.
        shutil.copy2(PACKAGE / "_harness.py", staging / "py" / "_harness.py")

        icon.write_web(staging)

        files = {
            path.relative_to(staging).as_posix(): sha256(path.read_bytes())
            for path in sorted(staging.rglob("*"))
            if path.is_file() and path.name != "sw.js"
        }
        build_id = sha256(json.dumps(files, sort_keys=True).encode())[:16]
        # The offline worker must change byte-for-byte when anything else
        # does, or the browser never installs the new build.
        worker = staging / "sw.js"
        worker.write_text(worker.read_text().replace("__BUILD__", build_id))
        files["sw.js"] = sha256(worker.read_bytes())
        info = {
            "engine": engine_version(),
            "pyodide": pyodide["version"],
            "python": pyodide["python"],
            "commit": commit(),
            # One hash over every file, so the offline cache knows when any
            # of them changed without comparing them one by one.
            "build": build_id,
            "files": files,
        }
        (staging / "build-info.json").write_text(json.dumps(info, indent=1) + "\n")

        if output.exists():
            shutil.rmtree(output)
        staging.rename(output)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "web")
    parser.add_argument("--cache", type=Path, default=ROOT / "build" / "web-cache")
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    info = build(args.output.resolve(), args.cache.resolve())
    total = sum((args.output / name).stat().st_size for name in info["files"])
    print(f"built {args.output} -- engine {info['engine']}, "
          f"pyodide {info['pyodide']}, {len(info['files'])} files, "
          f"{total / 1e6:.1f} MB, build {info['build']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
