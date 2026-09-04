"""A seccomp-BPF filter, assembled by hand. T2 W2.

The namespaces set up in :mod:`vibecoder.sandbox` already remove the network
and the host filesystem. This is the second layer: it removes the *ability to
ask*. A submission under this filter cannot open a socket at all, rather than
opening one that goes nowhere, and cannot reach for the syscalls that exist to
change what a process is -- ``ptrace``, ``unshare``, ``setns``, ``mount``,
module loading, ``bpf``.

Two layers rather than one because they fail differently. A namespace is
configuration, and configuration can be got wrong in a way that still looks
like it worked; this filter is a hard refusal from the kernel that does not
depend on any mount having been set up correctly.

**Why the bytecode is written out longhand.** ``libseccomp`` is the normal way
to produce one of these, and N1 forbids it. A seccomp filter is classic BPF --
a list of 8-byte instructions -- and generating one is a page of ``struct``
calls, so the rule costs less here than the dependency would. The syscall
numbers below were read from this machine's ``asm/unistd_64.h`` and
``asm-generic/unistd.h`` rather than remembered, because a wrong number fails
in the worst available way: silently permitting what it was meant to deny.

Denials return ``EPERM`` rather than killing the process. The submission sees
a ``PermissionError``, the harness records it as a failed test with a readable
message, and T2 exit criterion 1 -- "the attempt is recorded" -- is satisfied
by the machinery that already reports every other error.
"""

from __future__ import annotations

import platform
import struct

# BPF instruction classes and modes (linux/bpf_common.h).
BPF_LD = 0x00
BPF_W = 0x00
BPF_ABS = 0x20
BPF_JMP = 0x05
BPF_JEQ = 0x10
BPF_K = 0x00
BPF_RET = 0x06

LOAD_WORD = BPF_LD | BPF_W | BPF_ABS
JUMP_EQUAL = BPF_JMP | BPF_JEQ | BPF_K
RETURN = BPF_RET | BPF_K

# Offsets into struct seccomp_data.
OFFSET_NR = 0
OFFSET_ARCH = 4

# Actions (linux/seccomp.h).
SECCOMP_RET_KILL_PROCESS = 0x80000000
SECCOMP_RET_ERRNO = 0x00050000
SECCOMP_RET_ALLOW = 0x7FFF0000
EPERM = 1

# Architecture tokens (linux/audit.h).
AUDIT_ARCH_X86_64 = 0xC000003E
AUDIT_ARCH_AARCH64 = 0xC00000B7

#: Syscalls a submission has no business making, by architecture. Grouped by
#: what they would buy an attacker rather than alphabetically, because the
#: reason a number is on this list is the only thing that justifies it.
_X86_64 = {
    # Reaching the network, or asking whether it is there.
    "socket": 41, "connect": 42, "accept": 43, "sendto": 44, "recvfrom": 45,
    "sendmsg": 46, "recvmsg": 47, "shutdown": 48, "bind": 49, "listen": 50,
    "accept4": 288, "recvmmsg": 299, "sendmmsg": 307,
    # Becoming a different process, or reading one.
    "ptrace": 101, "process_vm_readv": 310, "process_vm_writev": 311,
    # Changing the shape of the sandbox from inside it.
    "mount": 165, "umount2": 166, "pivot_root": 155, "chroot": 161,
    "unshare": 272, "setns": 308, "open_by_handle_at": 304,
    # Reaching into the kernel.
    "init_module": 175, "delete_module": 176, "finit_module": 313,
    "kexec_load": 246, "kexec_file_load": 320, "bpf": 321,
    "userfaultfd": 323, "perf_event_open": 298,
    # Kernel keyring, and things a process should never do to a machine.
    "add_key": 248, "request_key": 249, "keyctl": 250,
    "reboot": 169, "swapon": 167, "swapoff": 168,
}

_AARCH64 = {
    "socket": 198, "connect": 203, "accept": 202, "sendto": 206,
    "recvfrom": 207, "sendmsg": 211, "recvmsg": 212, "shutdown": 210,
    "bind": 200, "listen": 201, "accept4": 242, "recvmmsg": 243,
    "sendmmsg": 269,
    "ptrace": 117, "process_vm_readv": 270, "process_vm_writev": 271,
    "mount": 40, "umount2": 39, "pivot_root": 41, "chroot": 51,
    "unshare": 97, "setns": 268, "open_by_handle_at": 265,
    "init_module": 105, "delete_module": 106, "finit_module": 273,
    "kexec_load": 104, "kexec_file_load": 294, "bpf": 280,
    "userfaultfd": 282, "perf_event_open": 241,
    "add_key": 217, "request_key": 218, "keyctl": 219,
    "reboot": 142, "swapon": 224, "swapoff": 225,
}

ARCHITECTURES: dict[str, tuple[int, dict[str, int]]] = {
    "x86_64": (AUDIT_ARCH_X86_64, _X86_64),
    "aarch64": (AUDIT_ARCH_AARCH64, _AARCH64),
}


def _instruction(code: int, jt: int, jf: int, k: int) -> bytes:
    """One ``struct sock_filter``: 8 bytes, no padding."""
    return struct.pack("HBBI", code, jt, jf, k)


def current_architecture() -> str | None:
    """The key into :data:`ARCHITECTURES`, or None if unsupported."""
    machine = platform.machine()
    return machine if machine in ARCHITECTURES else None


def available() -> bool:
    """Whether a filter can be built for this machine.

    False is not fatal: the namespaces in :mod:`vibecoder.sandbox` still hold
    without it. It does mean the second layer is missing, which is why
    ``vibecoder sandbox`` reports it rather than leaving it to be assumed.
    """
    return current_architecture() is not None


def blocked_syscalls(architecture: str | None = None) -> dict[str, int]:
    architecture = architecture or current_architecture()
    if architecture is None:
        return {}
    return dict(ARCHITECTURES[architecture][1])


def build(architecture: str | None = None) -> bytes:
    """The compiled cBPF program, as ``bwrap --seccomp`` wants it.

    Shape::

        load  arch
        jeq   expected ? next : kill      -- foreign arch, numbers meaningless
        load  syscall number
        jeq   blocked_0 ? deny : next
        ...
        ret   ALLOW
        deny: ret ERRNO(EPERM)
        kill: ret KILL_PROCESS

    The architecture check comes first and is not optional. Syscall numbers
    are per-architecture, so a filter applied to the wrong one is not a weaker
    filter, it is a filter that denies unrelated syscalls and permits the ones
    it was written to stop.
    """
    architecture = architecture or current_architecture()
    if architecture not in ARCHITECTURES:
        raise RuntimeError(
            f"no seccomp syscall table for {architecture or platform.machine()!r}"
        )
    token, table = ARCHITECTURES[architecture]
    numbers = sorted(set(table.values()))
    count = len(numbers)

    # Indices: 0 arch load, 1 arch check, 2 nr load, 3..3+count-1 checks,
    # then allow, deny, kill.
    allow_at = 3 + count
    deny_at = allow_at + 1
    kill_at = deny_at + 1

    program = [
        _instruction(LOAD_WORD, 0, 0, OFFSET_ARCH),
        # Jump distances are measured from the instruction after this one.
        _instruction(JUMP_EQUAL, 0, kill_at - 2, token),
        _instruction(LOAD_WORD, 0, 0, OFFSET_NR),
    ]
    for offset, number in enumerate(numbers):
        here = 3 + offset
        program.append(
            _instruction(JUMP_EQUAL, deny_at - (here + 1), 0, number)
        )
    program.append(_instruction(RETURN, 0, 0, SECCOMP_RET_ALLOW))
    program.append(_instruction(RETURN, 0, 0, SECCOMP_RET_ERRNO | EPERM))
    program.append(_instruction(RETURN, 0, 0, SECCOMP_RET_KILL_PROCESS))

    # Every jump offset must fit in the 8-bit jt/jf fields. With a table this
    # size there is plenty of room, but the check is cheap and the failure it
    # prevents is a filter that silently jumps to the wrong instruction.
    if kill_at > 255:
        raise RuntimeError("seccomp filter too long for 8-bit jump offsets")
    return b"".join(program)


#: Docker takes a JSON profile rather than compiled BPF, and names syscalls
#: rather than numbering them -- so this form needs no architecture table at
#: all. Same policy, second dialect.
DOCKER_DEFAULT_ACTION = "SCMP_ACT_ALLOW"
DOCKER_DENY_ACTION = "SCMP_ACT_ERRNO"


def docker_profile() -> dict:
    """The same denial list as :func:`build`, in Docker's profile format.

    Docker's *default* profile does not deny ``ptrace`` -- it was allowed
    deliberately, so that debuggers work inside containers -- and it permits
    socket creation. Relying on it would have left the Docker backend weaker
    than the bubblewrap one while both reported "seccomp".

    The names are the union across architectures, which is safe because a
    profile naming a syscall the running kernel does not have is ignored
    rather than rejected.
    """
    names = sorted({
        name for _, table in ARCHITECTURES.values() for name in table
    })
    return {
        "defaultAction": DOCKER_DEFAULT_ACTION,
        "archMap": [],
        "syscalls": [
            {
                "names": names,
                "action": DOCKER_DENY_ACTION,
                "errnoRet": EPERM,
            }
        ],
    }
