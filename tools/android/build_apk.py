"""Build the Android app: the browser build wrapped in a WebView, signed.

Build-time tool, stdlib only, and no Gradle: the app is one Java class, a
manifest and some resources, so the SDK's own tools are driven directly --
`aapt2` for resources, `javac` and `d8` for code, `zipalign` and `apksigner`
to finish. Every step is visible here and none of it downloads anything.

    python3.11 tools/android/build_apk.py              # release, signed
    python3.11 tools/android/build_apk.py --debug      # debuggable, separate app id
    python3.11 tools/android/build_apk.py --install    # ... and adb install it

The release key lives outside the repository, in ~/.config/vibecoder/. It is
created on first use. **Back it up**: an app signed with a lost key can never
be updated in place, only uninstalled and reinstalled, which deletes progress.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android"
sys.path.insert(0, str(ROOT / "tools" / "web"))
import build as web_build  # noqa: E402
import icon  # noqa: E402

PACKAGE = "com.astraarcana.vibecoder"
MIN_SDK = 26
TARGET_SDK = 36
KEYS = Path(os.environ.get("VIBECODER_KEYS", Path.home() / ".config" / "vibecoder"))


def sdk() -> Path:
    for candidate in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
                      Path.home() / "Android" / "Sdk"):
        if candidate and Path(candidate, "platforms").is_dir():
            return Path(candidate)
    raise SystemExit("no Android SDK: set ANDROID_HOME")


def newest(directory: Path) -> Path:
    def key(path: Path):
        return tuple(int(p) if p.isdigit() else 0 for p in path.name.replace("-", ".").split("."))
    return sorted((p for p in directory.iterdir() if p.is_dir()), key=key)[-1]


def run(*argv, **kwargs) -> subprocess.CompletedProcess:
    printable = " ".join(str(a) for a in argv)
    print(f"  $ {printable[:160]}", file=sys.stderr)
    return subprocess.run([str(a) for a in argv], check=True, **kwargs)


def version_code(version: str) -> int:
    """0.2.0 -> 200, 1.4.12 -> 10412: monotonic for as long as parts stay < 100."""
    major, minor, patch = (int(p) for p in version.split(".")[:3])
    return major * 10000 + minor * 100 + patch


def release_key() -> tuple[Path, Path]:
    """The signing key and its password file, created once with keytool."""
    keystore = KEYS / "android-release.jks"
    password = KEYS / "android-release.pass"
    if keystore.exists() and password.exists():
        return keystore, password
    KEYS.mkdir(parents=True, exist_ok=True)
    os.chmod(KEYS, 0o700)
    password.write_text(secrets.token_urlsafe(32) + "\n")
    os.chmod(password, 0o600)
    run("keytool", "-genkeypair", "-keystore", keystore, "-storetype", "PKCS12",
        "-alias", "vibecoder", "-keyalg", "RSA", "-keysize", "4096",
        "-validity", "10000", "-dname", "CN=VibeCoder, O=Astra Arcana",
        f"-storepass:file", password, f"-keypass:file", password)
    os.chmod(keystore, 0o600)
    print(f"\n  created release key {keystore}\n  BACK IT UP -- updates are signed with it.\n",
          file=sys.stderr)
    return keystore, password


def debug_key() -> tuple[Path, Path]:
    keystore = Path.home() / ".android" / "debug.keystore"
    password = KEYS / "android-debug.pass"
    KEYS.mkdir(parents=True, exist_ok=True)
    password.write_text("android\n")
    if not keystore.exists():
        keystore.parent.mkdir(parents=True, exist_ok=True)
        run("keytool", "-genkeypair", "-keystore", keystore, "-alias", "androiddebugkey",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000",
            "-dname", "CN=Android Debug,O=Android,C=US",
            "-storepass", "android", "-keypass", "android")
    return keystore, password


def build(*, debug: bool, web: Path | None, output: Path) -> Path:
    tools = newest(sdk() / "build-tools")
    platform = sdk() / "platforms" / f"android-{TARGET_SDK}" / "android.jar"
    if not platform.exists():
        platform = newest(sdk() / "platforms") / "android.jar"
    version = web_build.engine_version()

    work = ROOT / "build" / "android" / ("debug" if debug else "release")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    if web is None:
        web = ROOT / "build" / "web"
        web_build.build(web, ROOT / "build" / "web-cache")

    # Resources, plus the launcher icon drawn from the same pixel map as the web's.
    res = work / "res"
    shutil.copytree(ANDROID / "res", res)
    (res / "drawable").mkdir(exist_ok=True)
    (res / "drawable" / "ic_launcher_foreground.xml").write_text(icon.android_foreground())
    (res / "drawable" / "ic_launcher_monochrome.xml").write_text(icon.android_monochrome())

    # The page, the engine and Pyodide. The offline worker is for hosted
    # builds only; the app's files are already on the device.
    assets = work / "assets"
    shutil.copytree(web, assets / "www", ignore=shutil.ignore_patterns("sw.js"))

    compiled = work / "compiled.zip"
    run(tools / "aapt2", "compile", "--dir", res, "-o", compiled)
    unsigned = work / "unsigned.apk"
    link = [tools / "aapt2", "link", "-o", unsigned, "-I", platform,
            "--manifest", ANDROID / "AndroidManifest.xml",
            "--min-sdk-version", MIN_SDK, "--target-sdk-version", TARGET_SDK,
            "--version-code", version_code(version), "--version-name", version,
            "-A", assets, "--java", work / "gen", compiled]
    if debug:
        link += ["--debug-mode", "--rename-manifest-package", f"{PACKAGE}.debug"]
    run(*link)

    classes = work / "classes"
    sources = [*sorted((ANDROID / "src").rglob("*.java")), *sorted((work / "gen").rglob("*.java"))]
    run("javac", "--release", "11", "-classpath", platform, "-d", classes,
        "-Xlint:-options", *sources)
    dex = work / "dex"
    dex.mkdir()
    run(tools / "d8", "--release", "--min-api", MIN_SDK, "--lib", platform,
        "--output", dex, *sorted(classes.rglob("*.class")))
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as apk:
        apk.write(dex / "classes.dex", "classes.dex")

    aligned = work / "aligned.apk"
    run(tools / "zipalign", "-P", "16", "-f", "4", unsigned, aligned)
    keystore, password = debug_key() if debug else release_key()
    output.parent.mkdir(parents=True, exist_ok=True)
    # One password for store and key. apksigner reads a *second line* for
    # --key-pass when both name the same file, so the key's is left implied.
    run(tools / "apksigner", "sign", "--ks", keystore, "--ks-pass", f"file:{password}",
        "--out", output, aligned)
    run(tools / "apksigner", "verify", "--print-certs", output,
        stdout=subprocess.DEVNULL)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--debug", action="store_true",
                        help="debuggable build under a separate app id, debug-signed")
    parser.add_argument("--web", type=Path, help="use an existing browser build")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--install", action="store_true", help="adb install when done")
    args = parser.parse_args(argv)
    version = web_build.engine_version()
    name = f"vibecoder-{version}{'-debug' if args.debug else ''}.apk"
    output = (args.output or ROOT / "dist" / name).resolve()
    apk = build(debug=args.debug, web=args.web, output=output)
    print(f"built {apk} ({apk.stat().st_size / 1e6:.1f} MB)")
    if args.install:
        run("adb", "install", "-r", apk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
