"""Core data types for VibeCoder.

Everything here is a plain dataclass so it round-trips to JSON without a
serialisation library. Levels are *generated* from a seed rather than stored
statically, which is what makes replaying a level with a new variant cheap.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable, Sequence


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

class Source(Enum):
    """Where a piece of code came from. The input to every isolation decision.

    This is an enum rather than a boolean because "untrusted" is a conclusion,
    not a fact, and the fact is worth keeping: a run that must be isolated
    should say *why*. It also lets the policy change in one place -- if
    isolation ever becomes cheap enough to apply to everything, only
    :meth:`requires_isolation` moves.

    It lives in ``models`` rather than ``sandbox`` so that ``Level`` can carry
    one without ``models`` gaining a dependency. ``models`` depends on nothing;
    that is the rule the module map rests on.
    """

    #: Typed by the person at this keyboard, on their own machine. N4 applies:
    #: the sandbox protects the game from their mistakes, not the machine from
    #: them, and it is their machine.
    PLAYER = "player"
    #: Shipped with the game -- a level's reference solution. Trusted for the
    #: same reason the game itself is: it came from this repository.
    BUNDLED = "bundled"
    #: Written by somebody else and delivered over a wire: a community level, a
    #: daily challenge, an ingested repository. Never runs on the host.
    THIRD_PARTY = "third_party"

    @property
    def requires_isolation(self) -> bool:
        """Whether this code may only run under an isolating backend.

        The one place the trust policy is written down. Everything else asks
        this rather than deciding for itself.
        """
        return self is Source.THIRD_PARTY

    def __str__(self) -> str:
        return self.value


# --------------------------------------------------------------------------
# Level definition
# --------------------------------------------------------------------------

@dataclass
class TestCase:
    """One hidden test case. Values must be JSON-serialisable.

    That constraint exists because tests are shipped to the sandbox process as
    JSON. It rules out passing custom objects into a level, which has not been
    a limitation for any level written so far.
    """

    name: str
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    expected: Any = None

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "args": list(self.args),
            "kwargs": dict(self.kwargs),
            "expected": self.expected,
        }


@dataclass
class Level:
    """A single playable level.

    ``make_tests`` receives a seeded ``random.Random`` so that every variant of
    a level is reproducible from its seed: the same seed always yields the same
    test data, and a new seed yields a fresh variant with the same shape.
    """

    id: str
    world: int
    world_title: str
    index: int
    title: str
    brief: str
    func_name: str
    starter: str
    reference: str
    make_tests: Callable[[random.Random], Sequence[TestCase]]
    par_seconds: float = 180.0
    tags: tuple[str, ...] = ()
    style_goals: tuple[str, ...] = ()
    #: Progressive hints, revealed one per failed attempt after the first.
    #:
    #: Ordered from a nudge to something close to the answer. They exist
    #: because a beginner who is stuck has no one to ask, and the alternative
    #: to a hint is not "they work it out", it is "they close the terminal".
    #: The first attempt never gets one: being stuck for a minute is the part
    #: of the exercise that does the teaching.
    hints: tuple[str, ...] = ()
    #: Who wrote this level. Every level in this repository is BUNDLED; a
    #: community level (T5) is THIRD_PARTY, and carrying that on the level
    #: itself is what stops its reference solution from reaching the host
    #: path by default.
    #:
    #: **This covers the code that runs in the sandbox, and nothing else.**
    #: ``make_tests`` is a callable that runs in the *parent* process every
    #: time :meth:`tests_for` is called, and a level is loaded by importing a
    #: module, which executes its body. Marking a level THIRD_PARTY does not
    #: make either of those safe. The registry only loads levels bundled with
    #: this package, so there is no way to reach that today -- and T5 must not
    #: open it without solving the loading problem separately. See the hazard
    #: list in docs/trajectories/T5-community.md.
    source: "Source" = Source.BUNDLED

    def tests_for(self, seed: int) -> list[TestCase]:
        return list(self.make_tests(random.Random(seed)))

    def hints_after(self, failed_attempts: int) -> list[str]:
        """Hints earned by ``failed_attempts`` unsuccessful runs.

        One new hint per failure after the first, so a player who is close
        gets a nudge and a player who is lost eventually gets the shape of
        the answer. Never more than the level wrote.
        """
        if failed_attempts < 2:
            return []
        return list(self.hints[: failed_attempts - 1])

    @property
    def multiplier(self) -> float:
        """Later worlds are worth more toward the global score."""
        return 1.0 + 0.1 * (self.world - 1)


# --------------------------------------------------------------------------
# Execution results
# --------------------------------------------------------------------------

@dataclass
class TestOutcome:
    name: str
    passed: bool
    got: str = ""
    expected: str = ""
    error: str = ""


@dataclass
class RunResult:
    """What came back from one sandboxed execution of a submission."""

    outcomes: list[TestOutcome] = field(default_factory=list)
    wall_seconds: float = 0.0
    ops: int = 0
    peak_bytes: int = 0
    stdout: str = ""
    error: str = ""          # fatal error (syntax error, missing function, timeout)
    error_type: str = ""     # "SyntaxError", "Timeout", "MissingFunction", ...
    trace: list[dict[str, Any]] = field(default_factory=list)

    @property
    def fatal(self) -> bool:
        return bool(self.error)

    @property
    def passed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.passed)

    @property
    def total_count(self) -> int:
        return len(self.outcomes)

    @property
    def all_passed(self) -> bool:
        return self.total_count > 0 and self.passed_count == self.total_count

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

@dataclass
class ScoreBreakdown:
    accuracy: float = 0.0
    speed: float = 0.0
    functional: float = 0.0
    subtotal: float = 0.0
    bonuses: dict[str, float] = field(default_factory=dict)
    total: float = 0.0
    stars: int = 0

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# --------------------------------------------------------------------------
# Vibe profile
# --------------------------------------------------------------------------

#: Schema version of `VibeVector`. Bump this whenever a field is added,
#: removed, or changes meaning, and add the matching entry to `VECTOR_MIGRATIONS`.
#:
#: The history it records:
#:
#: * **1** — the original vector (S001).
#: * **2** — conventions, the complexity distribution, nesting, comment
#:   density (S011).
#: * **3** — ``partial``, ``partial_reason``, ``files_seen`` (S014).
#: * **4** — the version field itself, and preservation of unknown fields.
VECTOR_VERSION = 4


def _additive(data: dict[str, Any]) -> dict[str, Any]:
    """A step that added fields and changed no existing one.

    Every migration so far is one of these, because every change so far has
    been additive and the dataclass defaults already supply the new fields. It
    is written out rather than left implicit so the chain is complete: a gap
    at version *n* is indistinguishable from "nobody thought about *n*", and
    `VECTOR_MIGRATIONS` is checked for gaps by the test suite.
    """
    return data


#: ``version -> the function that turns it into version + 1``. Applied in
#: order, so a version 1 profile written before any of this existed is walked
#: forward one step at a time rather than guessed at in one leap.
VECTOR_MIGRATIONS: dict[int, Any] = {
    1: _additive,   # 1 -> 2: S011 added six style fields
    2: _additive,   # 2 -> 3: S014 added the partial fields
    3: _additive,   # 3 -> 4: the version field; nothing existing moved
}


def migrate_vector(data: dict[str, Any], version: int) -> dict[str, Any]:
    """Walk a stored profile forward to `VECTOR_VERSION`.

    Raises `ValueError` for a version with no migration, which can only happen
    if somebody bumps `VECTOR_VERSION` without writing the step. Failing loudly
    here beats loading a profile whose fields mean something else.
    """
    data = dict(data)
    while version < VECTOR_VERSION:
        step = VECTOR_MIGRATIONS.get(version)
        if step is None:
            raise ValueError(
                f"no migration from vibe vector version {version}; "
                f"VECTOR_VERSION is {VECTOR_VERSION}"
            )
        data = step(data)
        version += 1
    return data


@dataclass
class VibeVector:
    """The static-analysis fingerprint of a codebase.

    ``patterns`` values are all normalised to 0..1 so they can be compared
    across codebases of wildly different sizes.
    """

    files: int = 0
    functions: int = 0
    code_lines: int = 0
    libraries: dict[str, int] = field(default_factory=dict)
    patterns: dict[str, float] = field(default_factory=dict)
    exceptions_caught: dict[str, int] = field(default_factory=dict)
    avg_function_lines: float = 0.0
    max_complexity: int = 0
    docstring_ratio: float = 0.0
    naming: dict[str, float] = field(default_factory=dict)
    #: PEP 8 conformance per identifier kind, 0..1. A kind the codebase has
    #: none of is absent rather than zero.
    conventions: dict[str, float] = field(default_factory=dict)
    #: Complexity as a distribution. ``max_complexity`` is one function on a
    #: bad day; these two say what the codebase is usually like.
    median_complexity: float = 0.0
    p90_complexity: float = 0.0
    #: Depth of nested control flow: the habit of returning early versus
    #: stepping further right, which survives every formatting choice.
    avg_nesting: float = 0.0
    max_nesting: int = 0
    #: Comment lines over all non-blank lines.
    comment_density: float = 0.0
    #: Set when an ingestion budget stopped the profile early. The vector still
    #: describes real code -- it is a smaller sample, not a wrong one -- but it
    #: is not a complete description of the codebase, and anything comparing
    #: two profiles or reporting one needs to know which it is holding.
    partial: bool = False
    #: Which budget ended the run, phrased for a person ("time budget: 60s").
    #: Empty exactly when ``partial`` is false.
    partial_reason: str = ""
    #: Eligible files found, against ``files`` actually profiled. Zero means
    #: "not recorded" rather than "none found": a profile written before this
    #: field existed loads with zero and is always complete, so ``files`` is
    #: the count to trust whenever ``partial`` is false.
    files_seen: int = 0
    tags: list[str] = field(default_factory=list)

    #: Schema this vector was written against. See `VECTOR_VERSION`.
    version: int = VECTOR_VERSION
    #: Fields from a build newer than this one, kept verbatim.
    #:
    #: Without this, loading a profile written by a newer VibeCoder and saving
    #: it again *destroys* whatever that build recorded -- silently, on an
    #: ordinary `vibecoder status`. Preserving them costs a dict and makes the
    #: round trip lossless in the one direction migration cannot help with,
    #: because a migration can only be written by the build that knows what
    #: the field means.
    unknown: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Flat JSON, with preserved future fields put back where they were.

        ``unknown`` is merged rather than nested, so a newer build reading this
        profile finds its own fields exactly where it left them instead of in
        a quarantine bucket it would have to know to look in.
        """
        data = asdict(self)
        data.update(data.pop("unknown", {}))
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "VibeVector":
        """Load a profile written by any version, migrating it forward.

        A profile with no ``version`` is version 1: the field was added in
        version 4, so its absence dates the profile rather than making it
        unreadable.

        A profile from a *newer* build keeps its own version number. Claiming
        it as this version would assert we understand fields we have never
        heard of, and re-saving would then look like a downgrade rather than
        the pass-through it is.
        """
        data = dict(data)
        version = int(data.pop("version", 1) or 1)
        if version < VECTOR_VERSION:
            data = migrate_vector(data, version)
            version = VECTOR_VERSION

        known = set(cls.__dataclass_fields__) - {"version", "unknown"}
        return cls(
            version=version,
            unknown={k: v for k, v in data.items() if k not in known},
            **{k: v for k, v in data.items() if k in known},
        )

    @property
    def from_a_newer_build(self) -> bool:
        """Whether this profile was written by a VibeCoder newer than this one."""
        return self.version > VECTOR_VERSION
