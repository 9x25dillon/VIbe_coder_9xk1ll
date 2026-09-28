"""Upload the browser build to a host, switching versions atomically.

Build-time tool, stdlib only; shells out to `ssh` and `scp`. The target path
becomes a symlink to a versioned sibling directory, so a visitor never loads
half of one build and half of another, and the previous build stays on disk
for an instant rollback (`ln -sfn` it back).

    python3.11 tools/web/deploy.py astra@example.com:/var/www/vibecoder --key ~/.ssh/key

The web server must already send the headers in docs/WEB.md; this tool moves
files and nothing else.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target", help="user@host:/absolute/path (becomes a symlink)")
    parser.add_argument("--key", help="ssh identity file")
    parser.add_argument("--port", default="22")
    parser.add_argument("--dir", type=Path, default=ROOT / "build" / "web")
    parser.add_argument("--keep", type=int, default=3, help="old builds to keep")
    args = parser.parse_args(argv)

    host, _, path = args.target.partition(":")
    if not host or not path.startswith("/"):
        raise SystemExit("target must look like user@host:/absolute/path")
    info = json.loads((args.dir / "build-info.json").read_text())
    release = f"{path.rstrip('/')}-{info['engine']}-{info['build']}"
    ssh = ["ssh", "-p", args.port] + (["-i", args.key] if args.key else [])
    scp = ["scp", "-P", args.port] + (["-i", args.key] if args.key else [])

    with tempfile.TemporaryDirectory() as scratch:
        bundle = Path(scratch) / "vibecoder-web.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            archive.add(args.dir, arcname=".")
        remote_bundle = f"/tmp/vibecoder-web-{info['build']}.tar.gz"
        subprocess.run(scp + [str(bundle), f"{host}:{remote_bundle}"], check=True)

    q = shlex.quote
    parent = str(Path(path).parent)
    script = " && ".join([
        f"mkdir -p {q(release)}",
        f"tar -xzf {q(remote_bundle)} -C {q(release)}",
        f"rm -f {q(remote_bundle)}",
        # Refuse to replace a real directory: the first deploy must be onto a
        # path that is free or already a symlink we made.
        f"( [ ! -e {q(path)} ] || [ -L {q(path)} ] )",
        f"ln -sfn {q(release)} {q(path)}",
        # Keep the newest few builds for rollback.
        f"ls -1dt {q(path.rstrip('/'))}-*/ 2>/dev/null | tail -n +{args.keep + 1} | xargs -r rm -rf",
        f"ls -la {q(parent)} | grep -F {q(Path(path).name)}",
    ])
    subprocess.run(ssh + [host, script], check=True)
    print(f"deployed build {info['build']} (engine {info['engine']}) to {host}:{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
