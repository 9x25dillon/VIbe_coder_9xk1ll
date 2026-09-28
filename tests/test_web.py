"""Contracts of the browser and Android builds (T9) that Python can check.

The client is JavaScript and is exercised by `tools/web/smoke.py` (headless
Chromium) and `tools/android/device_smoke.py` (a real phone); neither runs in
this suite, which must pass on any host with nothing but Python. What *can* be
checked here are the promises the build makes in prose -- one security policy
in three places, no network, no third-party origin, every engine call the
page makes existing on the engine -- because a promise that is only written
down drifts the first time somebody edits one of the three places.
"""

import ast
import hashlib
import json
import re
import sys
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ANDROID = ROOT / "android"
sys.path.insert(0, str(ROOT / "tools" / "web"))

import build as web_build  # noqa: E402
import icon  # noqa: E402
import serve  # noqa: E402

from vibecoder.service import Service  # noqa: E402


def directives(policy: str) -> dict[str, str]:
    parsed = {}
    for part in policy.split(";"):
        words = part.split()
        if words:
            parsed[words[0]] = " ".join(sorted(words[1:]))
    return parsed


class TestOnePolicy(unittest.TestCase):
    """The page, the local server and the Android shell send the same CSP."""

    def page_policy(self) -> str:
        text = (WEB / "index.html").read_text()
        return re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', text).group(1)

    def android_policy(self) -> str:
        java = (ANDROID / "src" / "com" / "astraarcana" / "vibecoder" / "MainActivity.java").read_text()
        block = re.search(r"static final String CSP = (.*?);\n", java, re.S).group(1)
        return "".join(re.findall(r'"([^"]*)"', block))

    def test_the_three_policies_agree(self):
        server = directives(serve.CSP)
        # A <meta> policy cannot carry frame-ancestors; browsers ignore it there.
        server.pop("frame-ancestors")
        self.assertEqual(directives(self.page_policy()), server)
        self.assertEqual(directives(self.android_policy()), server)

    def test_webassembly_may_compile_and_nothing_else_is_evaluated(self):
        script = directives(serve.CSP)["script-src"].split()
        self.assertIn("'wasm-unsafe-eval'", script)
        self.assertNotIn("'unsafe-eval'", script)
        self.assertNotIn("'unsafe-inline'", script)

    def test_no_directive_names_another_origin(self):
        for value in directives(serve.CSP).values():
            for source in value.split():
                self.assertFalse(source.startswith(("http", "*")), source)


class TestNoNetwork(unittest.TestCase):
    def test_the_client_references_no_external_url(self):
        pattern = re.compile(r"https?://(?!www\.w3\.org/2000/svg)")
        for path in WEB.rglob("*"):
            if path.suffix in {".html", ".js", ".css", ".py", ".webmanifest"}:
                with self.subTest(path=path.name):
                    self.assertIsNone(pattern.search(path.read_text()), path)

    def test_the_app_cannot_open_a_socket(self):
        manifest = (ANDROID / "AndroidManifest.xml").read_text()
        self.assertNotIn("android.permission.INTERNET", manifest)

    def test_player_code_is_not_sent_to_cloud_backup(self):
        manifest = (ANDROID / "AndroidManifest.xml").read_text()
        self.assertIn('android:allowBackup="false"', manifest)

    def test_every_pinned_asset_is_https_with_a_sha256(self):
        lock = json.loads((ROOT / "tools" / "web" / "assets.lock.json").read_text())
        for name, asset in lock.items():
            with self.subTest(asset=name):
                self.assertTrue(asset["url"].startswith("https://"))
                self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")

    def test_a_mismatched_download_is_refused(self):
        cache = ROOT / "build" / "test-web-cache"
        cache.mkdir(parents=True, exist_ok=True)
        digest = "0" * 64
        (cache / digest).write_bytes(b"tampered")
        try:
            with self.assertRaises((SystemExit, OSError)):
                web_build.fetch("https://invalid.invalid/x", digest, cache)
            self.assertFalse((cache / digest).exists(), "a bad cache entry must be dropped")
        finally:
            for leftover in cache.iterdir():
                leftover.unlink()
            cache.rmdir()


class TestEngineSurface(unittest.TestCase):
    """The page can only call what the engine exposes, and only that."""

    def exposed(self) -> set[str]:
        tree = ast.parse((WEB / "boot.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "METHODS":
                names = node.value.generators[0].iter
                return {element.value for element in names.elts}
        raise AssertionError("boot.py has no METHODS")

    def test_every_exposed_name_is_a_service_method(self):
        for name in self.exposed():
            self.assertTrue(callable(getattr(Service, name, None)), name)

    def test_nothing_private_is_exposed(self):
        self.assertFalse([n for n in self.exposed() if n.startswith("_")])

    def test_every_call_the_page_makes_is_exposed(self):
        calls = set()
        for path in (WEB / "js").glob("*.js"):
            calls.update(re.findall(r'\.call\("([a-z_]+)"', path.read_text()))
        self.assertTrue(calls, "the scan stopped finding calls")
        self.assertEqual(calls - self.exposed(), set())


class TestBundle(unittest.TestCase):
    def test_the_engine_archive_is_the_package(self):
        archive = zipfile.ZipFile(BytesIO(web_build.engine_archive()))
        names = set(archive.namelist())
        self.assertIn("vibecoder/service.py", names)
        self.assertIn("vibecoder/_harness.py", names)
        self.assertIn("vibecoder/levels/w1_l1_greet.py", names)
        self.assertFalse([n for n in names if "__pycache__" in n or not n.endswith(".py")])
        packaged = {p.relative_to(ROOT).as_posix() for p in (ROOT / "vibecoder").rglob("*.py")
                    if "__pycache__" not in p.parts}
        self.assertEqual(names, packaged)

    def test_the_engine_archive_is_reproducible(self):
        first = hashlib.sha256(web_build.engine_archive()).hexdigest()
        self.assertEqual(first, hashlib.sha256(web_build.engine_archive()).hexdigest())

    def test_every_local_reference_in_the_page_exists(self):
        html = (WEB / "index.html").read_text()
        generated = {"icon.svg", "icon-192.png", "fonts/JetBrainsMono-Regular.woff2",
                     "fonts/VT323-Regular.woff2"}
        for reference in re.findall(r'(?:href|src)="([^"#:]+)"', html):
            with self.subTest(reference=reference):
                self.assertTrue((WEB / reference).exists() or reference in generated, reference)

    def test_the_offline_worker_is_stamped_per_build(self):
        self.assertIn('const BUILD = "__BUILD__";', (WEB / "sw.js").read_text())

    def test_bundled_licences_are_present(self):
        for name in ("VibeCoder-EPL-2.0.txt", "Pyodide-MPL-2.0.txt",
                     "JetBrainsMono-OFL.txt", "VT323-OFL.txt"):
            self.assertGreater((WEB / "licenses" / name).stat().st_size, 1000, name)


class TestIcon(unittest.TestCase):
    def test_the_pixel_map_is_square(self):
        self.assertEqual({len(row) for row in icon.ART}, {len(icon.ART)})

    def test_png_is_a_valid_png_of_the_asked_size(self):
        data = icon.png(48)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
        self.assertEqual((width, height), (48, 48))

    def test_the_launcher_art_stays_inside_the_safe_zone(self):
        """Adaptive icons are cropped to a 66dp circle-ish zone of 108dp."""
        numbers = [float(n) for n in re.findall(r"[MHhVv](-?[\d.]+)", icon.android_foreground())]
        coordinates = [n for n in numbers if n > 4]
        self.assertGreaterEqual(min(coordinates), 21)
        self.assertLessEqual(max(coordinates), 87)
