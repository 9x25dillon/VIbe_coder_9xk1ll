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
    "generator_function": "functional",
    "builtin_aggregate": "functional",
    "enumerate": "loops",
    "zip": "loops",
    "dataclass": "oop",
    "property": "oop",
}


# Patterns counted per function rather than per file: asking "what share of
# this player's functions are decorated" is meaningful, while "what share of
# files contain a decorator" is not.
PER_FUNCTION_PATTERNS = {
    "decorator", "type_hints", "recursion", "async",
    # Everything counted once per function in `_visit_function` belongs here:
    # normalising a per-function tally over files reports a share of the wrong
    # denominator, and reads as a larger habit than it is.
    "star_args", "keyword_only_args", "generator_function", "nested_function",
    "property", "static_or_class_method",
}


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
        #: PEP 8 conformance, counted per identifier kind rather than pooled.
        #: See :data:`CONVENTIONS` for why the split matters.
        self.conventions: Counter[str] = Counter()
        #: Every function's complexity, kept rather than reduced, so the
        #: profile can report a distribution instead of one outlier.
        self.complexities: list[int] = []
        #: Every function's deepest level of nested control flow.
        self.depths: list[int] = []


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


#: The PEP 8 convention expected of each kind of identifier.
#:
#: These are counted separately rather than pooled into ``naming`` because a
#: single "PascalCase share" cannot tell a correctly named class from a
#: Java-style function name -- the two are the same token shape and opposite
#: verdicts. Pooling them was why class names were left out of ``naming``
#: entirely, which lost the signal rather than fixing the conflation.
#: ``ast.Match`` exists from Python 3.10. The game supports 3.10+, so this is
#: always present today -- it stays a lookup rather than a hard reference so
#: that profiling never depends on the analysing interpreter being newer than
#: the analysed code.
_MATCH = getattr(ast, "Match", None)

CONVENTIONS = {
    "class": "PascalCase",
    "function": "snake_case",
    "constant": "SCREAMING_SNAKE",
}

#: Display plurals for :data:`CONVENTIONS`. "classs" is the reason this exists.
CONVENTION_PLURALS = {
    "class": "classes",
    "function": "functions",
    "constant": "constants",
}


def _nesting_depth(node: ast.AST) -> int:
    """Deepest level of nested control flow inside ``node``.

    A proxy for a habit that survives every naming and formatting choice:
    whether somebody returns early, or keeps stepping to the right.

    Two things make this a statement walk rather than an ``ast.walk``:

    * ``ast.walk`` flattens the tree, and depth is the one thing it discards.
    * An ``elif`` chain is *nested* in the AST -- each ``elif`` is an ``If``
      inside the previous one's ``orelse`` -- and *flat* on the screen. Counting
      the AST shape reported this module's own dispatch chain as 22 levels deep
      when it is one. A reader's indentation is the thing being measured, so
      the chain counts once.

    A nested function starts its own budget: its body is not the enclosing
    function's indentation and is not charged to it.
    """
    skip = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
    loops = (ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith)

    def walk_body(body: list, depth: int) -> int:
        deepest = depth
        for statement in body:
            if isinstance(statement, skip):
                continue
            if isinstance(statement, ast.If):
                deepest = max(deepest, walk_if(statement, depth))
            elif isinstance(statement, loops):
                deepest = max(deepest, walk_body(statement.body, depth + 1))
                deepest = max(
                    deepest, walk_body(getattr(statement, "orelse", []), depth + 1)
                )
            elif isinstance(statement, ast.Try):
                for block in (statement.body, statement.orelse,
                              statement.finalbody):
                    deepest = max(deepest, walk_body(block, depth + 1))
                for handler in statement.handlers:
                    deepest = max(deepest, walk_body(handler.body, depth + 1))
            elif _MATCH is not None and isinstance(statement, _MATCH):
                for case in statement.cases:
                    deepest = max(deepest, walk_body(case.body, depth + 1))
        return deepest

    def walk_if(statement: ast.If, depth: int) -> int:
        deepest = walk_body(statement.body, depth + 1)
        orelse = statement.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            deepest = max(deepest, walk_if(orelse[0], depth))  # an `elif`
        else:
            deepest = max(deepest, walk_body(orelse, depth + 1))
        return deepest

    return walk_body(list(getattr(node, "body", [])), 0)


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


def _decorator_name(node: ast.AST) -> str | None:
    """The bare name of a decorator, however it was written.

    ``@dataclass``, ``@dataclasses.dataclass`` and ``@dataclass(frozen=True)``
    are the same decision by the author and should count once.
    """
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _own_body(node: ast.AST):
    """Every node belonging to ``node`` itself, not to a function inside it.

    ``ast.walk`` would descend into nested definitions, which makes a `yield`
    in a closure look like the enclosing function is a generator. It is not,
    and the difference is exactly the sort of thing this profiler is for.
    """
    stack = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        yield current
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef,
                                ast.ClassDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(current))


def _record_constants(tree: ast.AST, stats: _FileStats) -> None:
    """SCREAMING_SNAKE conformance, for module-level assignments only.

    Scoped to module level on purpose: a name bound inside a function is a
    local variable whatever it looks like, and judging it against the constant
    convention would report every loop counter as a violation.
    """
    for node in getattr(tree, "body", []):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if not isinstance(target, ast.Name) or target.id.startswith("_"):
                continue
            stats.conventions["constant_total"] += 1
            if _naming_style(target.id) == CONVENTIONS["constant"]:
                stats.conventions["constant_ok"] += 1


#: Node types whose mere presence is the whole signal, mapped to the pattern
#: they record. Everything needing more than "it appeared" gets a handler
#: below instead.
_PRESENCE_PATTERNS: dict[type, str] = {
    ast.ListComp: "comprehension",
    ast.SetComp: "comprehension",
    ast.DictComp: "comprehension",
    ast.GeneratorExp: "generator_expr",
    ast.Lambda: "lambda",
    ast.JoinedStr: "fstring",
    ast.With: "context_manager",
    ast.AsyncWith: "context_manager",
    ast.Try: "try_except",
    ast.NamedExpr: "walrus",
    ast.IfExp: "ternary",
    ast.Global: "global_statement",
}
if _MATCH is not None:
    _PRESENCE_PATTERNS[_MATCH] = "match_statement"


def _visit_import(node: ast.Import, stats: _FileStats) -> None:
    for alias in node.names:
        stats.libraries[alias.name.split(".")[0]] += 1


def _visit_import_from(node: ast.ImportFrom, stats: _FileStats) -> None:
    # A relative import names a module inside the codebase being profiled, not
    # a library its author chose to depend on.
    if node.module and node.level == 0:
        stats.libraries[node.module.split(".")[0]] += 1


def _visit_function(node: ast.AST, stats: _FileStats) -> None:
    stats.functions += 1
    end = getattr(node, "end_lineno", node.lineno) or node.lineno
    stats.function_lines += max(1, end - node.lineno + 1)
    if ast.get_docstring(node):
        stats.docstrings += 1

    if node.decorator_list:
        stats.patterns["decorator"] += 1
    for decorator in node.decorator_list:
        label = _decorator_name(decorator)
        if label == "property":
            stats.patterns["property"] += 1
        elif label in {"staticmethod", "classmethod"}:
            stats.patterns["static_or_class_method"] += 1

    if isinstance(node, ast.AsyncFunctionDef):
        stats.patterns["async"] += 1
    if node.args.vararg or node.args.kwarg:
        stats.patterns["star_args"] += 1
    if node.args.kwonlyargs:
        stats.patterns["keyword_only_args"] += 1
    if node.returns is not None or any(
        a.annotation is not None for a in node.args.args
    ):
        stats.patterns["type_hints"] += 1

    body = list(_own_body(node))
    if any(isinstance(c, (ast.Yield, ast.YieldFrom)) for c in body):
        stats.patterns["generator_function"] += 1
    if any(isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef)) for c in body):
        stats.patterns["nested_function"] += 1
    if any(
        isinstance(c, ast.Call)
        and isinstance(c.func, ast.Name)
        and c.func.id == node.name
        for c in ast.walk(node)
    ):
        stats.patterns["recursion"] += 1

    score = _complexity(node)
    stats.complexities.append(score)
    stats.max_complexity = max(stats.max_complexity, score)
    stats.depths.append(_nesting_depth(node))

    style = _naming_style(node.name)
    if style:
        stats.names[style] += 1
    stats.conventions["function_total"] += 1
    if style == CONVENTIONS["function"]:
        stats.conventions["function_ok"] += 1


def _visit_class(node: ast.ClassDef, stats: _FileStats) -> None:
    stats.classes += 1
    stats.patterns["class"] += 1
    stats.conventions["class_total"] += 1
    if _naming_style(node.name) == CONVENTIONS["class"]:
        stats.conventions["class_ok"] += 1
    if any(
        _decorator_name(d) in {"dataclass", "attrs", "define"}
        for d in node.decorator_list
    ):
        stats.patterns["dataclass"] += 1
    if any(
        isinstance(c, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__slots__"
            for target in c.targets
        )
        for c in node.body
    ):
        stats.patterns["slots"] += 1


#: Builtins whose use is a style choice worth recording, mapped to the pattern.
_CALL_PATTERNS = {
    "map": "map_filter_reduce",
    "filter": "map_filter_reduce",
    "reduce": "map_filter_reduce",
    "enumerate": "enumerate",
    "zip": "zip",
    "any": "builtin_aggregate",
    "all": "builtin_aggregate",
    "sum": "builtin_aggregate",
    "min": "builtin_aggregate",
    "max": "builtin_aggregate",
    "sorted": "builtin_aggregate",
}


def _visit_call(node: ast.Call, stats: _FileStats) -> None:
    if isinstance(node.func, ast.Name):
        pattern = _CALL_PATTERNS.get(node.func.id)
        if pattern:
            stats.patterns[pattern] += 1
    elif isinstance(node.func, ast.Attribute):
        # `"{}".format(x)` is a formatting era, the way an f-string is. Only
        # on a literal receiver, so `logger.format(...)` is not miscounted.
        if node.func.attr == "format" and isinstance(node.func.value, ast.Constant):
            stats.patterns["str_format"] += 1


def _visit_binop(node: ast.BinOp, stats: _FileStats) -> None:
    # `"%s" % value`. Only when the left side is literally a string, so
    # arithmetic modulo is not mistaken for formatting.
    if (
        isinstance(node.op, ast.Mod)
        and isinstance(node.left, ast.Constant)
        and isinstance(node.left.value, str)
    ):
        stats.patterns["percent_format"] += 1


def _visit_except(node: ast.ExceptHandler, stats: _FileStats) -> None:
    caught = node.type
    if isinstance(caught, ast.Name):
        stats.exceptions[caught.id] += 1
    elif isinstance(caught, ast.Tuple):
        for element in caught.elts:
            if isinstance(element, ast.Name):
                stats.exceptions[element.id] += 1
    elif caught is None:
        stats.exceptions["bare-except"] += 1


def _visit_name(node: ast.Name, stats: _FileStats) -> None:
    if not isinstance(node.ctx, ast.Store):
        return
    style = _naming_style(node.id)
    if style:
        stats.names[style] += 1


#: Node type to handler. A dispatch table rather than an ``elif`` chain
#: because this module's own metrics condemned the chain: at twenty-odd
#: branches it was the most complex function in the codebase by a factor of
#: two, and a profiler that cannot survive its own report is not worth
#: trusting. Exact types, not ``isinstance`` -- every key here is a concrete
#: AST class, and async variants are registered explicitly.
_HANDLERS: dict[type, object] = {
    ast.Import: _visit_import,
    ast.ImportFrom: _visit_import_from,
    ast.FunctionDef: _visit_function,
    ast.AsyncFunctionDef: _visit_function,
    ast.ClassDef: _visit_class,
    ast.Call: _visit_call,
    ast.BinOp: _visit_binop,
    ast.ExceptHandler: _visit_except,
    ast.Name: _visit_name,
}


def _analyse_tree(tree: ast.AST, stats: _FileStats) -> None:
    """Accumulate every signal this module reads from one parsed file."""
    _record_constants(tree, stats)
    for node in ast.walk(tree):
        handler = _HANDLERS.get(type(node))
        if handler is not None:
            handler(node, stats)
            continue
        pattern = _PRESENCE_PATTERNS.get(type(node))
        if pattern is not None:
            stats.patterns[pattern] += 1


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
    target.conventions.update(other.conventions)
    target.complexities.extend(other.complexities)
    target.depths.extend(other.depths)


def _percentile(values: list[int], fraction: float) -> float:
    """Nearest-rank percentile. Empty input is 0.0.

    Deliberately not an interpolating percentile: these are counts of branches
    and levels of indentation, and a p90 complexity of 8.4 would be reporting
    a precision the underlying integer does not have.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return float(ordered[index])


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
    comment_lines = 0

    for path in paths:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source)
        except (SyntaxError, OSError, ValueError):
            continue
        parsed_files += 1
        for line in source.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                comment_lines += 1
            else:
                code_lines += 1

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

    # PEP 8 conformance per identifier kind. A kind with nothing to judge is
    # left out rather than reported as 0%, which would read as "you name every
    # class wrongly" for a codebase that has no classes.
    conventions: dict[str, float] = {}
    for kind in CONVENTIONS:
        seen = totals.conventions.get(f"{kind}_total", 0)
        if seen:
            conventions[kind] = round(
                totals.conventions.get(f"{kind}_ok", 0) / seen, 3
            )

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
        conventions=conventions,
        median_complexity=_percentile(totals.complexities, 0.5),
        p90_complexity=_percentile(totals.complexities, 0.9),
        avg_nesting=round(
            sum(totals.depths) / len(totals.depths), 2
        ) if totals.depths else 0.0,
        max_nesting=max(totals.depths) if totals.depths else 0,
        comment_density=round(
            comment_lines / max(1, comment_lines + code_lines), 3
        ),
    )
    vibe.tags = derive_tags(vibe)
    return vibe


#: One readable trait per rule: ``(label, test)``. Ordered from the traits
#: people recognise themselves by down to the incidental ones, because only
#: the first few are shown.
#:
#: Every threshold here is a judgement about *style*, never about quality. A
#: codebase with deep nesting and no type hints is not being marked down; the
#: profiler's whole job is to describe how somebody writes so the game can
#: meet them there, and a signature that reads as a scolding would make people
#: stop running it.
SIGNATURE_RULES: list[tuple[str, object]] = [
    ("strongly typed", lambda v: v.patterns.get("type_hints", 0) >= 0.7),
    ("untyped", lambda v: v.patterns.get("type_hints", 0) <= 0.05),
    ("comprehension-first", lambda v: v.patterns.get("comprehension", 0) >= 0.5),
    ("loop-first", lambda v: v.patterns.get("comprehension", 0) <= 0.1),
    ("generator-heavy", lambda v: v.patterns.get("generator_function", 0) >= 0.15),
    ("object-oriented", lambda v: v.patterns.get("class", 0) >= 0.5),
    ("function-oriented", lambda v: v.patterns.get("class", 0) <= 0.15),
    ("modern syntax", lambda v: max(
        v.patterns.get("walrus", 0), v.patterns.get("match_statement", 0)
    ) >= 0.1),
    ("f-string era", lambda v: v.patterns.get("fstring", 0) >= 0.5),
    ("%-format era", lambda v: v.patterns.get("percent_format", 0) >= 0.2),
    ("shallow nesting", lambda v: 0 < v.avg_nesting <= 1.2),
    ("deeply nested", lambda v: v.avg_nesting >= 2.5),
    ("short functions", lambda v: 0 < v.avg_function_lines <= 12),
    ("long functions", lambda v: v.avg_function_lines >= 30),
    ("simple control flow", lambda v: 0 < v.p90_complexity <= 5),
    ("branch-heavy", lambda v: v.p90_complexity >= 12),
    ("documented", lambda v: v.docstring_ratio >= 0.6),
    ("sparsely documented", lambda v: v.docstring_ratio <= 0.15),
    ("heavily commented", lambda v: v.comment_density >= 0.2),
    ("async", lambda v: v.patterns.get("async", 0) >= 0.1),
    ("PEP 8 throughout", lambda v: v.conventions and min(v.conventions.values()) >= 0.9),
    ("mixed naming conventions", lambda v: v.conventions and min(v.conventions.values()) <= 0.6),
]


def style_signature(vibe: VibeVector, *, limit: int = 4) -> list[str]:
    """A few words describing how this codebase is written.

    The numbers above it are the evidence; this is the sentence somebody
    actually reads. It exists because "docstring_ratio 0.43" tells a player
    nothing about themselves, and "sparsely documented, flat, early-returning"
    tells them something they can recognise and argue with -- and arguing with
    it means they looked, which is the point.
    """
    traits = [label for label, test in SIGNATURE_RULES if test(vibe)]
    return traits[:limit]


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
