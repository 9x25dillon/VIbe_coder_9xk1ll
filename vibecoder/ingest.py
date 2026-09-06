"""Reading Python source out of an archive somebody else built.

The profiler's input is other people's code, and T2 W5 widens that from a
directory on disk to a ``.zip`` a stranger uploaded. An archive is not a
directory: it can claim to hold a gigabyte in a megabyte, name a member
``../../.ssh/authorized_keys``, or hold two hundred thousand entries whose
only purpose is to be counted.

Two properties do most of the work here, and both are structural rather than
careful:

**Nothing is written to disk.** Members are decompressed into memory, handed
to the profiler as strings, and dropped. There is no extraction directory to
clean up and therefore no window in which a cleanup can fail, which is how
T2's exit criterion 5 -- no source retained afterwards -- is met by
construction instead of by remembering. It also makes path traversal
unreachable: a member called ``../../etc/passwd`` is a string we reject, not a
file we nearly wrote.

**Only ``.py`` members are ever opened.** A nested archive, a 4 GB blob of
zeros, an ELF binary: none of them are read, because the profiler has no use
for them. That shrinks the decompression surface to Python source, which is
the one thing here we actually want.

The guards below are what remains after those two. They run in two stages: the
central directory is judged *before* a single byte is decompressed, and then
the bytes that arrive are measured against what the directory claimed, because
a header is written by whoever built the archive and can say anything.

This module imports nothing from the ``vibecoder`` package. It is the boundary
where untrusted input arrives, and it should be readable and testable without
the game around it.
"""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator


@dataclass(frozen=True)
class IngestLimits:
    """What an archive is allowed to cost before we stop believing in it.

    Every field stops a distinct failure, and the defaults are sized for a
    source repository rather than for an archive in general -- a 500 MB
    expansion is already far more Python than anyone has written by hand, and
    the point of a limit is to be reached by hostile input and not by real
    input.
    """

    #: The archive as it sits on disk. Bounds the central directory read, and
    #: therefore how much work a caller can cause before any check runs.
    max_archive_bytes: int = 200 * 1024 * 1024

    #: Entries in the central directory, ``.py`` or otherwise. A million empty
    #: members expand to nothing and still cost a million iterations.
    max_entries: int = 50_000

    #: Total expansion the archive *declares*, across every member. This is
    #: the zip-bomb guard proper: it is decided from the central directory,
    #: with nothing decompressed.
    max_declared_bytes: int = 500 * 1024 * 1024

    #: One member, expanded. The largest file in CPython's own ``Lib`` is
    #: under 1 MB, so a 4 MB Python file is already an outlier.
    max_file_bytes: int = 4 * 1024 * 1024

    #: Python source actually decompressed and held, across the whole run.
    #: The last line of defence if every declared size is a lie.
    max_source_bytes: int = 64 * 1024 * 1024

    #: Declared expansion divided by compressed size. Deflate tops out near
    #: 1032:1 on repetitive input; prose and code land between 2:1 and 5:1, so
    #: 100:1 is far outside anything a codebase does by accident.
    max_ratio: float = 100.0

    #: The ratio is only meaningful once an archive is big enough for it to
    #: mean something. A single 12 KB file that compresses 200:1 is a text
    #: file full of spaces, not an attack.
    ratio_floor: int = 1 * 1024 * 1024


DEFAULT_LIMITS = IngestLimits()


class ArchiveRejected(Exception):
    """An archive we refuse to read, and the specific reason why.

    ``reason`` is a stable slug so that tests and callers can branch on the
    cause without matching prose; ``str(exc)`` is the sentence a player sees.
    They are separate because the wording is presentation and the reason is
    behaviour, and only one of them should be safe to reword.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class ArchivePlan:
    """The verdict on an archive's central directory: what we will read.

    Produced before anything is decompressed. ``members`` holds only the
    ``.py`` entries that survived every check, so the streaming stage has no
    decisions left to make about *whether* to open something.
    """

    path: Path
    members: tuple[zipfile.ZipInfo, ...]
    entries: int
    declared_bytes: int
    compressed_bytes: int
    skipped: int

    @property
    def python_files(self) -> int:
        return len(self.members)


def looks_like_archive(path: str | Path) -> bool:
    """Whether this path should be read as an archive rather than as source.

    Decided by content, not by name: ``zipfile.is_zipfile`` looks for the
    end-of-central-directory record, so a ``.whl``, an ``.egg`` or a download
    that lost its extension all route correctly, and a ``.py`` file never
    does. It reads the tail of the file, so it stays cheap however large the
    file is.
    """
    path = Path(path)
    if not path.is_file():
        return False
    try:
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def _unsafe_path(name: str) -> str | None:
    """Why this member name is hostile, or ``None`` if it is ordinary.

    Nothing here is written to disk, so none of these can actually traverse
    anywhere. They are rejected because an archive containing them is not a
    codebase somebody is asking us to profile, and continuing to read it would
    mean deciding that a hostile archive is fine as long as we happen to be
    holding it carefully.
    """
    if not name or name in (".", ".."):
        return "empty or dot member name"
    if name.startswith("/") or name.startswith("\\"):
        return f"absolute member path: {name!r}"
    # The zip spec says members use forward slashes. A backslash is either a
    # Windows path smuggled through or a separator we would disagree with an
    # extractor about, and both are reasons not to proceed.
    if "\\" in name:
        return f"backslash in member path: {name!r}"
    if len(name) > 1 and name[1] == ":":
        return f"drive-letter member path: {name!r}"
    if ".." in PurePosixPath(name).parts:
        return f"parent-directory traversal: {name!r}"
    return None


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    """A symlink member stores its target as its contents.

    We never write it, so it cannot point anywhere, but reading it would feed
    the profiler a path string wearing a ``.py`` name.
    """
    return stat.S_ISLNK(info.external_attr >> 16)


def inspect_zip(
    path: str | Path, limits: IngestLimits = DEFAULT_LIMITS
) -> ArchivePlan:
    """Judge an archive from its central directory alone, expanding nothing.

    Raises `ArchiveRejected` before any member is opened. That ordering is the
    whole point: a bomb that is only detected while inflating has already cost
    what it set out to cost.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no such path: {path}")
    if not path.is_file():
        raise ArchiveRejected("not-a-file", f"not a file: {path}")

    size = path.stat().st_size
    if size > limits.max_archive_bytes:
        raise ArchiveRejected(
            "archive-too-large",
            f"archive is {size:,} bytes, over the "
            f"{limits.max_archive_bytes:,} byte limit",
        )

    try:
        with zipfile.ZipFile(path) as zf:
            infos = zf.infolist()
    except (zipfile.BadZipFile, OSError, ValueError) as exc:
        raise ArchiveRejected("not-a-zip", f"not a readable zip archive: {exc}")

    if len(infos) > limits.max_entries:
        raise ArchiveRejected(
            "too-many-entries",
            f"archive holds {len(infos):,} entries, over the "
            f"{limits.max_entries:,} entry limit",
        )

    declared = 0
    compressed = 0
    members: list[zipfile.ZipInfo] = []
    skipped = 0

    for info in infos:
        problem = _unsafe_path(info.filename)
        if problem is not None:
            raise ArchiveRejected("path-traversal", problem)

        declared += info.file_size
        compressed += info.compress_size

        if info.file_size > limits.max_file_bytes:
            raise ArchiveRejected(
                "entry-too-large",
                f"{info.filename!r} declares {info.file_size:,} bytes, over "
                f"the {limits.max_file_bytes:,} byte per-file limit",
            )

        if info.is_dir() or _is_symlink(info):
            skipped += 1
            continue
        if not info.filename.lower().endswith(".py"):
            skipped += 1
            continue
        # An encrypted member cannot be read without a password we will never
        # have, and guessing is not a feature.
        if info.flag_bits & 0x1:
            skipped += 1
            continue
        members.append(info)

    if declared > limits.max_declared_bytes:
        raise ArchiveRejected(
            "declared-expansion-too-large",
            f"archive declares {declared:,} bytes expanded, over the "
            f"{limits.max_declared_bytes:,} byte limit",
        )

    if declared >= limits.ratio_floor and compressed > 0:
        ratio = declared / compressed
        if ratio > limits.max_ratio:
            raise ArchiveRejected(
                "compression-ratio",
                f"archive expands {ratio:,.0f}:1, over the "
                f"{limits.max_ratio:,.0f}:1 limit",
            )

    return ArchivePlan(
        path=path,
        members=tuple(members),
        entries=len(infos),
        declared_bytes=declared,
        compressed_bytes=compressed,
        skipped=skipped,
    )


def _stream(plan: ArchivePlan, limits: IngestLimits) -> Iterator[tuple[str, str]]:
    """Decompress the planned members, measuring what actually arrives.

    Every read is bounded by `IngestLimits.max_file_bytes` regardless of what
    the directory promised, because the directory was written by whoever built
    the archive. A member that overruns its declaration is the signature of a
    forged header, so it fails the whole archive rather than being skipped:
    at that point the central directory we made every other decision from is
    known to be untrue.
    """
    budget = limits.max_source_bytes
    with zipfile.ZipFile(plan.path) as zf:
        for info in plan.members:
            try:
                with zf.open(info) as handle:
                    # One byte past the limit is how we tell "at the limit"
                    # from "truncated at the limit".
                    raw = handle.read(limits.max_file_bytes + 1)
            except (zipfile.BadZipFile, OSError, ValueError, RuntimeError):
                # A member that will not inflate is one file's worth of
                # signal lost, not a reason to abandon the codebase.
                continue

            if len(raw) > limits.max_file_bytes:
                raise ArchiveRejected(
                    "expansion-mismatch",
                    f"{info.filename!r} expands past its declared "
                    f"{info.file_size:,} bytes",
                )

            budget -= len(raw)
            if budget < 0:
                raise ArchiveRejected(
                    "source-budget-exhausted",
                    f"archive holds more than {limits.max_source_bytes:,} "
                    f"bytes of Python source",
                )

            yield info.filename, raw.decode("utf-8", errors="replace")


def iter_python_sources(
    path: str | Path, limits: IngestLimits = DEFAULT_LIMITS
) -> Iterator[tuple[str, str]]:
    """Yield ``(member name, source)`` for every readable ``.py`` in an archive.

    The inspection is eager and the reading is lazy, deliberately. A generator
    that did both would defer its rejection until the caller asked for the
    first member, which would make "rejected before expansion" depend on how
    the caller happened to write their loop.
    """
    plan = inspect_zip(path, limits)
    return _stream(plan, limits)
