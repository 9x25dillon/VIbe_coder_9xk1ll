"""Archive ingestion: what the profiler will read, and what it refuses.

The unit under test is the boundary where a stranger's archive arrives, so
nearly every test here is adversarial. The honest-archive tests exist to prove
the guards do not also reject real codebases -- a bomb detector that rejects
everything passes every attack test and is useless.
"""

import struct
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from vibecoder.ingest import (
    DEFAULT_LIMITS,
    ArchiveRejected,
    IngestLimits,
    inspect_zip,
    iter_python_sources,
    looks_like_archive,
)
from vibecoder.profiler import profile_archive, profile_path

MODULE = '''\
"""A small module with something to measure."""

import json


def load(text: str) -> dict:
    """Parse a payload."""
    return json.loads(text)


class Store:
    def keys(self):
        return [k for k in self.data]
'''


class ArchiveTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def archive_from(self, members: dict, name: str = "a.zip") -> Path:
        """Build an archive from ``{member name: bytes or text}``.

        A plain dict rather than keyword arguments because every member name
        here has a dot or a slash in it, and S011 lost half an hour to
        ``profile(a_py=...)`` silently writing a file the globber never found.
        """
        path = self.root / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for member, content in members.items():
                if isinstance(content, str):
                    content = content.encode("utf-8")
                zf.writestr(member, content)
        return path


# --------------------------------------------------------------------------
# The archives we want to read
# --------------------------------------------------------------------------

class TestAnHonestArchive(ArchiveTestBase):
    def test_python_members_are_read(self):
        path = self.archive_from({"pkg/mod.py": MODULE})
        sources = dict(iter_python_sources(path))
        self.assertEqual(list(sources), ["pkg/mod.py"])
        self.assertEqual(sources["pkg/mod.py"], MODULE)

    def test_an_archive_profiles_identically_to_the_directory(self):
        """The transport must not change the measurement.

        If a zip of a checkout profiled differently from the checkout, every
        signature the game shows would depend on how the player happened to
        hand us their code.
        """
        tree = self.root / "tree"
        (tree / "pkg").mkdir(parents=True)
        (tree / "pkg" / "mod.py").write_text(MODULE, encoding="utf-8")
        (tree / "top.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")

        packed = self.archive_from({
            "pkg/mod.py": MODULE,
            "top.py": "def f(x):\n    return x + 1\n",
        })

        self.assertEqual(
            profile_path(tree).to_json(), profile_archive(packed).to_json()
        )

    def test_non_python_members_are_ignored(self):
        path = self.archive_from({
            "mod.py": MODULE,
            "README.md": "# not python\n",
            "logo.png": b"\x89PNG\r\n\x1a\n" + b"\x00" * 64,
            "data.json": '{"a": 1}',
        })
        self.assertEqual([n for n, _ in iter_python_sources(path)], ["mod.py"])

    def test_vendored_directories_are_skipped_as_they_are_on_disk(self):
        """Otherwise an archive of a repo profiles its dependencies."""
        path = self.archive_from({
            "mod.py": MODULE,
            "node_modules/thing/setup.py": "import flask\n",
            "__pycache__/mod.py": "import django\n",
            ".venv/lib/site.py": "import numpy\n",
        })
        vibe = profile_archive(path)
        self.assertEqual(vibe.files, 1)
        self.assertNotIn("flask", vibe.libraries)
        self.assertNotIn("django", vibe.libraries)

    def test_a_file_that_does_not_parse_costs_one_file_not_the_run(self):
        path = self.archive_from({"good.py": MODULE, "bad.py": "def (:\n"})
        vibe = profile_archive(path)
        self.assertEqual(vibe.files, 1)
        self.assertIn("json", vibe.libraries)

    def test_undecodable_bytes_do_not_raise(self):
        path = self.archive_from({"mod.py": b"# \xff\xfe\ndef f():\n    return 1\n"})
        vibe = profile_archive(path)
        self.assertEqual(vibe.files, 1)

    def test_a_directory_entry_is_not_a_file(self):
        path = self.root / "d.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("pkg/", "")
            zf.writestr("pkg/mod.py", MODULE)
        self.assertEqual([n for n, _ in iter_python_sources(path)], ["pkg/mod.py"])

    def test_an_empty_archive_profiles_to_an_empty_vector(self):
        path = self.root / "empty.zip"
        with zipfile.ZipFile(path, "w"):
            pass
        self.assertEqual(profile_archive(path).files, 0)

    def test_the_plan_counts_what_it_skipped(self):
        path = self.archive_from({"mod.py": MODULE, "README.md": "#\n"})
        plan = inspect_zip(path)
        self.assertEqual(plan.entries, 2)
        self.assertEqual(plan.python_files, 1)
        self.assertEqual(plan.skipped, 1)


# --------------------------------------------------------------------------
# Exit criterion 4: a bomb is rejected before expansion
# --------------------------------------------------------------------------

class TestTheBombGuard(ArchiveTestBase):
    """T2 exit criterion 4: ≤1 MB compressed, ≥1 GB expanded, rejected.

    The archive is built once for the class because deflate has to actually
    compress a gibibyte of zeros to produce an honest specimen, which takes a
    few seconds. A forged central directory would be cheaper and would prove
    less: the point is that a *real* bomb is refused.
    """

    bomb: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls._dir = tempfile.TemporaryDirectory()
        cls.bomb = Path(cls._dir.name) / "bomb.zip"
        chunk = b"\0" * (1 << 22)
        with zipfile.ZipFile(cls.bomb, "w", zipfile.ZIP_DEFLATED) as zf:
            with zf.open("payload.py", "w") as fh:
                for _ in range(256):  # 1 GiB
                    fh.write(chunk)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._dir.cleanup()

    def test_the_specimen_is_the_one_the_criterion_describes(self):
        """Deflate tops out near 1032:1, so 1 GiB cannot compress below ~1 MiB.

        Recorded as an assertion rather than a comment because if a future
        change makes the fixture smaller or weaker, the criterion it stands
        for stops being tested and nothing else would say so.
        """
        self.assertLessEqual(self.bomb.stat().st_size, 1024 * 1024)
        with zipfile.ZipFile(self.bomb) as zf:
            self.assertGreaterEqual(zf.infolist()[0].file_size, 1024 ** 3)

    def test_a_zip_bomb_is_rejected(self):
        with self.assertRaises(ArchiveRejected) as caught:
            list(iter_python_sources(self.bomb))
        self.assertEqual(caught.exception.reason, "entry-too-large")

    def test_it_is_rejected_before_a_single_member_is_opened(self):
        """The criterion is about ordering, not merely about the verdict.

        A bomb caught while inflating has already cost what it set out to
        cost, so the test fails if anything reaches for member data at all.
        """
        with mock.patch.object(
            zipfile.ZipFile, "open", side_effect=AssertionError("member opened")
        ):
            with self.assertRaises(ArchiveRejected):
                list(iter_python_sources(self.bomb))

    def test_rejection_is_decided_from_the_directory_and_so_is_immediate(self):
        started = time.perf_counter()
        with self.assertRaises(ArchiveRejected):
            inspect_zip(self.bomb)
        self.assertLess(time.perf_counter() - started, 1.0)

    def test_the_ratio_guard_catches_a_bomb_spread_across_members(self):
        """Per-file and per-archive limits alone leave a gap in the middle.

        Members each under the per-file limit, summing under the declared
        total, can still be an archive that is 400:1 compressed -- which no
        codebase is.
        """
        limits = IngestLimits(
            max_file_bytes=8 * 1024 * 1024,
            max_declared_bytes=64 * 1024 * 1024,
            ratio_floor=1024,
            max_ratio=100.0,
        )
        path = self.archive_from(
            {f"m{i}.py": b"\0" * (2 * 1024 * 1024) for i in range(8)}
        )
        with self.assertRaises(ArchiveRejected) as caught:
            inspect_zip(path, limits)
        self.assertEqual(caught.exception.reason, "compression-ratio")

    def test_a_small_well_compressing_file_is_not_a_bomb(self):
        """The ratio floor exists so that ordinary text is not an attack."""
        limits = IngestLimits(max_ratio=100.0)
        path = self.archive_from({"pad.py": "x = 1" + " " * 60_000 + "\n"})
        self.assertEqual(inspect_zip(path, limits).python_files, 1)


# --------------------------------------------------------------------------
# Everything else we refuse
# --------------------------------------------------------------------------

class TestRejection(ArchiveTestBase):
    def assertRejected(self, path, reason, limits=DEFAULT_LIMITS):
        with self.assertRaises(ArchiveRejected) as caught:
            list(iter_python_sources(path, limits))
        self.assertEqual(caught.exception.reason, reason)
        return caught.exception

    def test_parent_directory_traversal(self):
        path = self.archive_from({"../../etc/passwd.py": "x = 1\n"})
        self.assertRejected(path, "path-traversal")

    def test_a_traversal_buried_mid_path(self):
        path = self.archive_from({"pkg/../../out.py": "x = 1\n"})
        self.assertRejected(path, "path-traversal")

    def test_an_absolute_member_path(self):
        path = self.archive_from({"/etc/cron.d/mod.py": "x = 1\n"})
        self.assertRejected(path, "path-traversal")

    def test_a_backslash_separator(self):
        path = self.archive_from({"..\\..\\mod.py": "x = 1\n"})
        self.assertRejected(path, "path-traversal")

    def test_a_drive_letter(self):
        path = self.archive_from({"C:/windows/mod.py": "x = 1\n"})
        self.assertRejected(path, "path-traversal")

    def test_a_hostile_member_fails_the_whole_archive(self):
        """Not "skip that one and read the rest".

        An archive holding a traversal is not a codebase with one odd file in
        it; profiling the remainder would be deciding that hostile input is
        acceptable as long as we handle it neatly.
        """
        path = self.archive_from({"ok.py": MODULE, "../evil.py": "x = 1\n"})
        self.assertRejected(path, "path-traversal")

    def test_a_symlink_member_is_not_read_as_source(self):
        path = self.root / "link.zip"
        info = zipfile.ZipInfo("link.py")
        info.external_attr = (0o120777 << 16)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr(info, "/etc/passwd")
            zf.writestr("real.py", MODULE)
        self.assertEqual([n for n, _ in iter_python_sources(path)], ["real.py"])

    def test_an_encrypted_member_is_skipped_not_guessed(self):
        """`zipfile` cannot write encryption, so the flag is set by hand.

        Worth the byte-poking: a password-protected archive is an ordinary
        thing for somebody to upload, and reading its members would either
        raise or hand the profiler ciphertext to parse.
        """
        path = self.archive_from({"secret.py": "x = 1\n"}, name="enc.zip")
        raw = bytearray(path.read_bytes())
        # General-purpose bit flag: offset 6 of the local header, 8 of the
        # central directory entry. Bit 0 means the member is encrypted.
        for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            at = raw.index(signature) + offset
            raw[at] |= 0x1
        path.write_bytes(bytes(raw))
        with zipfile.ZipFile(path) as zf:
            self.assertTrue(zf.infolist()[0].flag_bits & 0x1)
        self.assertEqual(list(iter_python_sources(path)), [])

    def test_too_many_entries(self):
        limits = IngestLimits(max_entries=10)
        path = self.archive_from({f"m{i}.py": "x = 1\n" for i in range(11)})
        self.assertRejected(path, "too-many-entries", limits)

    def test_declared_expansion_over_the_total_limit(self):
        limits = IngestLimits(
            max_file_bytes=1024 * 1024,
            max_declared_bytes=1024,
            max_ratio=1e9,
        )
        path = self.archive_from({f"m{i}.py": "x" * 512 for i in range(4)})
        self.assertRejected(path, "declared-expansion-too-large", limits)

    def test_a_single_oversized_member(self):
        limits = IngestLimits(max_file_bytes=1024, max_ratio=1e9)
        path = self.archive_from({"big.py": "x" * 4096})
        self.assertRejected(path, "entry-too-large", limits)

    def test_an_archive_too_large_to_open(self):
        limits = IngestLimits(max_archive_bytes=32)
        path = self.archive_from({"m.py": MODULE})
        self.assertRejected(path, "archive-too-large", limits)

    def test_something_that_is_not_a_zip(self):
        path = self.root / "notes.zip"
        path.write_bytes(b"PK not really\n" + b"\x00" * 200)
        self.assertRejected(path, "not-a-zip")

    def test_a_truncated_archive(self):
        path = self.archive_from({"m.py": MODULE})
        data = path.read_bytes()
        path.write_bytes(data[: len(data) // 2])
        self.assertRejected(path, "not-a-zip")

    def test_a_missing_path_is_a_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            inspect_zip(self.root / "nope.zip")

    def test_a_directory_is_not_an_archive(self):
        with self.assertRaises(ArchiveRejected) as caught:
            inspect_zip(self.root)
        self.assertEqual(caught.exception.reason, "not-a-file")

    def test_a_large_but_honest_archive_is_not_rejected_for_its_size(self):
        """Q46's answer, and the line between the two modules.

        Every signal that an archive is an *attack* lives in the central
        directory and was judged before a byte was decompressed. What is left
        at the streaming stage is an archive that is merely large, which is
        the same situation as a large directory -- so it is profiled as far as
        the budget goes and flagged partial, rather than refused. Ingest
        decides hostile; `ProfileBudget` decides enough.
        """
        from vibecoder.profiler import ProfileBudget, profile_archive

        path = self.archive_from({f"m{i}.py": "x = 1\n" * 400 for i in range(4)})
        self.assertEqual(len(list(iter_python_sources(path))), 4)

        vibe = profile_archive(path, budget=ProfileBudget(max_total_bytes=1024))
        self.assertTrue(vibe.partial)
        self.assertIn("size budget", vibe.partial_reason)
        self.assertEqual(vibe.files_seen, 4)
        self.assertLess(vibe.files, 4)


class TestAForgedDirectory(ArchiveTestBase):
    """A central directory is written by whoever built the archive.

    Every check in `inspect_zip` believes what the directory says, because
    believing it is the only way to reach a verdict before expanding
    anything. These tests establish what that trust actually costs.

    The answer turned out to be less than expected. `zipfile.ZipExtFile` sets
    its output budget from the declared ``file_size``, so a member physically
    cannot inflate past its declaration through this reader -- and then checks
    the directory's CRC against what it inflated, so an under-declared member
    fails outright rather than arriving truncated. Forging a size costs the
    forger that member. The directory checks are therefore the real guard, and
    the bounded read is a defence against an implementation detail, which is
    worth keeping and worth being honest about.
    """

    def forge(self, declared: int, actual: int) -> Path:
        """An archive whose directory under-reports how big its member is."""
        path = self.archive_from({"m.py": b"# " + b"a" * (actual - 2)})
        raw = bytearray(path.read_bytes())
        # Uncompressed size sits at offset 22 of the local file header
        # (PK\x03\x04) and offset 24 of the central directory header
        # (PK\x01\x02). One member, so each signature appears once.
        for signature, offset in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
            at = raw.index(signature) + offset
            raw[at:at + 4] = struct.pack("<I", declared)
        path.write_bytes(bytes(raw))
        with zipfile.ZipFile(path) as zf:
            self.assertEqual(zf.infolist()[0].file_size, declared)
        return path

    def test_an_under_declared_member_is_dropped_rather_than_expanded(self):
        """The finding, pinned so a future Python changing it is visible.

        Inflating stops at the declared size and the CRC check then fails, so
        the member is lost rather than delivered short. If this ever starts
        returning source, the bounded read below has stopped being belt and
        braces and become the only thing between a forged header and an
        unbounded inflate.
        """
        limits = IngestLimits(max_file_bytes=32 * 1024, max_ratio=1e9)
        path = self.forge(declared=1024, actual=256 * 1024)
        self.assertEqual(list(iter_python_sources(path, limits)), [])

    def test_the_read_is_bounded_by_our_limit_not_by_the_declaration(self):
        """We never call ``read()`` unbounded, whatever the directory says."""
        limits = IngestLimits(max_file_bytes=32 * 1024, max_ratio=1e9)
        path = self.forge(declared=1024, actual=256 * 1024)
        requested = []
        real_read = zipfile.ZipExtFile.read

        def spy(this, n=-1):
            requested.append(n)
            return real_read(this, n)

        with mock.patch.object(zipfile.ZipExtFile, "read", spy):
            list(iter_python_sources(path, limits))
        self.assertEqual(requested, [limits.max_file_bytes + 1])

    def test_a_reader_that_ignores_the_declared_size_is_still_caught(self):
        """The bounded read is a guard against an assumption, not an attack.

        ``ZipExtFile`` bounding its own output is an implementation detail of
        one interpreter, not a documented contract. This simulates the reader
        that does not, and asserts the archive fails rather than the oversized
        member being handed onward as source.
        """
        limits = IngestLimits(max_file_bytes=1024, max_ratio=1e9)
        path = self.archive_from({"m.py": MODULE})
        oversized = b"x" * (limits.max_file_bytes + 1)
        with mock.patch.object(zipfile.ZipExtFile, "read", return_value=oversized):
            with self.assertRaises(ArchiveRejected) as caught:
                list(iter_python_sources(path, limits))
        self.assertEqual(caught.exception.reason, "expansion-mismatch")

    def test_a_member_that_will_not_inflate_costs_one_file(self):
        """One corrupt member is lost signal, not an abandoned codebase."""
        path = self.archive_from({"bad.py": MODULE, "good.py": MODULE})
        real_open = zipfile.ZipFile.open

        def fail_first(this, member, *args, **kwargs):
            if getattr(member, "filename", member) == "bad.py":
                raise zipfile.BadZipFile("bad crc")
            return real_open(this, member, *args, **kwargs)

        with mock.patch.object(zipfile.ZipFile, "open", fail_first):
            names = [n for n, _ in iter_python_sources(path)]
        self.assertEqual(names, ["good.py"])


# --------------------------------------------------------------------------
# Exit criterion 5: no source retained on disk
# --------------------------------------------------------------------------

class TestNothingIsWrittenToDisk(ArchiveTestBase):
    def test_profiling_an_archive_leaves_the_filesystem_as_it_found_it(self):
        path = self.archive_from({"pkg/mod.py": MODULE, "top.py": MODULE})
        before = sorted(p.name for p in self.root.iterdir())
        profile_archive(path)
        self.assertEqual(before, sorted(p.name for p in self.root.iterdir()))

    def test_no_extraction_api_is_used_at_all(self):
        """A structural claim, not an observation about one run.

        "The directory looked empty afterwards" is compatible with extracting
        and deleting, and a deletion is a step that can fail. Never calling
        the extraction API is what makes the commitment hold by construction.
        """
        path = self.archive_from({"mod.py": MODULE})
        boom = AssertionError("source was extracted to disk")
        with mock.patch.object(zipfile.ZipFile, "extract", side_effect=boom), \
             mock.patch.object(zipfile.ZipFile, "extractall", side_effect=boom), \
             mock.patch.object(tempfile, "mkdtemp", side_effect=boom):
            vibe = profile_archive(path)
        self.assertEqual(vibe.files, 1)


# --------------------------------------------------------------------------
# Routing
# --------------------------------------------------------------------------

class TestRouting(ArchiveTestBase):
    def test_an_archive_is_recognised_by_content_not_by_name(self):
        path = self.archive_from({"m.py": MODULE}, name="download.dat")
        self.assertTrue(looks_like_archive(path))
        self.assertEqual(profile_path(path).files, 1)

    def test_a_python_file_is_not_an_archive(self):
        path = self.root / "m.py"
        path.write_text(MODULE, encoding="utf-8")
        self.assertFalse(looks_like_archive(path))
        self.assertEqual(profile_path(path).files, 1)

    def test_a_directory_is_not_an_archive(self):
        self.assertFalse(looks_like_archive(self.root))

    def test_a_missing_path_is_not_an_archive(self):
        self.assertFalse(looks_like_archive(self.root / "nope.zip"))

    def test_a_nested_archive_is_never_opened(self):
        """The classic bomb is a zip of zips. We only read ``.py``."""
        inner = self.archive_from({"m.py": MODULE}, name="inner.zip")
        outer = self.archive_from(
            {"inner.zip": inner.read_bytes(), "real.py": MODULE}, name="outer.zip"
        )
        self.assertEqual([n for n, _ in iter_python_sources(outer)], ["real.py"])


if __name__ == "__main__":
    unittest.main()
