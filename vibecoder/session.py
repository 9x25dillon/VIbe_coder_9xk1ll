"""Player progression: the Vibe Vector, per-level records and the global score.

State lives in a single JSON file so it can be inspected, diffed and deleted by
hand. The location is ``$VIBECODER_HOME`` if set, otherwise ``~/.vibecoder``.

The global score is recomputed from the per-level bests on every save rather
than incremented, so a corrupted increment cannot compound and replaying a
level can never lower a total the player already banked.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ScoreBreakdown, VibeVector
from .scoring import streak_multiplier

STATE_VERSION = 1


def home() -> Path:
    root = os.environ.get("VIBECODER_HOME")
    return Path(root).expanduser() if root else Path.home() / ".vibecoder"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class LevelRecord:
    level_id: str
    attempts: int = 0
    clears: int = 0
    best_total: float = 0.0
    best_stars: int = 0
    last_seed: int = 0
    seeds_played: list[int] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "level_id": self.level_id,
            "attempts": self.attempts,
            "clears": self.clears,
            "best_total": self.best_total,
            "best_stars": self.best_stars,
            "last_seed": self.last_seed,
            "seeds_played": self.seeds_played,
            "history": self.history[-20:],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "LevelRecord":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


class Session:
    """Load, mutate and persist a player's progression."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (home() / "profile.json")
        self.version = STATE_VERSION
        self.created_at = _now()
        self.updated_at = self.created_at
        self.vibe: VibeVector | None = None
        self.vibe_source: str = ""
        self.levels: dict[str, LevelRecord] = {}
        self.streak = 0
        self.tokens: dict[str, int] = {"hint": 3, "skip": 1}
        self.total_score = 0.0

    # -- persistence -------------------------------------------------------

    @classmethod
    def load(cls, path: Path | None = None) -> "Session":
        session = cls(path)
        if not session.path.exists():
            return session
        try:
            data = json.loads(session.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt profile is preserved rather than silently overwritten,
            # so the player can recover a hand-edited file.
            backup = session.path.with_suffix(f".corrupt-{int(time.time())}.json")
            try:
                session.path.rename(backup)
            except OSError:
                pass
            return session

        session.version = data.get("version", STATE_VERSION)
        session.created_at = data.get("created_at", session.created_at)
        session.updated_at = data.get("updated_at", session.updated_at)
        session.vibe_source = data.get("vibe_source", "")
        if data.get("vibe"):
            session.vibe = VibeVector.from_json(data["vibe"])
        session.levels = {
            level_id: LevelRecord.from_json(record)
            for level_id, record in data.get("levels", {}).items()
        }
        session.streak = data.get("streak", 0)
        session.tokens = data.get("tokens", session.tokens)
        session.total_score = data.get("total_score", 0.0)
        return session

    def save(self) -> None:
        self.updated_at = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "vibe_source": self.vibe_source,
            "vibe": self.vibe.to_json() if self.vibe else None,
            "levels": {k: v.to_json() for k, v in self.levels.items()},
            "streak": self.streak,
            "tokens": self.tokens,
            "total_score": round(self.total_score, 2),
        }
        # Write-then-rename so an interrupted save cannot truncate the profile.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    # -- mutation ----------------------------------------------------------

    def record(self, level_id: str) -> LevelRecord:
        return self.levels.setdefault(level_id, LevelRecord(level_id=level_id))

    def next_seed(self, level_id: str) -> int:
        """Pick a variant seed the player has not seen for this level."""
        record = self.record(level_id)
        seed = len(record.seeds_played) + 1
        while seed in record.seeds_played:
            seed += 1
        return seed

    def submit(
        self,
        level_id: str,
        score: ScoreBreakdown,
        *,
        seed: int,
        multipliers: dict[str, float] | None = None,
    ) -> dict[str, Any]:
        """Bank a completed attempt and return what changed."""
        record = self.record(level_id)
        record.attempts += 1
        record.last_seed = seed
        if seed not in record.seeds_played:
            record.seeds_played.append(seed)

        cleared = score.stars > 0
        if cleared:
            record.clears += 1

        improved = score.total > record.best_total
        if improved:
            record.best_total = score.total
            record.best_stars = score.stars

        record.history.append(
            {
                "at": _now(),
                "seed": seed,
                "total": score.total,
                "stars": score.stars,
                "accuracy": score.accuracy,
                "speed": score.speed,
                "functional": score.functional,
            }
        )

        # A perfect clear extends the streak; anything less resets it.
        if score.stars == 3:
            self.streak += 1
        else:
            self.streak = 0

        self.total_score = self.recompute_total(multipliers)
        return {
            "improved": improved,
            "cleared": cleared,
            "streak": self.streak,
            "streak_multiplier": streak_multiplier(self.streak),
        }

    def recompute_total(self, multipliers: dict[str, float] | None = None) -> float:
        """Global score = sum of per-level bests, each times its world multiplier.

        Levels missing from ``multipliers`` count at 1.0, so a profile that
        references a level which has since been removed still totals cleanly.
        """
        multipliers = multipliers or {}
        return round(
            sum(
                record.best_total * multipliers.get(level_id, 1.0)
                for level_id, record in self.levels.items()
            ),
            2,
        )

    # -- run artifacts -----------------------------------------------------

    def runs_dir(self) -> Path:
        path = self.path.parent / "runs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save_run(self, level_id: str, payload: dict[str, Any]) -> str:
        run_id = f"{level_id}-{int(time.time())}"
        (self.runs_dir() / f"{run_id}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        return run_id

    def load_run(self, run_id: str) -> dict[str, Any]:
        path = self.runs_dir() / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"no such run: {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[str]:
        return sorted(p.stem for p in self.runs_dir().glob("*.json"))
