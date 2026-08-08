"""VibeCoder - a Python puzzle game that adapts to how you already write code.

Public surface:

    from vibecoder import profile_path, all_levels, run_submission, score_submission

Phase 0 scope is documented in docs/trajectories/T1-core-loop.md. The engine is
deliberately dependency-free so the game runs anywhere a Python 3.10+
interpreter does.
"""

from .models import Level, RunResult, ScoreBreakdown, TestCase, TestOutcome, VibeVector
from .profiler import profile_path, recommend
from .runner import reference_benchmark, run_code, run_submission
from .scoring import (
    BOSS_WEIGHTS,
    LEVEL_WEIGHTS,
    Weights,
    accuracy_score,
    functional_score,
    score_submission,
    speed_score,
    stars_for,
)
from .session import Session
from .levels import all_levels, get_level, worlds

__version__ = "0.1.0"

__all__ = [
    "Level",
    "RunResult",
    "ScoreBreakdown",
    "TestCase",
    "TestOutcome",
    "VibeVector",
    "Weights",
    "BOSS_WEIGHTS",
    "LEVEL_WEIGHTS",
    "Session",
    "accuracy_score",
    "all_levels",
    "functional_score",
    "get_level",
    "profile_path",
    "recommend",
    "reference_benchmark",
    "run_code",
    "run_submission",
    "score_submission",
    "speed_score",
    "stars_for",
    "worlds",
    "__version__",
]
