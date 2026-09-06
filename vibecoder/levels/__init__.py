"""Level registry.

Every module in this package that exposes a module-level ``LEVEL`` is picked up
automatically, so adding a level is adding a file. A module exposing ``BOSS``
is registered as a boss fight instead (T3). See docs/LEVEL_AUTHORING.md for the
contract each must satisfy.
"""

from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache

from ..models import BossLevel, Level


@lru_cache(maxsize=1)
def all_levels() -> tuple[Level, ...]:
    levels: list[Level] = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        level = getattr(module, "LEVEL", None)
        if isinstance(level, Level):
            levels.append(level)

    ids = [level.id for level in levels]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate level ids: {sorted(duplicates)}")

    return tuple(sorted(levels, key=lambda lvl: (lvl.world, lvl.index)))


def get_level(level_id: str) -> Level:
    for level in all_levels():
        if level.id == level_id:
            return level
    raise KeyError(f"unknown level: {level_id!r}")


def worlds() -> dict[int, list[Level]]:
    grouped: dict[int, list[Level]] = {}
    for level in all_levels():
        grouped.setdefault(level.world, []).append(level)
    return grouped


@lru_cache(maxsize=1)
def all_bosses() -> tuple[BossLevel, ...]:
    """Every boss fight, discovered the same way levels are.

    Kept separate from `all_levels` rather than folded in behind a flag: a boss
    is a different shape (n functions, ordered steps, per-step tests) and every
    caller that walks levels would otherwise have to remember to ask which kind
    it was holding.
    """
    bosses: list[BossLevel] = []
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{__name__}.{info.name}")
        boss = getattr(module, "BOSS", None)
        if isinstance(boss, BossLevel):
            bosses.append(boss)

    ids = [boss.id for boss in bosses]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise ValueError(f"duplicate boss ids: {sorted(duplicates)}")

    return tuple(sorted(bosses, key=lambda b: (b.world, b.index)))


def get_boss(boss_id: str) -> BossLevel:
    for boss in all_bosses():
        if boss.id == boss_id:
            return boss
    raise KeyError(f"unknown boss: {boss_id!r}")
