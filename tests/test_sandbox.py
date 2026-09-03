"""The transport seam: backend selection, availability, and isolation smoke.

The adversarial suite that proves a submission cannot escape is T2 W2's gate
(`tests/test_sandbox_escape.py`). What lives here is narrower: that the right
backend gets picked, that pinning a dead one fails loudly rather than quietly
downgrading, and that an isolating backend really does execute code.
"""

import os
import unittest
from unittest import mock

from vibecoder import sandbox
from vibecoder.models import TestCase as Case
from vibecoder.runner import run_code

ADD = "def add(a, b):\n    return a + b\n"


def _isolating_backends():
    return [b for b in sandbox.BACKENDS if b.available()]


class TestSelection(unittest.TestCase):
    """`auto` is the only mode most players will ever be in."""

    def setUp(self):
        # select() reads the environment on every call, so each test states
        # the whole environment it means to test under.
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("VIBECODER_SANDBOX", None)

    def test_trusted_code_takes_the_fast_path(self):
        self.assertEqual(sandbox.select().name, "subprocess")

    def test_auto_defaults_to_trusted(self):
        os.environ["VIBECODER_SANDBOX"] = "auto"
        self.assertEqual(sandbox.select().name, "subprocess")

    def test_untrusted_code_never_takes_the_fast_path(self):
        """The whole point of the seam. A downgrade here is the bug."""
        if not _isolating_backends():
            self.skipTest("no isolating backend on this machine")
        self.assertTrue(sandbox.select(untrusted=True).isolating)

    def test_untrusted_raises_when_nothing_isolates(self):
        with mock.patch.object(sandbox, "BACKENDS", ()):
            with self.assertRaises(sandbox.SandboxUnavailable):
                sandbox.select(untrusted=True)

    def test_an_unknown_backend_name_is_an_error(self):
        os.environ["VIBECODER_SANDBOX"] = "hovercraft"
        with self.assertRaises(sandbox.SandboxUnavailable) as ctx:
            sandbox.select()
        self.assertIn("hovercraft", str(ctx.exception))

    def test_pinning_an_unavailable_backend_raises(self):
        """Silently falling back would defeat the reason for pinning."""
        os.environ["VIBECODER_SANDBOX"] = "bwrap"
        with mock.patch.object(sandbox.BwrapBackend, "available", return_value=False):
            with self.assertRaises(sandbox.SandboxUnavailable):
                sandbox.select()

    def test_a_pinned_name_wins_over_the_untrusted_flag(self):
        os.environ["VIBECODER_SANDBOX"] = "subprocess"
        self.assertEqual(sandbox.select(untrusted=True).name, "subprocess")


class TestDescribe(unittest.TestCase):
    def test_every_backend_is_reported(self):
        names = [row[0] for row in sandbox.describe()]
        self.assertEqual(names, ["subprocess", "bwrap", "docker"])

    def test_only_the_subprocess_backend_claims_no_isolation(self):
        isolating = {name: iso for name, iso, _ in sandbox.describe()}
        self.assertFalse(isolating["subprocess"])
        self.assertTrue(isolating["bwrap"])
        self.assertTrue(isolating["docker"])


class TestCommands(unittest.TestCase):
    """Argv construction, which is all a backend actually contributes."""

    HARNESS = sandbox.Path(sandbox.__file__).with_name("_harness.py")

    def test_bwrap_disables_the_network(self):
        argv = sandbox.BwrapBackend().command(self.HARNESS, mem_limit_mb=256)
        self.assertIn("--unshare-all", argv)
        self.assertIn("--die-with-parent", argv)

    def test_bwrap_never_binds_the_host_root(self):
        """A `--bind / /` would undo the entire filesystem story."""
        argv = sandbox.BwrapBackend().command(self.HARNESS, mem_limit_mb=256)
        pairs = list(zip(argv, argv[1:], argv[2:]))
        self.assertFalse(
            [f for f, src, dst in pairs if f.startswith("--bind") and src == "/"],
            "bubblewrap must not bind the host root",
        )

    def test_docker_passes_the_memory_limit_through(self):
        argv = sandbox.DockerBackend().command(self.HARNESS, mem_limit_mb=256)
        self.assertIn("256m", argv)
        self.assertIn("--network", argv)
        self.assertEqual(argv[argv.index("--network") + 1], "none")

    def test_docker_mounts_the_harness_read_only(self):
        argv = sandbox.DockerBackend().command(self.HARNESS, mem_limit_mb=256)
        mount = argv[argv.index("--volume") + 1]
        self.assertTrue(mount.endswith(":ro"), mount)

    def test_the_harness_is_the_entrypoint_everywhere(self):
        """N2: one child script, three transports."""
        for backend in (
            sandbox.SubprocessBackend(),
            sandbox.BwrapBackend(),
            sandbox.DockerBackend(),
        ):
            argv = backend.command(self.HARNESS, mem_limit_mb=256)
            with self.subTest(backend=backend.name):
                self.assertTrue(
                    argv[-1].endswith("_harness.py") or argv[-1] == sandbox.GUEST_HARNESS,
                    argv,
                )
                self.assertIn("-I", argv)


@unittest.skipUnless(_isolating_backends(), "no isolating backend on this machine")
class TestIsolatedExecution(unittest.TestCase):
    """Exit criterion 7 in miniature, plus early evidence for 1 and 2."""

    def test_untrusted_code_still_runs_and_scores(self):
        result = run_code(ADD, "add", [Case("s", [1, 2], expected=3)], untrusted=True)
        self.assertFalse(result.fatal, result.error)
        self.assertTrue(result.all_passed)
        self.assertGreater(result.ops, 0)

    def test_the_result_matches_the_untrusted_path(self):
        """Same code, same numbers -- otherwise scoring depends on transport."""
        tests = [Case("s", [2, 3], expected=5)]
        trusted = run_code(ADD, "add", tests)
        isolated = run_code(ADD, "add", tests, untrusted=True)
        self.assertEqual(trusted.ops, isolated.ops)

    def test_a_syntax_error_is_reported_not_crashed(self):
        result = run_code("def add(a b):\n    pass\n", "add", [], untrusted=True)
        self.assertTrue(result.fatal)
        self.assertEqual(result.error_type, "SyntaxError")

    def test_the_network_is_unreachable(self):
        """Early evidence for exit criterion 1; W2 owns the real suite."""
        code = (
            "import socket\n"
            "def probe():\n"
            "    socket.create_connection(('1.1.1.1', 53), timeout=2)\n"
            "    return 'reachable'\n"
        )
        result = run_code(code, "probe", [Case("n", [], expected="reachable")],
                          untrusted=True)
        self.assertFalse(result.all_passed, "the sandbox reached the network")

    def test_the_players_home_directory_is_not_visible(self):
        """Early evidence for exit criterion 2."""
        code = (
            "import os\n"
            "def peek():\n"
            "    return os.path.isdir(os.path.expanduser('~/.ssh'))\n"
        )
        result = run_code(code, "peek", [Case("h", [], expected=True)],
                          untrusted=True)
        self.assertFalse(result.all_passed, "the sandbox saw the host home directory")


if __name__ == "__main__":
    unittest.main()
