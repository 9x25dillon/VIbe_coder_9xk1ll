"""Execution backends -- the transport seam named in ARCHITECTURE.md.

``runner.run_code`` decides *what* to execute and how to interpret the result.
This module decides *where* it runs. Every backend answers the same narrow
question: given the harness script, what argv spawns it under this isolation
regime? The harness itself is identical in all three -- it reads one JSON
object on stdin and writes one on stdout, and it never imports the
``vibecoder`` package (N2). That is what makes the transport swappable at all.

    SubprocessBackend  a fresh interpreter. Fast, no isolation beyond rlimits.
                       Correct for code the player wrote on their own machine.
    BwrapBackend       bubblewrap namespaces: no network, no host filesystem
                       beyond a read-only interpreter, a tmpfs workdir.
    DockerBackend      the same properties via a container image, for hosts
                       that have a daemon but no bubblewrap.

Selection is ``VIBECODER_SANDBOX``: ``auto`` (default), or a backend name to
pin one. Under ``auto`` a trusted run takes the subprocess path and an
untrusted one takes the first available isolating backend -- see
``select()``.

N4 still holds for ``SubprocessBackend``: it is an isolation boundary, not a
security one. The other two are the answer to that, and T2 W2 hardens them
further (seccomp, uid mapping). Nothing here should be described as complete
isolation until the adversarial suite in W2 says so.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path

# Where the harness is mounted inside an isolated filesystem. Fixed, because
# the host path is not necessarily representable inside the sandbox.
GUEST_HARNESS = "/harness.py"
GUEST_WORKDIR = "/work"

DEFAULT_DOCKER_IMAGE = "python:3.11-slim"

#: How long a backend availability probe may take before it is called dead.
PROBE_TIMEOUT = 10.0


class SandboxUnavailable(RuntimeError):
    """Raised when a pinned backend cannot run on this machine."""


class Backend(ABC):
    """Turns the harness into an argv. Stateless apart from a probe cache."""

    name: str = ""
    #: Whether this backend isolates the submission from the host. False means
    #: "do not put a stranger's code through it" -- see N4.
    isolating: bool = False

    _probe: bool | None = None

    @abstractmethod
    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]:
        """Argv that runs ``harness`` with JSON on stdin, JSON on stdout."""

    def _probe_command(self, harness: Path) -> list[str] | None:
        """Argv proving the backend works, or None to skip probing."""
        return None

    def available(self) -> bool:
        """Whether this backend can actually run here. Cached per process."""
        if self._probe is None:
            type(self)._probe = self._check()
        return bool(self._probe)

    def _probe_ok(self, done: subprocess.CompletedProcess[str]) -> bool:
        """Whether a completed probe proves the backend works."""
        return done.returncode == 0

    def _check(self) -> bool:
        probe = self._probe_command(Path(__file__).with_name("_harness.py"))
        if probe is None:
            return True
        try:
            done = subprocess.run(
                probe, capture_output=True, timeout=PROBE_TIMEOUT, text=True
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return self._probe_ok(done)


class SubprocessBackend(Backend):
    """A fresh interpreter on the host. The Phase 0 path, unchanged."""

    name = "subprocess"
    isolating = False

    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]:
        return [sys.executable, "-I", str(harness)]


class BwrapBackend(Backend):
    """bubblewrap: user/network/pid namespaces, no daemon, no root.

    The filesystem is assembled rather than inherited. Only the interpreter's
    own prefix and the shared libraries it links against are visible, each
    read-only; everything else the submission might want to read -- the
    player's home directory, ``/etc`` -- simply is not in the mount namespace.
    The one writable path is a tmpfs that evaporates with the process.
    """

    name = "bwrap"
    isolating = True

    def _isolation_flags(self, harness: Path) -> list[str]:
        prefix = sys.base_prefix
        flags = [
            "--ro-bind", prefix, prefix,
            "--ro-bind", str(harness), GUEST_HARNESS,
        ]
        # The interpreter links against libc and libpython, and the loader
        # lives outside the prefix on most distributions. Bind what exists;
        # a prefix that already contains these makes the extra bind a no-op.
        for lib in ("/usr/lib", "/usr/lib64", "/lib", "/lib64"):
            flags += ["--ro-bind-try", lib, lib]
        flags += [
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", GUEST_WORKDIR,
            "--chdir", GUEST_WORKDIR,
            # No network, no host PID table, no shared IPC. --die-with-parent
            # is what stops a wedged submission outliving the timeout.
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
            "--setenv", "PATH", "/usr/bin",
            "--setenv", "HOME", GUEST_WORKDIR,
            # Python must not try to write bytecode into a read-only prefix.
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        ]
        return flags

    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]:
        # Memory is capped by the harness itself via RLIMIT_AS, which survives
        # into the namespace; bubblewrap has no memory knob of its own.
        return [
            "bwrap",
            *self._isolation_flags(harness),
            sys.executable, "-I", GUEST_HARNESS,
        ]

    def _probe_command(self, harness: Path) -> list[str] | None:
        if shutil.which("bwrap") is None:
            return ["false"]
        # Namespaces can be present but forbidden (a hardened kernel, some
        # container hosts), so ask the kernel rather than the filesystem.
        return [
            "bwrap",
            *self._isolation_flags(harness),
            sys.executable, "-I", "-c", "pass",
        ]


class DockerBackend(Backend):
    """A container per run. For hosts with a daemon but no bubblewrap.

    Deliberately cold -- one container per submission, no warm pool. The
    trajectory's own hazard note is that a pool is the standard source of
    state-leak bugs between runs, and a leak here is one player's code seeing
    another's.
    """

    name = "docker"
    isolating = True

    @property
    def image(self) -> str:
        return os.environ.get("VIBECODER_DOCKER_IMAGE", DEFAULT_DOCKER_IMAGE)

    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]:
        return [
            "docker", "run", "--rm", "--interactive",
            "--network", "none",
            "--read-only",
            "--user", "65534:65534",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--pids-limit", "64",
            "--memory", f"{mem_limit_mb}m",
            "--tmpfs", f"{GUEST_WORKDIR}:rw,size=64m,noexec",
            "--workdir", GUEST_WORKDIR,
            "--volume", f"{harness}:{GUEST_HARNESS}:ro",
            "--env", "PYTHONDONTWRITEBYTECODE=1",
            self.image,
            "python3", "-I", GUEST_HARNESS,
        ]

    def _probe_command(self, harness: Path) -> list[str] | None:
        if shutil.which("docker") is None:
            return ["false"]
        # The client existing says nothing about the daemon being up, and
        # `docker version` is no help: it exits 0 and still prints a version
        # when the socket is missing. `docker info` reports an empty
        # ServerVersion in that case, which is a signal we can test.
        return ["docker", "info", "--format", "{{.ServerVersion}}"]

    def _probe_ok(self, done: subprocess.CompletedProcess[str]) -> bool:
        return done.returncode == 0 and bool(done.stdout.strip())


#: Registered backends, in the order ``auto`` prefers them for untrusted code.
BACKENDS: tuple[Backend, ...] = (
    BwrapBackend(),
    DockerBackend(),
)

_BY_NAME: dict[str, Backend] = {
    b.name: b for b in (SubprocessBackend(), *BACKENDS)
}


def select(*, untrusted: bool = False) -> Backend:
    """Return the backend to run under.

    ``VIBECODER_SANDBOX`` pins one by name and raises if it cannot run, because
    a pinned isolating backend silently downgrading to the subprocess path is
    exactly the failure this module exists to prevent.
    """
    pinned = os.environ.get("VIBECODER_SANDBOX", "auto").strip().lower()

    if pinned and pinned != "auto":
        backend = _BY_NAME.get(pinned)
        if backend is None:
            known = ", ".join(sorted(_BY_NAME))
            raise SandboxUnavailable(
                f"unknown sandbox backend {pinned!r} (known: {known})"
            )
        if not backend.available():
            raise SandboxUnavailable(
                f"sandbox backend {pinned!r} is not available on this machine"
            )
        return backend

    if not untrusted:
        return _BY_NAME["subprocess"]

    for backend in BACKENDS:
        if backend.available():
            return backend

    raise SandboxUnavailable(
        "untrusted code requires an isolating sandbox, but neither bubblewrap "
        "nor a running Docker daemon is available. Install bubblewrap "
        "(package 'bubblewrap') or start Docker."
    )


def describe() -> list[tuple[str, bool, bool]]:
    """``(name, isolating, available)`` for every backend. Used by the CLI."""
    return [
        (b.name, b.isolating, b.available())
        for b in (_BY_NAME["subprocess"], *BACKENDS)
    ]
