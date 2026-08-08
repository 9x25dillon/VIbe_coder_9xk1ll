"""Core data types for VibeCoder.

Everything here is a plain dataclass so it round-trips to JSON without a
serialisation library. Levels are *generated* from a seed rather than stored
statically, which is what makes replaying a level with a new variant cheap.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Sequence


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

    def tests_for(self, seed: int) -> list[TestCase]:
        return list(self.make_tests(random.Random(seed)))

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
    tags: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "VibeVector":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})
