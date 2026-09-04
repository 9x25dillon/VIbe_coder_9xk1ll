"""Adversarial suite: every escape attempt must fail. T2 W2's gate.

The instrument check for this waypoint says this file has to run in CI rather
than by hand, so it is an ordinary unittest module discovered with the rest.
It skips itself when no isolating backend exists, because on such a machine
there is nothing to assert -- and the skip is louder than a pass, which is the
intended reading.

Each test states the attack and asserts the submission did not get what it
wanted. They assert on *failure*, never on a specific error message: the
kernel is free to refuse in whichever way it likes, and a test that pins the
wording would fail on the next kernel while proving nothing about safety.

N4 still applies to `SubprocessBackend`. Nothing here is run against it,
because it makes no such promise.
"""

import getpass
import os
import pathlib
import unittest

from vibecoder import sandbox, seccomp
from vibecoder.models import Source, TestCase as Case
from vibecoder.runner import run_code

TIMEOUT = 15.0

#: The host's real home directory, resolved out here in the parent. Tests must
#: name it absolutely: inside the sandbox HOME is /work, so a submission
#: expanding "~" is asking about the sandbox and would "succeed" while proving
#: nothing at all.
HOST_HOME = os.path.expanduser("~")

#: Identifying details of the host, resolved in the parent. Tests assert that
#: these are unreachable rather than that particular paths are absent -- the
#: two isolating backends have genuinely different filesystem models. A
#: container brings its own `/etc/passwd` and its own `/`, so "the path does
#: not exist" is true under bubblewrap and false under Docker while both are
#: equally safe. What matters to a player is that the sandbox cannot read
#: *their* machine.
HOST_USER = getpass.getuser()
HOST_REPO = str(pathlib.Path(__file__).resolve().parent.parent)


def isolating_backends():
    return [b for b in sandbox.BACKENDS if b.available()]


def isolation_in_effect() -> bool:
    """Whether `untrusted=True` will actually reach an isolating backend.

    Pinning `VIBECODER_SANDBOX=subprocess` wins over the untrusted flag by
    design (D13), which would turn this whole file red on a machine where
    somebody is debugging. There is nothing to assert in that configuration,
    so it skips -- and a skipped security suite is meant to read as louder
    than a passing one.
    """
    if not isolating_backends():
        return False
    try:
        return sandbox.select(untrusted=True).isolating
    except sandbox.SandboxUnavailable:
        return False


def attempt(code: str, *, func: str = "escape", timeout: float = TIMEOUT):
    """Run one escape attempt under whichever backend is pinned."""
    return run_code(
        code, func, [Case("attempt", [], expected="__unreachable__")],
        source=Source.THIRD_PARTY, timeout=timeout,
    )


def succeeded(result, marker: str = "ESCAPED") -> bool:
    """Whether the submission reached the thing it was reaching for."""
    if result.fatal:
        return False
    return any(marker in (o.got or "") for o in result.outcomes)


@unittest.skipUnless(isolation_in_effect(), "no isolating backend in effect")
class EscapeTest(unittest.TestCase):
    """Base for the attack classes. ``BACKEND`` is filled in by load_tests."""

    #: Which backend this copy of the class exercises. None means "whatever
    #: the environment already selects", which is what a bare run of one class
    #: from the command line does.
    BACKEND: str | None = None

    def setUp(self) -> None:
        if self.BACKEND is None:
            return
        previous = os.environ.get("VIBECODER_SANDBOX")
        os.environ["VIBECODER_SANDBOX"] = self.BACKEND
        self.addCleanup(self._restore_pin, previous)

    @staticmethod
    def _restore_pin(previous: str | None) -> None:
        if previous is None:
            os.environ.pop("VIBECODER_SANDBOX", None)
        else:
            os.environ["VIBECODER_SANDBOX"] = previous

    def assertContained(self, result, message: str) -> None:
        where = f" (backend: {self.BACKEND})" if self.BACKEND else ""
        self.assertFalse(succeeded(result), message + where)

    def assertRecorded(self, result) -> None:
        """Exit criterion 1: the attempt is recorded, not merely refused."""
        recorded = bool(result.error) or any(
            o.error or o.got for o in result.outcomes
        )
        self.assertTrue(recorded, "the attempt left no trace in the result")


class TestNetwork(EscapeTest):
    """Exit criterion 1."""

    def test_an_outbound_connection_fails(self):
        result = attempt(
            "import socket\n"
            "def escape():\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
            "    return 'ESCAPED'\n"
        )
        self.assertContained(result, "the sandbox reached the network")
        self.assertRecorded(result)

    def test_a_socket_cannot_even_be_created(self):
        """seccomp, not the namespace: there is nothing to connect *with*."""
        if not seccomp.available():
            self.skipTest("no seccomp syscall table for this architecture")
        result = attempt(
            "import socket\n"
            "def escape():\n"
            "    socket.socket(socket.AF_INET, socket.SOCK_STREAM)\n"
            "    return 'ESCAPED'\n"
        )
        self.assertContained(result, "a socket was created")

    def test_a_dns_lookup_fails(self):
        result = attempt(
            "import socket\n"
            "def escape():\n"
            "    return 'ESCAPED ' + socket.gethostbyname('example.com')\n"
        )
        self.assertContained(result, "the sandbox resolved a hostname")

    def test_a_unix_socket_to_the_host_fails(self):
        result = attempt(
            "import socket\n"
            "def escape():\n"
            "    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "    s.connect('/var/run/docker.sock')\n"
            "    return 'ESCAPED'\n"
        )
        self.assertContained(result, "the sandbox reached a host unix socket")

    def test_urllib_fails(self):
        """The way a submission would actually try it."""
        result = attempt(
            "import urllib.request\n"
            "def escape():\n"
            "    urllib.request.urlopen('http://example.com', timeout=3)\n"
            "    return 'ESCAPED'\n"
        )
        self.assertContained(result, "the sandbox made an HTTP request")


class TestFilesystem(EscapeTest):
    """Exit criterion 2."""

    def test_the_players_home_directory_is_not_readable(self):
        result = attempt(
            "import os\n"
            "def escape():\n"
            f"    return 'ESCAPED ' + str(os.listdir({HOST_HOME!r}))\n"
        )
        self.assertContained(result, "the sandbox read the host home directory")
        self.assertRecorded(result)

    def test_expanduser_does_not_point_at_the_host_home(self):
        """The sandbox's HOME is its own workdir, not the player's."""
        result = attempt(
            "import os\n"
            "def escape():\n"
            f"    return 'ESCAPED' if os.path.expanduser('~') == {HOST_HOME!r} "
            "else os.path.expanduser('~')\n"
        )
        self.assertContained(result, "HOME still points at the host home")

    def test_etc_passwd_does_not_describe_the_host(self):
        """A container has its own passwd file; it must not be the host's."""
        result = attempt(
            "def escape():\n"
            "    try:\n"
            "        body = open('/etc/passwd').read()\n"
            "    except OSError:\n"
            "        return 'absent'\n"
            f"    return 'ESCAPED' if {HOST_USER!r} in body else 'not the host'\n"
        )
        self.assertContained(result, "the sandbox read the host's /etc/passwd")

    def test_ssh_keys_are_not_readable(self):
        result = attempt(
            "import glob\n"
            "def escape():\n"
            f"    found = glob.glob({os.path.join(HOST_HOME, '.ssh', '*')!r})\n"
            "    return 'ESCAPED ' + str(found) if found else 'none'\n"
        )
        self.assertContained(result, "the sandbox saw ssh keys")

    def test_the_repository_itself_is_not_readable(self):
        """The submission must not be able to read the game that runs it."""
        result = attempt(
            "def escape():\n"
            "    return 'ESCAPED ' + open('/proc/self/cwd/vibecoder/scoring.py').read()\n"
        )
        self.assertContained(result, "the sandbox read the game's source")

    def test_writing_outside_the_workdir_fails(self):
        result = attempt(
            "def escape():\n"
            "    open('/etc/vibecoder-was-here', 'w').write('x')\n"
            "    return 'ESCAPED'\n"
        )
        self.assertContained(result, "the sandbox wrote outside its workdir")

    def test_the_interpreter_prefix_is_read_only(self):
        """It is mounted so the submission can run at all; it is not writable."""
        result = attempt(
            "import sys, os\n"
            "def escape():\n"
            "    target = os.path.join(sys.base_prefix, 'vibecoder-was-here')\n"
            "    open(target, 'w').write('x')\n"
            "    return 'ESCAPED'\n"
        )
        self.assertContained(result, "the interpreter prefix was writable")

    def test_the_host_filesystem_is_not_reachable(self):
        """By absolute path, which is what an attacker would actually use."""
        result = attempt(
            "import os\n"
            "def escape():\n"
            f"    return 'ESCAPED ' + str(os.listdir({HOST_REPO!r}))\n"
        )
        self.assertContained(result, "the host filesystem is reachable")

    def test_the_game_that_runs_the_submission_is_not_readable(self):
        result = attempt(
            "def escape():\n"
            f"    return 'ESCAPED ' + open({HOST_REPO + '/vibecoder/scoring.py'!r}).read()\n"
        )
        self.assertContained(result, "the sandbox read the game's own source")


class TestPrivilege(EscapeTest):
    def test_the_submission_does_not_run_as_root(self):
        result = attempt(
            "import os\n"
            "def escape():\n"
            "    return 'ESCAPED' if os.getuid() == 0 else 'nobody'\n"
        )
        self.assertContained(result, "the submission ran as root")

    def test_new_namespaces_cannot_be_created(self):
        """Nested user namespaces are how a sandbox usually comes apart."""
        if not seccomp.available():
            self.skipTest("no seccomp syscall table for this architecture")
        result = attempt(
            "import ctypes\n"
            "def escape():\n"
            "    libc = ctypes.CDLL('libc.so.6', use_errno=True)\n"
            "    rc = libc.unshare(0x10000000)\n"
            "    return 'ESCAPED' if rc == 0 else 'denied'\n"
        )
        self.assertContained(result, "the sandbox created a new namespace")

    def test_ptrace_is_denied(self):
        if not seccomp.available():
            self.skipTest("no seccomp syscall table for this architecture")
        result = attempt(
            "import ctypes\n"
            "def escape():\n"
            "    libc = ctypes.CDLL('libc.so.6', use_errno=True)\n"
            "    rc = libc.ptrace(0, 0, 0, 0)\n"
            "    return 'ESCAPED' if rc == 0 else 'denied'\n"
        )
        self.assertContained(result, "ptrace was permitted")

    def test_mounting_is_denied(self):
        if not seccomp.available():
            self.skipTest("no seccomp syscall table for this architecture")
        result = attempt(
            "import ctypes\n"
            "def escape():\n"
            "    libc = ctypes.CDLL('libc.so.6', use_errno=True)\n"
            "    rc = libc.mount(b'/', b'/work', b'none', 0x1000, None)\n"
            "    return 'ESCAPED' if rc == 0 else 'denied'\n"
        )
        self.assertContained(result, "mount was permitted")

    def test_host_processes_are_not_visible(self):
        result = attempt(
            "import os\n"
            "def escape():\n"
            "    pids = [e for e in os.listdir('/proc') if e.isdigit()]\n"
            "    return 'ESCAPED ' + str(len(pids)) if len(pids) > 20 else 'few'\n"
        )
        self.assertContained(result, "the host process table is visible")


class TestResourceExhaustion(EscapeTest):
    """Exit criterion 3: contained, parent unaffected, diagnosable."""

    def test_a_fork_bomb_is_contained(self):
        result = attempt(
            "import os\n"
            "def escape():\n"
            "    for _ in range(2000):\n"
            "        try:\n"
            "            os.fork()\n"
            "        except OSError:\n"
            "            return 'contained'\n"
            "    return 'ESCAPED'\n",
            timeout=20.0,
        )
        self.assertContained(result, "a fork bomb was not contained")

    def test_a_fork_bomb_returns_a_diagnosable_error(self):
        """A corrupted reply is not a diagnosis. This was the first attempt."""
        result = attempt(
            "import os\n"
            "def escape():\n"
            "    for _ in range(2000):\n"
            "        os.fork()\n"
            "    return 'ESCAPED'\n",
            timeout=20.0,
        )
        self.assertNotEqual(
            result.error_type, "SandboxCrash",
            "a fork bomb corrupted the reply instead of failing cleanly",
        )

    def test_a_ten_gigabyte_allocation_is_contained(self):
        result = attempt(
            "def escape():\n"
            "    return 'ESCAPED ' + str(len(bytearray(10 * 1024 ** 3)))\n"
        )
        self.assertContained(result, "a 10GB allocation was permitted")
        self.assertRecorded(result)

    def test_an_infinite_loop_is_stopped(self):
        result = attempt(
            "def escape():\n"
            "    while True:\n"
            "        pass\n",
            timeout=5.0,
        )
        self.assertTrue(result.fatal)
        self.assertEqual(result.error_type, "Timeout")

    def test_the_parent_survives_every_attack(self):
        """The point of all of the above: this process is still here."""
        import os

        self.assertTrue(os.getpid() > 0)
        healthy = run_code(
            "def ok():\n    return 1\n", "ok",
            [Case("t", [], expected=1)], source=Source.THIRD_PARTY,
        )
        self.assertTrue(healthy.all_passed, "the sandbox stopped working")


class TestHardeningIsReported(unittest.TestCase):
    """A protection that is not applied must not be claimed."""

    def test_the_subprocess_backend_claims_nothing(self):
        self.assertEqual(sandbox.SubprocessBackend().hardening, ())

    def test_bubblewrap_reports_seccomp_only_when_it_has_a_table(self):
        applied = sandbox.BwrapBackend().hardening
        self.assertEqual("seccomp" in applied, seccomp.available())

    def test_bubblewrap_claims_the_namespaces_it_sets_up(self):
        applied = sandbox.BwrapBackend().hardening
        for protection in ("netns", "ro-rootfs", "non-root"):
            self.assertIn(protection, applied)


class TestSeccompProgram(unittest.TestCase):
    """The filter itself, without needing to run anything under it."""

    def test_a_program_is_produced_for_this_machine(self):
        if not seccomp.available():
            self.skipTest("unsupported architecture")
        program = seccomp.build()
        self.assertEqual(len(program) % 8, 0, "not a whole number of instructions")
        self.assertGreater(len(program), 8)

    def test_an_unsupported_architecture_raises_rather_than_guessing(self):
        with self.assertRaises(RuntimeError):
            seccomp.build("vax")

    def test_every_architecture_blocks_the_same_syscall_names(self):
        """A name missing from one table is a hole on that architecture."""
        tables = [set(t) for _, t in seccomp.ARCHITECTURES.values()]
        self.assertTrue(all(t == tables[0] for t in tables))

    def test_the_network_syscalls_are_on_the_list(self):
        for architecture in seccomp.ARCHITECTURES:
            blocked = seccomp.blocked_syscalls(architecture)
            for name in ("socket", "connect", "bind", "sendto"):
                self.assertIn(name, blocked, f"{name} unblocked on {architecture}")

    def test_syscall_numbers_are_distinct_within_an_architecture(self):
        """A duplicated number means a syscall silently went unblocked."""
        for architecture, (_, table) in seccomp.ARCHITECTURES.items():
            with self.subTest(architecture=architecture):
                self.assertEqual(len(set(table.values())), len(table))


if __name__ == "__main__":
    unittest.main()


def load_tests(loader, tests, pattern):
    """Run every attack against every isolating backend this machine has.

    The Docker backend permitted `ptrace` for as long as this suite only ever
    exercised whichever backend happened to be selected -- Docker's default
    seccomp profile allows it deliberately, and nothing here was looking. A
    gate that tests one of two backends is a gate with a hole in it, so each
    attack class is cloned once per available backend and pinned to it.

    The cost is real: a Docker pass is several times slower than a bubblewrap
    one, because every attempt is a cold container. That is the price of the
    waypoint's own instrument check, which asks for this to run in CI rather
    than by hand.
    """
    suite = unittest.TestSuite()
    attacks = (TestNetwork, TestFilesystem, TestPrivilege, TestResourceExhaustion)
    names = [b.name for b in isolating_backends()]

    # A pin already means "use this backend", so honour it here too: it gives
    # a fast inner loop that still runs the whole gate against one backend.
    # An unpinned run -- which is what CI does -- takes all of them.
    pinned = os.environ.get("VIBECODER_SANDBOX", "auto").strip().lower()
    if pinned in names:
        names = [pinned]

    for case in attacks:
        if not names:
            suite.addTests(loader.loadTestsFromTestCase(case))
            continue
        for name in names:
            clone = type(f"{case.__name__}[{name}]", (case,), {"BACKEND": name})
            clone.__module__ = case.__module__
            suite.addTests(loader.loadTestsFromTestCase(clone))

    for case in (TestHardeningIsReported, TestSeccompProgram):
        suite.addTests(loader.loadTestsFromTestCase(case))
    return suite
