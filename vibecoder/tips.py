"""Vibe Tips: the post-level coaching layer.

A tip fires when a rule finds a specific, actionable pattern in the submission.
Tips are deliberately conservative -- a wrong tip erodes trust in every later
one -- so each rule matches a narrow shape and says what to do instead.

Rules receive a ``TipContext`` and return a message or None. They must never
raise: a submission that reached this point already ran, but it may still be
strange.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable

from .models import RunResult, VibeVector

# A submission must exceed the reference by this factor before the efficiency
# tip fires, leaving room for ordinary variation between correct solutions.
OPS_TIP_FACTOR = 1.6


@dataclass
class TipContext:
    code: str
    func_name: str
    tree: ast.AST | None
    result: RunResult
    ref_ops: int
    vibe: VibeVector | None
    style_results: dict[str, bool]


Rule = Callable[[TipContext], str | None]

#: A rule about whether the code is *right*. These are the only ones worth
#: showing to somebody whose program does not work yet.
CORRECTNESS = "correctness"
#: A rule about whether working code is idiomatic or efficient. Useful once it
#: runs, noise before that.
POLISH = "polish"

RULES: list[Rule] = []
KINDS: dict[str, str] = {}


def rule(fn: Rule | None = None, *, kind: str = POLISH):
    """Register a tip rule. ``kind`` decides when it is allowed to speak."""
    def register(target: Rule) -> Rule:
        RULES.append(target)
        KINDS[target.__name__] = kind
        return target

    return register(fn) if fn is not None else register


def _target(ctx: TipContext) -> ast.AST | None:
    if ctx.tree is None:
        return None
    for node in ast.walk(ctx.tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == ctx.func_name:
                return node
    return None


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

@rule
def accumulator_loop(ctx: TipContext) -> str | None:
    """A for loop whose only body is ``result.append(...)`` is a comprehension."""
    target = _target(ctx)
    if target is None:
        return None
    for node in ast.walk(target):
        if not isinstance(node, ast.For) or len(node.body) != 1:
            continue
        statement = node.body[0]
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and statement.value.func.attr == "append"
        ):
            return (
                "That loop only appends to a list. A list comprehension says the "
                "same thing in one line, and a generator expression says it "
                "without building the list at all."
            )
    return None


@rule(kind=CORRECTNESS)
def range_len_indexing(ctx: TipContext) -> str | None:
    target = _target(ctx)
    if target is None:
        return None
    for node in ast.walk(target):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "range"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "len"
        ):
            return (
                "`range(len(xs))` means you want both the index and the item - "
                "`enumerate(xs)` gives you both without the indexing."
            )
    return None


@rule(kind=CORRECTNESS)
def range_len_off_by_one(ctx: TipContext) -> str | None:
    """``range(len(xs) + 1)``: the loop that always walks one past the end.

    Narrow on purpose. It matches the literal ``+ 1`` on a ``len()`` inside a
    ``range()``, which is a bug with exactly one cause and one fix -- unlike
    a general "you got an IndexError" message, which a player can already see.
    """
    target = _target(ctx)
    if target is None:
        return None
    for node in ast.walk(target):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "range"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.BinOp)
            and isinstance(node.args[0].op, ast.Add)
        ):
            continue
        left, right = node.args[0].left, node.args[0].right
        adds_one = isinstance(right, ast.Constant) and right.value == 1
        is_len = (
            isinstance(left, ast.Call)
            and isinstance(left.func, ast.Name)
            and left.func.id == "len"
        )
        if adds_one and is_len:
            return (
                "`range(len(xs) + 1)` takes one step past the end of the list, "
                "so the last index does not exist. A list of 4 items has "
                "indexes 0 to 3, and `range(len(xs))` stops in the right place."
            )
    return None


@rule
def manual_sum(ctx: TipContext) -> str | None:
    """``total = 0`` followed by ``total += ...`` inside a loop."""
    target = _target(ctx)
    if target is None:
        return None
    for node in ast.walk(target):
        if not isinstance(node, (ast.For, ast.While)):
            continue
        for statement in ast.walk(node):
            if (
                isinstance(statement, ast.AugAssign)
                and isinstance(statement.op, ast.Add)
                and isinstance(statement.target, ast.Name)
            ):
                return (
                    "Accumulating with `+=` in a loop is what `sum()` does - "
                    "`sum(x.price for x in items)` keeps the intent in one place."
                )
    return None


@rule
def string_concat_in_loop(ctx: TipContext) -> str | None:
    target = _target(ctx)
    if target is None:
        return None
    for node in ast.walk(target):
        if not isinstance(node, (ast.For, ast.While)):
            continue
        for statement in ast.walk(node):
            if (
                isinstance(statement, ast.AugAssign)
                and isinstance(statement.op, ast.Add)
                and isinstance(statement.value, (ast.Constant, ast.JoinedStr))
                and isinstance(getattr(statement.value, "value", ""), str)
            ):
                return (
                    "Growing a string with `+=` in a loop copies it every time. "
                    "Collect the pieces and `''.join(pieces)` once at the end."
                )
    return None


@rule(kind=CORRECTNESS)
def bare_except(ctx: TipContext) -> str | None:
    target = _target(ctx)
    if target is None:
        return None
    for node in ast.walk(target):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            return (
                "A bare `except:` swallows `KeyboardInterrupt` and every bug you "
                "have not written yet. Catch the exception you actually expect."
            )
    return None


@rule
def inefficient_versus_reference(ctx: TipContext) -> str | None:
    if not ctx.result.all_passed or ctx.ref_ops <= 0 or ctx.result.ops <= 0:
        return None
    ratio = ctx.result.ops / ctx.ref_ops
    if ratio >= OPS_TIP_FACTOR:
        # State the measurement, and name the usual causes as possibilities
        # rather than as a diagnosis. The op count says *how much* work was
        # done, never *why*, and this rule has not looked. Claiming "work
        # repeated inside a loop" on a solution whose only cost is `append`
        # versus a comprehension sends a beginner hunting for a bug that is
        # not there, and a confidently wrong tip is worse than none (Q33).
        return (
            f"Correct, but your solution executes about {ratio:.1f}x as many "
            f"lines as the reference. That usually means an extra pass over "
            f"the data, or work inside a loop that could happen once outside "
            f"it."
        )
    return None


@rule
def nested_loop_lookup(ctx: TipContext) -> str | None:
    """A loop inside a loop where the inner one only searches for membership."""
    target = _target(ctx)
    if target is None:
        return None
    for node in ast.walk(target):
        if not isinstance(node, ast.For):
            continue
        inner = [c for c in ast.walk(node) if isinstance(c, ast.For) and c is not node]
        if inner:
            return (
                "Nested loops over two collections is O(n*m). If the inner loop "
                "is looking things up, build a `set` or `dict` first and the "
                "lookup drops to O(1)."
            )
    return None


@rule
def missing_type_hints_for_typed_player(ctx: TipContext) -> str | None:
    """Only fires when the player's own codebase says they normally annotate."""
    if ctx.vibe is None:
        return None
    if ctx.vibe.patterns.get("type_hints", 0.0) < 0.5:
        return None
    target = _target(ctx)
    if not isinstance(target, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    if target.returns is None and not any(
        a.annotation is not None for a in target.args.args
    ):
        return (
            "Your own codebase annotates over half of its functions - this "
            "submission has no hints at all. Worth staying consistent."
        )
    return None


@rule
def unused_style_goals(ctx: TipContext) -> str | None:
    missed = [goal for goal, met in ctx.style_results.items() if not met]
    if not missed:
        return None
    from .style import DESCRIPTIONS

    described = "; ".join(DESCRIPTIONS.get(goal, goal) for goal in missed)
    return f"Style goal missed (worth +5%): {described}."


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------

def generate(
    code: str,
    func_name: str,
    result: RunResult,
    *,
    ref_ops: int = 0,
    vibe: VibeVector | None = None,
    style_results: dict[str, bool] | None = None,
    limit: int = 3,
) -> list[str]:
    """Run every rule and return at most ``limit`` tips, best-first."""
    try:
        tree: ast.AST | None = ast.parse(code)
    except SyntaxError:
        return []

    ctx = TipContext(
        code=code,
        func_name=func_name,
        tree=tree,
        result=result,
        ref_ops=ref_ops,
        vibe=vibe,
        style_results=style_results or {},
    )

    # A run where nothing passed is not a style conversation. The player has a
    # broken program and needs the failure, which the results block already
    # shows; advice about comprehensions on top of it reads as the game missing
    # the point. Only correctness rules speak here -- and if none of them has
    # anything to say, saying nothing is the right answer.
    candidates = RULES
    if result.outcomes and result.passed_count == 0:
        candidates = [r for r in RULES if KINDS.get(r.__name__) == CORRECTNESS]

    tips: list[str] = []
    for check in candidates:
        try:
            message = check(ctx)
        except Exception:  # noqa: BLE001 - a broken rule must not break the game
            continue
        if message and message not in tips:
            tips.append(message)
        if len(tips) >= limit:
            break
    return tips
