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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .daily import Attempt
from .mastery import Mastery, observation
from .models import ScoreBreakdown, VibeVector
from .scoring import streak_multiplier

STATE_VERSION = 1

#: Top-level keys this build understands. Anything else in a profile came from
#: a newer build and is preserved untouched -- see `Session.unknown`.
_KNOWN_KEYS = frozenset({
    "version", "created_at", "updated_at", "vibe_source", "vibe",
    "levels", "streak", "tokens", "total_score", "mastery", "dailies",
})


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
        #: What the player *scores*, per content tag (T4 W1). Deliberately a
        #: separate field from `vibe`, which is what the player *writes*: T4's
        #: exit criterion 8 forbids any screen blending the two, and two
        #: fields are harder to average by accident than two keys in one dict.
        self.mastery = Mastery()
        #: Every daily played, in the order they were played (T5 W2). Stored
        #: with the level and seed that were actually served, never
        #: re-derived: `daily.choose` depends on the build's catalogue, so a
        #: history that recomputed would rewrite what you played the moment a
        #: level was added (Q99).
        self.dailies: list[Attempt] = []
        self.levels: dict[str, LevelRecord] = {}
        self.streak = 0
        self.tokens: dict[str, int] = {"hint": 3, "skip": 1}
        self.total_score = 0.0
        #: Top-level keys written by a build newer than this one, kept
        #: verbatim. `VibeVector` has carried these since S015; the envelope
        #: around it did not, so an old build loading a new profile dropped
        #: every field it had never heard of and re-saved without them --
        #: silently, on an ordinary `vibecoder status`. Adding `mastery` is
        #: what made that live rather than theoretical.
        self.unknown: dict[str, Any] = {}

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
        session.mastery = Mastery.from_json(data.get("mastery", {}))
        session.dailies = [
            Attempt(**{k: v for k, v in entry.items()
                       if k in Attempt.__dataclass_fields__})
            for entry in data.get("dailies", [])
            if isinstance(entry, dict) and "date" in entry
        ]
        session.unknown = {
            key: value for key, value in data.items() if key not in _KNOWN_KEYS
        }
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
            "mastery": self.mastery.to_json(),
            "dailies": [asdict(entry) for entry in self.dailies],
        }
        # Merged rather than nested, so a newer build finds its own fields
        # exactly where it left them. A key this build knows about always
        # wins: `unknown` is what we could not interpret, never an override.
        for key, value in self.unknown.items():
            payload.setdefault(key, value)
        # Write-then-rename so an interrupted save cannot truncate the profile.
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    # -- mutation ----------------------------------------------------------

    def daily_played(self, date: str) -> "Attempt | None":
        """The ranked attempt for ``date``, if there is one."""
        for entry in self.dailies:
            if entry.date == date and entry.ranked:
                return entry
        return None

    def record_daily(self, date: str, level_id: str, seed: int,
                     score: ScoreBreakdown) -> Attempt:
        """Record a completed daily. The first run of a date is the ranked one.

        A daily is one shot at the same problem as everybody else, so a replay
        is kept -- it happened -- but never replaces the score that counts.
        Enforcing that needs no server, which is what makes W2 useful on its
        own rather than a client waiting for W3.
        """
        entry = Attempt(
            date=date, level_id=level_id, seed=seed,
            total=score.total, stars=score.stars,
            ranked=self.daily_played(date) is None,
            at=_now(),
        )
        self.dailies.append(entry)
        return entry

    def current_mastery(self) -> Mastery:
        """Mastery as it reads today, with age taken off it (T4 W6).

        The one place the clock meets the model. `self.mastery` stays the
        record of what was actually measured -- a profile should not rot on
        disk -- and this is the view every decision is made against.
        """
        return self.mastery.as_of(_now())

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
        tags: "Sequence[str]" = (),
    ) -> dict[str, Any]:
        """Bank a completed attempt and return what changed.

        Mastery is updated **here**, which is the whole of T4's exit criterion
        5: practice mode never calls this method, so a practice run cannot
        move mastery by construction rather than by a flag someone has to
        remember to check. `cmd_play` skips `submit` entirely when there is no
        honest solve time -- the same decision that drops the Speed axis (M1)
        -- so the two rules are enforced at one place instead of two.
        """
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

        # The three axes a run scored, reduced to one competence signal, then
        # applied to every tag the level carries. Unpacked here rather than
        # inside `mastery` so that module keeps importing nothing.
        moved = self.mastery.observe(
            list(tags),
            observation(
                accuracy=score.accuracy,
                functional=score.functional,
                first_try="first_try" in score.bonuses,
            ),
            at=_now(),
        )

        self.total_score = self.recompute_total(multipliers)
        return {
            "improved": improved,
            "cleared": cleared,
            "streak": self.streak,
            "streak_multiplier": streak_multiplier(self.streak),
            # What each tag moved by, so a caller can explain the update
            # without recomputing it (T4 W7 forbids hidden state).
            "mastery_moved": moved,
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
