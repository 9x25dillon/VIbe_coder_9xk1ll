"""Upload the browser build to a host, switching versions atomically.

Build-time tool, stdlib only; shells out to `ssh` and `scp`. The target is a
*releases directory*: each build is unpacked into `<target>/<engine>-<build>`
and a relative symlink `<target>/current` is swapped to it in one `rename`.
The web server's root is `<target>/current`.

The swap happens *inside* the directory rather than at its path because the
target is typically bind-mounted into a container, and Docker resolves a
mount's source when the container starts: a symlink replaced at the mount
point would go unseen until a restart. A link inside the mount is resolved by
the web server on every request, so a deploy needs no restart, a visitor never
loads half of one build and half of another, and rolling back is pointing
`current` at the previous directory.

    python3.11 tools/web/deploy.py astra@host:/home/astra/astro-aae/vibecoder-web \
        --key ~/.ssh/astra_hetzner

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
    parser.add_argument("target", help="user@host:/absolute/releases/dir")
    parser.add_argument("--key", help="ssh identity file")
    parser.add_argument("--port", default="22")
    parser.add_argument("--dir", type=Path, default=ROOT / "build" / "web")
    parser.add_argument("--keep", type=int, default=3, help="builds to keep, current included")
    args = parser.parse_args(argv)

    host, _, releases = args.target.partition(":")
    if not host or not releases.startswith("/"):
        raise SystemExit("target must look like user@host:/absolute/path")
    releases = releases.rstrip("/")
    info = json.loads((args.dir / "build-info.json").read_text())
    name = f"{info['engine']}-{info['build']}"
    ssh = ["ssh", "-p", args.port] + (["-i", args.key] if args.key else [])
    scp = ["scp", "-q", "-P", args.port] + (["-i", args.key] if args.key else [])

    with tempfile.TemporaryDirectory() as scratch:
        bundle = Path(scratch) / "vibecoder-web.tar.gz"
        with tarfile.open(bundle, "w:gz") as archive:
            archive.add(args.dir, arcname=".")
        remote_bundle = f"/tmp/vibecoder-web-{info['build']}.tar.gz"
        subprocess.run(scp + [str(bundle), f"{host}:{remote_bundle}"], check=True)

    q = shlex.quote
    staging = f"{releases}/.incoming-{name}"
    script = " && ".join([
        f"mkdir -p {q(releases)}",
        f"rm -rf {q(staging)} && mkdir {q(staging)}",
        f"tar -xzf {q(remote_bundle)} -C {q(staging)}",
        f"rm -f {q(remote_bundle)}",
        # World-readable: the web server in the container is another user.
        f"chmod -R a+rX {q(staging)}",
        f"rm -rf {q(releases + '/' + name)} && mv {q(staging)} {q(releases + '/' + name)}",
        # Build the new link beside the old one, then rename over it: rename
        # is atomic, `ln -sfn` is an unlink followed by a create.
        f"ln -sfn {q(name)} {q(releases + '/.current-next')}",
        f"mv -T {q(releases + '/.current-next')} {q(releases + '/current')}",
        # Prune the oldest builds, never the one `current` points at.
        f"cd {q(releases)} && ls -1dt */ | sed 's#/$##' | grep -vx {q(name)} "
        f"| tail -n +{max(args.keep, 1)} | xargs -r rm -rf",
        f"ls -la {q(releases)}",
    ])
    subprocess.run(ssh + [host, script], check=True)
    print(f"deployed build {info['build']} (engine {info['engine']}) -> {host}:{releases}/current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
