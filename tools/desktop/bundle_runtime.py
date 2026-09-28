"""Build a relocatable CPython + engine bundle from a checksum-pinned archive.

Build-time tool, stdlib only. Does not freeze Python, install packages, move
player data or obtain signing keys. The output is a runtime candidate, not a
signed desktop installer. Native smoke testing is required after relocation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LOCK = Path(__file__).with_name('python-runtime.lock.json')


def host_target() -> str:
    machine = platform.machine().lower()
    arch = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(machine, machine)
    suffix = {'Darwin': 'apple-darwin', 'Windows': 'pc-windows-msvc',
              'Linux': 'unknown-linux-gnu'}[platform.system()]
    return f'{arch}-{suffix}'


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def build(target: str, output: Path, cache: Path) -> Path:
    """Verify before extraction; publish a complete bundle with one rename."""
    lock = json.loads(LOCK.read_text())
    asset = lock['targets'][target]
    output = output.resolve()
    if output.exists():
        raise FileExistsError(f'output already exists; choose a new path: {output}')
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{asset['sha256']}.tar.gz"
    if not archive.exists():
        with tempfile.NamedTemporaryFile(dir=cache, delete=False) as temporary:
            download = Path(temporary.name)
            try:
                request = urllib.request.Request(asset['url'], headers={'User-Agent': 'VibeCoder-build'})
                with urllib.request.urlopen(request, timeout=60) as response:
                    shutil.copyfileobj(response, temporary)
            except BaseException:
                temporary.close()
                download.unlink(missing_ok=True)
                raise
        if checksum(download) != asset['sha256']:
            download.unlink()
            raise ValueError('runtime download checksum does not match the lock')
        download.replace(archive)
    if checksum(archive) != asset['sha256']:
        raise ValueError('cached runtime checksum does not match the lock')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.runtime-') as directory:
        stage = Path(directory) / 'bundle'
        stage.mkdir()
        with tarfile.open(archive, 'r:gz') as source:
            source.extractall(stage, filter='data')
        shutil.copytree(ROOT / 'vibecoder', stage / 'app' / 'vibecoder',
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for name in ('launcher.py', 'smoke.py'):
            shutil.copy2(Path(__file__).with_name(name), stage / name)
        shutil.copy2(ROOT / 'LICENSE', stage / 'VIBECODER-LICENSE')
        # Keep upstream Python/dependency notices exactly as distributed.
        # Inventory every bundled file so candidates can be audited and signed.
        inventory = {str(path.relative_to(stage)).replace('\\', '/'): checksum(path)
                     for path in sorted(stage.rglob('*')) if path.is_file()}
        manifest = {'python': lock['python'], 'release': lock['release'],
                    'target': target, **asset, 'files': inventory}
        (stage / 'runtime.json').write_text(json.dumps(manifest, indent=2) + '\n')
        stage.rename(output)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', default=host_target())
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cache', type=Path, default=ROOT / 'build' / 'runtime-cache')
    args = parser.parse_args()
    output = args.output or ROOT / 'build' / f'runtime-{args.target}'
    print(build(args.target, output, args.cache))


if __name__ == '__main__':
    main()
