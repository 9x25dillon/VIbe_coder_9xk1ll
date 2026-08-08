"""Style goals: optional constraints a level can ask the player to satisfy.

Meeting every declared goal earns the elegance bonus. Each checker takes the
parsed AST of the submission and returns True when the goal is met. Checkers
inspect only the target function so that helper code elsewhere in the file does
not accidentally satisfy or break a goal.
"""

from __future__ import annotations

import ast
from typing import Callable

Checker = Callable[[ast.AST], bool]


def _target_function(tree: ast.AST, func_name: str) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == func_name:
                return node
    return None


def _contains(node: ast.AST, *types: type) -> bool:
    return any(isinstance(child, types) for child in ast.walk(node))


def uses_comprehension(node: ast.AST) -> bool:
    return _contains(node, ast.ListComp, ast.SetComp, ast.DictComp)


def uses_generator_expr(node: ast.AST) -> bool:
    return _contains(node, ast.GeneratorExp)


def no_explicit_loop(node: ast.AST) -> bool:
    """No ``for``/``while`` statements. Comprehensions are fine - they are
    expressions, and steering players toward them is the point of the goal."""
    return not any(
        isinstance(child, (ast.For, ast.AsyncFor, ast.While))
        for child in ast.walk(node)
    )


def uses_enumerate(node: ast.AST) -> bool:
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == "enumerate"
        for child in ast.walk(node)
    )


def uses_recursion(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    return any(
        isinstance(child, ast.Call)
        and isinstance(child.func, ast.Name)
        and child.func.id == node.name
        for child in ast.walk(node)
    )


def single_return(node: ast.AST) -> bool:
    return sum(1 for child in ast.walk(node) if isinstance(child, ast.Return)) == 1


def has_type_hints(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    annotated = all(a.annotation is not None for a in node.args.args)
    return bool(node.args.args) and annotated and node.returns is not None


def has_docstring(node: ast.AST) -> bool:
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and bool(
        ast.get_docstring(node)
    )


CHECKERS: dict[str, Checker] = {
    "uses_comprehension": uses_comprehension,
    "uses_generator_expr": uses_generator_expr,
    "no_explicit_loop": no_explicit_loop,
    "uses_enumerate": uses_enumerate,
    "uses_recursion": uses_recursion,
    "single_return": single_return,
    "has_type_hints": has_type_hints,
    "has_docstring": has_docstring,
}

DESCRIPTIONS: dict[str, str] = {
    "uses_comprehension": "build the result with a comprehension",
    "uses_generator_expr": "stream values through a generator expression",
    "no_explicit_loop": "solve it without an explicit for/while loop",
    "uses_enumerate": "use enumerate() instead of indexing by range(len(...))",
    "uses_recursion": "solve it recursively",
    "single_return": "use a single return statement",
    "has_type_hints": "annotate the parameters and return type",
    "has_docstring": "document the function with a docstring",
}


def evaluate(code: str, func_name: str, goals: tuple[str, ...]) -> dict[str, bool]:
    """Evaluate every declared goal against a submission.

    Unparseable code fails every goal rather than raising, because this runs on
    submissions that may not compile.
    """
    if not goals:
        return {}
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {goal: False for goal in goals}

    target = _target_function(tree, func_name)
    if target is None:
        return {goal: False for goal in goals}

    results = {}
    for goal in goals:
        checker = CHECKERS.get(goal)
        if checker is None:
            raise KeyError(f"unknown style goal: {goal!r}")
        results[goal] = checker(target)
    return results


def all_met(results: dict[str, bool]) -> bool:
    return all(results.values()) if results else True
