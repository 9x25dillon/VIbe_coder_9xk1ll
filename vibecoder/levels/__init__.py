"""Level registry.

Every module in this package that exposes a module-level ``LEVEL`` is picked up
automatically, so adding a level is adding a file. See
docs/LEVEL_AUTHORING.md for the contract a level module must satisfy.
"""

from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache

from ..models import Level


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
