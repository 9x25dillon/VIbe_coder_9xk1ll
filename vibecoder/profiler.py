"""The Vibe Profiler: static analysis of a codebase into a Vibe Vector.

The profiler walks every ``.py`` file under a root directory and extracts the
signals the game uses to personalise content: which libraries the player
reaches for, which constructs they favour, how long their functions run, how
they name things, and which exceptions they actually handle.

Nothing here executes the analysed code. Files that fail to parse are counted
and skipped -- a codebase with a Python 2 file in it should still profile.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

from .models import VibeVector

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env",
    "node_modules", ".tox", ".mypy_cache", ".pytest_cache", "build", "dist",
    ".eggs", "site-packages",
}

# ``__future__`` says nothing about what a player likes to build with.
IGNORED_LIBRARIES = {"__future__"}

# Libraries mapped to the content tags that drive level selection. Only the
# top-level module name is matched, so ``pandas.io.parsers`` counts as pandas.
LIBRARY_TAGS: dict[str, tuple[str, ...]] = {
    "pandas": ("data", "tabular"),
    "numpy": ("data", "numeric"),
    "polars": ("data", "tabular"),
    "csv": ("data", "tabular"),
    "json": ("data", "serialisation"),
    "sqlite3": ("data", "storage"),
    "sqlalchemy": ("data", "storage"),
    "requests": ("web", "http"),
    "httpx": ("web", "http"),
    "urllib": ("web", "http"),
    "aiohttp": ("web", "http", "async"),
    "bs4": ("web", "scraping"),
    "lxml": ("web", "scraping"),
    "scrapy": ("web", "scraping"),
    "flask": ("web", "server"),
    "fastapi": ("web", "server"),
    "django": ("web", "server"),
    "re": ("text", "regex"),
    "collections": ("algorithms", "datastructures"),
    "itertools": ("functional", "algorithms"),
    "functools": ("functional",),
    "operator": ("functional",),
    "heapq": ("algorithms", "datastructures"),
    "bisect": ("algorithms", "datastructures"),
    "asyncio": ("async",),
    "threading": ("concurrency",),
    "multiprocessing": ("concurrency",),
    "pathlib": ("io",),
    "os": ("io",),
    "datetime": ("time",),
    "math": ("numeric",),
    "random": ("numeric",),
    "unittest": ("testing",),
    "pytest": ("testing",),
    "dataclasses": ("oop",),
    "typing": ("typing",),
    "torch": ("ml",),
    "sklearn": ("ml",),
    "tensorflow": ("ml",),
}

# A pattern must clear this share of its denominator before it earns a tag.
TAG_PATTERN_THRESHOLD = 0.35

PATTERN_TAGS: dict[str, str] = {
    "comprehension": "functional",
    "generator_expr": "functional",
    "lambda": "functional",
    "map_filter_reduce": "functional",
    "decorator": "metaprogramming",
    "class": "oop",
    "type_hints": "typing",
    "async": "async",
    "recursion": "algorithms",
    "context_manager": "io",
}


# Patterns counted per function rather than per file: asking "what share of
# this player's functions are decorated" is meaningful, while "what share of
# files contain a decorator" is not.
PER_FUNCTION_PATTERNS = {"decorator", "type_hints", "recursion", "async"}


class _FileStats:
    """Per-file accumulator. Kept separate so a parse failure loses one file."""

    def __init__(self) -> None:
        self.functions = 0
        self.function_lines = 0
        self.docstrings = 0
        self.classes = 0
        self.max_complexity = 0
        self.libraries: Counter[str] = Counter()
        self.exceptions: Counter[str] = Counter()
        self.patterns: Counter[str] = Counter()
        self.names: Counter[str] = Counter()


def _naming_style(name: str) -> str | None:
    if not name or name.startswith("__"):
        return None
    stripped = name.lstrip("_")
    if not stripped or not stripped[0].isalpha():
        return None
    if stripped.isupper():
        return "SCREAMING_SNAKE"
    if "_" in stripped and stripped.islower():
        return "snake_case"
    if stripped.islower():
        return "snake_case"  # a single lowercase word is idiomatic snake_case
    if stripped[0].islower() and any(c.isupper() for c in stripped):
        return "camelCase"
    if stripped[0].isupper():
        return "PascalCase"
    return None


def _complexity(node: ast.AST) -> int:
    """Cyclomatic complexity: one plus every branch point.

    This mirrors what radon reports closely enough for level calibration, with
    no dependency. Boolean operators count their extra operands because each
    one is a short-circuit branch.
    """
    score = 1
    for child in ast.walk(node):
        if isinstance(child, (ast.If, ast.For, ast.AsyncFor, ast.While,
                              ast.ExceptHandler, ast.With, ast.AsyncWith,
                              ast.Assert, ast.IfExp)):
            score += 1
        elif isinstance(child, ast.BoolOp):
            score += len(child.values) - 1
        elif isinstance(child, (ast.comprehension,)):
            score += 1 + len(child.ifs)
    return score


def _analyse_tree(tree: ast.AST, stats: _FileStats) -> None:
    for node in ast.walk(tree):
        # --- imports ---
        if isinstance(node, ast.Import):
            for alias in node.names:
                stats.libraries[alias.name.split(".")[0]] += 1
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                stats.libraries[node.module.split(".")[0]] += 1

        # --- functions ---
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stats.functions += 1
            end = getattr(node, "end_lineno", node.lineno) or node.lineno
            stats.function_lines += max(1, end - node.lineno + 1)
            if ast.get_docstring(node):
                stats.docstrings += 1
            if node.decorator_list:
                stats.patterns["decorator"] += 1
            if isinstance(node, ast.AsyncFunctionDef):
                stats.patterns["async"] += 1
            if node.returns is not None or any(
                a.annotation is not None for a in node.args.args
            ):
                stats.patterns["type_hints"] += 1
            if any(
                isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name)
                and c.func.id == node.name
                for c in ast.walk(node)
            ):
                stats.patterns["recursion"] += 1
            stats.max_complexity = max(stats.max_complexity, _complexity(node))
            style = _naming_style(node.name)
            if style:
                stats.names[style] += 1

        # --- classes ---
        elif isinstance(node, ast.ClassDef):
            stats.classes += 1
            stats.patterns["class"] += 1

        # --- expressions and statements ---
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp)):
            stats.patterns["comprehension"] += 1
        elif isinstance(node, ast.GeneratorExp):
            stats.patterns["generator_expr"] += 1
        elif isinstance(node, ast.Lambda):
            stats.patterns["lambda"] += 1
        elif isinstance(node, ast.JoinedStr):
            stats.patterns["fstring"] += 1
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            stats.patterns["context_manager"] += 1
        elif isinstance(node, ast.Try):
            stats.patterns["try_except"] += 1
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"map", "filter", "reduce"}:
                stats.patterns["map_filter_reduce"] += 1

        # --- caught exceptions ---
        elif isinstance(node, ast.ExceptHandler):
            names = node.type
            if isinstance(names, ast.Name):
                stats.exceptions[names.id] += 1
            elif isinstance(names, ast.Tuple):
                for element in names.elts:
                    if isinstance(element, ast.Name):
                        stats.exceptions[element.id] += 1
            elif names is None:
                stats.exceptions["bare-except"] += 1

        # --- variable names ---
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            style = _naming_style(node.id)
            if style:
                stats.names[style] += 1


def _merge(target: _FileStats, other: _FileStats) -> None:
    target.functions += other.functions
    target.function_lines += other.function_lines
    target.docstrings += other.docstrings
    target.classes += other.classes
    target.max_complexity = max(target.max_complexity, other.max_complexity)
    target.libraries.update(other.libraries)
    target.exceptions.update(other.exceptions)
    target.patterns.update(other.patterns)
    target.names.update(other.names)


def iter_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def profile_path(root: str | Path, *, top_libraries: int = 15) -> VibeVector:
    """Build a Vibe Vector from every Python file under ``root``."""
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"no such path: {root}")
    if root.is_file():
        paths = [root]
    else:
        paths = iter_python_files(root)

    totals = _FileStats()
    files_with_pattern: Counter[str] = Counter()
    parsed_files = 0
    code_lines = 0

    for path in paths:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError, ValueError):
            continue
        parsed_files += 1
        code_lines += sum(
            1 for line in source.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )

        # Analysed per file so that file-level patterns can be reported as the
        # share of files using them, which stays interpretable however large
        # the codebase gets.
        per_file = _FileStats()
        _analyse_tree(tree, per_file)
        files_with_pattern.update(per_file.patterns.keys())
        _merge(totals, per_file)

    for library in IGNORED_LIBRARIES:
        totals.libraries.pop(library, None)

    functions = max(1, totals.functions)
    denominator_files = max(1, parsed_files)
    patterns: dict[str, float] = {}
    for key, count in totals.patterns.items():
        if key in PER_FUNCTION_PATTERNS:
            # "share of functions that do this"
            patterns[key] = round(min(1.0, count / functions), 3)
        else:
            # "share of files that do this at all" - a raw count over files
            # saturates immediately for anything common, e.g. f-strings.
            patterns[key] = round(files_with_pattern[key] / denominator_files, 3)

    name_total = sum(totals.names.values()) or 1
    naming = {
        style: round(count / name_total, 3)
        for style, count in totals.names.most_common()
    }

    vibe = VibeVector(
        files=parsed_files,
        functions=totals.functions,
        code_lines=code_lines,
        libraries=dict(totals.libraries.most_common(top_libraries)),
        patterns=patterns,
        exceptions_caught=dict(totals.exceptions.most_common(10)),
        avg_function_lines=round(totals.function_lines / functions, 2),
        max_complexity=totals.max_complexity,
        docstring_ratio=round(totals.docstrings / functions, 3),
        naming=naming,
    )
    vibe.tags = derive_tags(vibe)
    return vibe


def derive_tags(vibe: VibeVector) -> list[str]:
    """Collapse libraries and patterns into the content tags levels are keyed on."""
    tags: Counter[str] = Counter()
    for library, count in vibe.libraries.items():
        for tag in LIBRARY_TAGS.get(library, ()):
            tags[tag] += count
    for pattern, share in vibe.patterns.items():
        tag = PATTERN_TAGS.get(pattern)
        if tag and share >= TAG_PATTERN_THRESHOLD:
            tags[tag] += 1
    return [tag for tag, _ in tags.most_common()]


def recommend(
    levels: list,
    vibe: VibeVector,
    *,
    comfort_weight: float = 0.4,
    gap_weight: float = 0.6,
) -> list:
    """Order levels by how useful they are to this player.

    The ranking leans toward *gaps* -- tags the player's codebase shows little
    or no evidence of -- because the stated goal of the Vibe Vector is to fill
    knowledge gaps, not to replay strengths. Comfort still carries weight so
    that the queue stays recognisable rather than throwing a pandas-only player
    straight into async.
    """
    known = set(vibe.tags)

    def rank(level) -> tuple[float, int, int]:
        level_tags = set(level.tags)
        if not level_tags:
            return (0.0, level.world, level.index)
        comfort = len(level_tags & known) / len(level_tags)
        gap = len(level_tags - known) / len(level_tags)
        score = comfort_weight * comfort + gap_weight * gap
        # Negative score sorts descending; world/index break ties in play order.
        return (-score, level.world, level.index)

    return sorted(levels, key=rank)
