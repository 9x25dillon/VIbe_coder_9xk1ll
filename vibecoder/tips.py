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
RULES: list[Rule] = []


def rule(fn: Rule) -> Rule:
    RULES.append(fn)
    return fn


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


@rule
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


@rule
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
        return (
            f"Correct, but your solution executes about {ratio:.1f}x as many "
            f"lines as the reference. Look for work being repeated inside a loop "
            f"that could happen once outside it."
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

    tips: list[str] = []
    for check in RULES:
        try:
            message = check(ctx)
        except Exception:  # noqa: BLE001 - a broken rule must not break the game
            continue
        if message and message not in tips:
            tips.append(message)
        if len(tips) >= limit:
            break
    return tips
