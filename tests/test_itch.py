"""The itch.io package (tools/itch/package.py), checked without the network.

The real build downloads Pyodide, which this suite must never do, so these
tests run the packager over a miniature build with the same layout and the
same strings. The guards that matter most are the refusals: a zip itch.io
would reject, or a Pyodide upgrade that moved a name the packager rewrites,
must stop the packager rather than reach an upload.
"""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT / "tools" / "itch"))

import package as itch  # noqa: E402

IMPORT = '"../vendor/pyodide/pyodide.mjs"'


def fake_build(root: Path) -> Path:
    """The web build's shape in miniature: every file the packager touches."""
    site = root / "web"
    files = {
        "index.html": '<script type="module" src="js/app.js"></script>',
        "js/app.js": 'navigator.serviceWorker.register("sw.js");',
        "css/app.css": "@font-face { src: url(../fonts/a.woff2); }",
        "sw.js": 'const BUILD = "abc";',
        "workers/engine.js": f"import {{ loadPyodide }} from {IMPORT};",
        "workers/sandbox.js": f"import {{ loadPyodide }} from {IMPORT};",
        "vendor/pyodide/pyodide.mjs":
            "let t=`${e.indexURL}pyodide.asm.mjs`;\n//# sourceMappingURL=pyodide.mjs.map\n",
        "vendor/pyodide/pyodide.asm.mjs": 'if(!e.includes("pyodide.asm.mjs"))return!1;',
        "vendor/pyodide/pyodide.asm.wasm": "\0asm",
        "build-info.json": json.dumps({"engine": "0.0.0", "build": "x", "files": {}}),
    }
    for name, text in files.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return site


class TestPackage(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.root = Path(self.scratch.name)
        self.site = fake_build(self.root)
        self.zip = self.root / "out" / "game.zip"

    def tearDown(self):
        self.scratch.cleanup()

    def contents(self) -> dict[str, str]:
        with zipfile.ZipFile(self.zip) as archive:
            return {name: archive.read(name).decode() for name in archive.namelist()}

    def test_index_is_at_the_root_and_nothing_depends_on_the_mjs_type(self):
        itch.package(self.site, self.zip)
        names = set(self.contents())
        self.assertIn("index.html", names)
        self.assertFalse([n for n in names if n.endswith(".mjs")])
        self.assertIn("vendor/pyodide/pyodide.js", names)
        self.assertIn("vendor/pyodide/pyodide.asm.js", names)

    def test_every_reference_to_a_renamed_file_follows_it(self):
        itch.package(self.site, self.zip)
        files = self.contents()
        for worker in ("workers/engine.js", "workers/sandbox.js"):
            self.assertIn('"../vendor/pyodide/pyodide.js"', files[worker])
        self.assertIn("pyodide.asm.js`", files["vendor/pyodide/pyodide.js"])
        self.assertIn('includes("pyodide.asm.js")', files["vendor/pyodide/pyodide.asm.js"])

    def test_the_offline_worker_is_left_out(self):
        itch.package(self.site, self.zip)
        self.assertNotIn("sw.js", self.contents())

    def test_build_info_lists_exactly_what_ships(self):
        itch.package(self.site, self.zip)
        files = self.contents()
        info = json.loads(files.pop("build-info.json"))
        self.assertEqual(info["target"], "itch.io")
        self.assertEqual(set(info["files"]), set(files))

    def test_the_source_build_is_not_modified(self):
        before = {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()}
        itch.package(self.site, self.zip)
        after = {p: p.read_bytes() for p in self.site.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_one_build_gives_one_zip(self):
        itch.package(self.site, self.zip)
        first = self.zip.read_bytes()
        itch.package(self.site, self.zip)
        self.assertEqual(first, self.zip.read_bytes())

    # ------------------------------------------------------------ refusals

    def test_a_moved_pyodide_name_is_refused_not_shipped(self):
        loader = self.site / "vendor/pyodide/pyodide.mjs"
        loader.write_text("let t=`${e.indexURL}pyodide.asm.v2.mjs`;")
        with self.assertRaises(itch.PackageError) as caught:
            itch.package(self.site, self.zip)
        self.assertIn("pyodide.asm.mjs", str(caught.exception))
        self.assertFalse(self.zip.exists())

    def test_a_missing_index_is_refused(self):
        (self.site / "index.html").unlink()
        with self.assertRaises(itch.PackageError):
            itch.package(self.site, self.zip)

    def test_a_root_relative_reference_is_refused(self):
        (self.site / "index.html").write_text('<link rel="stylesheet" href="/css/app.css">')
        with self.assertRaises(itch.PackageError) as caught:
            itch.package(self.site, self.zip)
        self.assertIn("root-relative", str(caught.exception))

    def test_a_protocol_relative_url_is_not_mistaken_for_a_root_path(self):
        (self.site / "index.html").write_text('<a href="//example.org/">x</a><script src="js/app.js"></script>')
        itch.package(self.site, self.zip)

    def test_itch_limits_are_enforced_before_writing(self):
        for limit, value in (("MAX_FILES", 3), ("MAX_FILE", 3), ("MAX_TOTAL", 10), ("MAX_PATH", 8)):
            with self.subTest(limit=limit), mock.patch.object(itch, limit, value):
                with self.assertRaises(itch.PackageError):
                    itch.package(self.site, self.zip)
                self.assertFalse(self.zip.exists())

    def test_a_directory_that_is_not_a_build_is_refused(self):
        with self.assertRaises(itch.PackageError):
            itch.package(self.root, self.zip)


class TestAgainstTheRealClient(unittest.TestCase):
    """The strings the packager rewrites in our own files must exist as written."""

    def test_each_worker_imports_pyodide_exactly_as_the_packager_expects(self):
        for name, text, _, expected in itch.PATCHES:
            if not name.startswith("workers/"):
                continue
            with self.subTest(worker=name):
                self.assertEqual((WEB / name).read_text().count(text), expected)

    def test_the_page_survives_a_refused_service_worker(self):
        app = (WEB / "js" / "app.js").read_text()
        self.assertIn('navigator.serviceWorker.register("sw.js").catch(', app)

    def test_the_engine_boots_without_storage(self):
        """An embed can be refused IndexedDB; that must cost the save, not the game."""
        engine = (WEB / "workers" / "engine.js").read_text()
        self.assertIn("persistent = await mountSaves();", engine)
        self.assertIn("if (!persistent) return;", engine)
        mount = engine[engine.index("async function mountSaves()"):engine.index("async function boot()")]
        self.assertIn("catch", mount)
        self.assertIn("return false;", mount)


if __name__ == "__main__":
    unittest.main()
