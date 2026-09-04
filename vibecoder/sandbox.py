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

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from . import seccomp

# Where the harness is mounted inside an isolated filesystem. Fixed, because
# the host path is not necessarily representable inside the sandbox.
GUEST_HARNESS = "/harness.py"
GUEST_WORKDIR = "/work"
#: Where the interpreter's prefix is mounted inside the sandbox.
#:
#: Deliberately *not* its host path. Bubblewrap creates the parent directories
#: a bind needs, so mounting an interpreter that lives under ``/home/someone``
#: conjures ``/home/someone`` into the sandbox -- empty, but enough to tell a
#: submission the player's username and where their tools are installed. The
#: contents were never readable; the shape of the host was. Mounting at a fixed
#: path removes the question, and makes the sandbox identical whether the
#: interpreter came from the system or from a user-local install.
GUEST_PREFIX = "/python"

DEFAULT_DOCKER_IMAGE = "python:3.11-slim"

#: The conventional unprivileged account. Inside a user namespace this is a
#: mapping, not the host's nobody, but the intent is the same: own nothing.
NOBODY_UID = 65534
NOBODY_GID = 65534

#: How long a backend availability probe may take before it is called dead.
PROBE_TIMEOUT = 10.0


class SandboxUnavailable(RuntimeError):
    """Raised when a pinned backend cannot run on this machine."""


@dataclass(frozen=True)
class Launch:
    """Everything needed to spawn one run.

    A plain argv was enough until seccomp arrived: ``bwrap --seccomp`` takes a
    *file descriptor*, not a path, so a backend now has to be able to hand the
    parent something to keep open for the duration of the spawn. Hence
    :meth:`Backend.launch`, a context manager, rather than a function
    returning a list of strings.
    """

    argv: list[str]
    pass_fds: tuple[int, ...] = ()
    #: What the backend actually managed to apply, for reporting. A backend
    #: that could not build a seccomp filter still runs; it just says so.
    hardening: tuple[str, ...] = field(default=())


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

    @contextlib.contextmanager
    def launch(self, harness: Path, *, mem_limit_mb: int) -> Iterator[Launch]:
        """Yield a :class:`Launch`, holding any resources open meanwhile.

        The default needs no resources. :class:`BwrapBackend` overrides it to
        keep the seccomp program's file descriptor alive across the spawn.
        """
        yield Launch(self.command(harness, mem_limit_mb=mem_limit_mb))

    @property
    def hardening(self) -> tuple[str, ...]:
        """Names of the protections this backend applies, for reporting."""
        return ()

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

    @staticmethod
    def guest_interpreter() -> str:
        """Where :data:`sys.executable` appears inside the sandbox.

        Normally the executable sits under its own prefix, so the guest path
        is the same relative walk from :data:`GUEST_PREFIX`. When it does not
        -- a symlink farm, an unusual build -- the executable is bound on its
        own and keeps its host path, which leaks nothing a system binary path
        does not already reveal.
        """
        executable = Path(sys.executable).resolve()
        prefix = Path(sys.base_prefix).resolve()
        try:
            return str(Path(GUEST_PREFIX) / executable.relative_to(prefix))
        except ValueError:
            return str(executable)

    def _isolation_flags(self, harness: Path) -> list[str]:
        prefix = str(Path(sys.base_prefix).resolve())
        flags = [
            "--ro-bind", prefix, GUEST_PREFIX,
            "--ro-bind", str(harness), GUEST_HARNESS,
        ]
        if not self.guest_interpreter().startswith(GUEST_PREFIX):
            executable = str(Path(sys.executable).resolve())
            flags += ["--ro-bind", executable, executable]
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
            # Inside the user namespace, be nobody. Before this the submission
            # ran as the player's own uid, which meant that any bind mount
            # added later -- by a future waypoint, in a hurry -- would have
            # been writable by default rather than by decision.
            "--uid", str(NOBODY_UID),
            "--gid", str(NOBODY_GID),
        ]
        return flags

    def command(self, harness: Path, *, mem_limit_mb: int) -> list[str]:
        # Memory is capped by the harness itself via RLIMIT_AS, which survives
        # into the namespace; bubblewrap has no memory knob of its own.
        return [
            "bwrap",
            *self._isolation_flags(harness),
            self.guest_interpreter(), "-I", GUEST_HARNESS,
        ]

    @property
    def hardening(self) -> tuple[str, ...]:
        applied = ("netns", "ro-rootfs", "non-root", "pid-ns")
        return applied + (("seccomp",) if seccomp.available() else ())

    @contextlib.contextmanager
    def launch(self, harness: Path, *, mem_limit_mb: int) -> Iterator[Launch]:
        """Spawn under a seccomp filter when one can be built for this arch.

        ``bwrap --seccomp`` reads the program from a file descriptor, so the
        program is written to an unlinked temporary file whose fd is passed to
        the child. It has to stay open across the spawn, which is the whole
        reason this is a context manager.

        An architecture with no syscall table is not a failure. The namespaces
        still hold; the second layer is simply absent, and ``hardening`` says
        so rather than letting it be assumed.
        """
        argv = self.command(harness, mem_limit_mb=mem_limit_mb)
        if not seccomp.available():
            yield Launch(argv, hardening=self.hardening)
            return

        with tempfile.TemporaryFile() as program:
            program.write(seccomp.build())
            program.flush()
            program.seek(0)
            descriptor = program.fileno()
            # The flag goes before the command, like every other bwrap option.
            index = argv.index(self.guest_interpreter())
            argv = (
                argv[:index]
                + ["--seccomp", str(descriptor)]
                + argv[index:]
            )
            yield Launch(argv, pass_fds=(descriptor,),
                         hardening=self.hardening)

    def _probe_command(self, harness: Path) -> list[str] | None:
        if shutil.which("bwrap") is None:
            return ["false"]
        # Namespaces can be present but forbidden (a hardened kernel, some
        # container hosts), so ask the kernel rather than the filesystem.
        return [
            "bwrap",
            *self._isolation_flags(harness),
            self.guest_interpreter(), "-I", "-c", "pass",
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
    def hardening(self) -> tuple[str, ...]:
        # Docker's *default* profile is not enough: it permits ptrace, on
        # purpose, so that debuggers work inside containers. This backend
        # ships the same denial list bubblewrap uses instead.
        return ("netns", "ro-rootfs", "non-root", "pid-ns", "no-new-privs",
                "cap-drop", "seccomp")

    @contextlib.contextmanager
    def launch(self, harness: Path, *, mem_limit_mb: int) -> Iterator[Launch]:
        """Spawn under this project's seccomp profile, not Docker's default.

        Docker reads a JSON profile from a *path*, where bubblewrap reads
        compiled BPF from a descriptor, so the same policy is written twice in
        two dialects -- see :func:`seccomp.docker_profile`.
        """
        argv = self.command(harness, mem_limit_mb=mem_limit_mb)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", encoding="utf-8"
        ) as profile:
            json.dump(seccomp.docker_profile(), profile)
            profile.flush()
            index = argv.index("--network")
            argv = (
                argv[:index]
                + ["--security-opt", f"seccomp={profile.name}"]
                + argv[index:]
            )
            yield Launch(argv, hardening=self.hardening)

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


def backend(name: str) -> Backend:
    """Look one up by name. Raises for an unknown name."""
    if name not in _BY_NAME:
        raise SandboxUnavailable(f"unknown sandbox backend {name!r}")
    return _BY_NAME[name]


def describe() -> list[tuple[str, bool, bool]]:
    """``(name, isolating, available)`` for every backend. Used by the CLI."""
    return [
        (b.name, b.isolating, b.available())
        for b in (_BY_NAME["subprocess"], *BACKENDS)
    ]
