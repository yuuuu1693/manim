from __future__ import annotations

import ast
from dataclasses import dataclass
from difflib import SequenceMatcher

from manimlib.code_checker.static_check import Diagnostic, check_code


@dataclass(frozen=True)
class AppliedFix:
    rule: str
    message: str
    line: int


@dataclass(frozen=True)
class FixResult:
    source: str
    applied: tuple[AppliedFix, ...]
    remaining: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class _Edit:
    start: int
    end: int
    replacement: str
    fix: AppliedFix


def apply_safe_fixes(source: str) -> FixResult:
    """Apply only deterministic fixes that preserve valid Python structure."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return FixResult(source, (), tuple(check_code(source)))

    diagnostics = check_code(source)
    edits = _empty_play_edits(source, tree)
    edits.extend(_undefined_name_edits(source, tree, diagnostics))
    edits = _non_overlapping_edits(edits)
    if not edits:
        return FixResult(source, (), tuple(diagnostics))

    repaired = source
    for edit in sorted(edits, key=lambda item: item.start, reverse=True):
        repaired = repaired[:edit.start] + edit.replacement + repaired[edit.end:]
    return FixResult(
        repaired,
        tuple(edit.fix for edit in sorted(edits, key=lambda item: item.start)),
        tuple(check_code(repaired)),
    )


def _empty_play_edits(source: str, tree: ast.Module) -> list[_Edit]:
    edits: list[_Edit] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if _call_name(call.func) != "self.play" or call.args or call.keywords:
            continue
        start, end = _node_offsets(source, node)
        edits.append(
            _Edit(
                start,
                end,
                "pass",
                AppliedFix("empty-play", "已将空 self.play() 替换为 pass", node.lineno),
            )
        )
    return edits


def _undefined_name_edits(
    source: str,
    tree: ast.Module,
    diagnostics: list[Diagnostic],
) -> list[_Edit]:
    name_nodes = {
        (node.lineno, node.col_offset + 1, node.id): node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    edits: list[_Edit] = []
    for diagnostic in diagnostics:
        if (
            diagnostic.rule != "undefined-variable"
            or diagnostic.line is None
            or diagnostic.column is None
            or diagnostic.symbol is None
        ):
            continue
        node = name_nodes.get(
            (diagnostic.line, diagnostic.column, diagnostic.symbol)
        )
        if node is None:
            continue
        function = _enclosing_function(functions, node)
        if function is None:
            continue
        candidates = _defined_before(function, node.lineno)
        replacement = _unique_close_match(diagnostic.symbol, candidates)
        if replacement is None:
            continue
        start, end = _node_offsets(source, node)
        edits.append(
            _Edit(
                start,
                end,
                replacement,
                AppliedFix(
                    "undefined-variable",
                    f"已将 {diagnostic.symbol} 更正为 {replacement}",
                    node.lineno,
                ),
            )
        )
    return edits


def _defined_before(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    line: int,
) -> set[str]:
    names = {
        argument.arg
        for argument in [
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        ]
    }
    if function.args.vararg is not None:
        names.add(function.args.vararg.arg)
    if function.args.kwarg is not None:
        names.add(function.args.kwarg.arg)

    collector = _PriorDefinitionCollector(line)
    for statement in function.body:
        collector.visit(statement)
    return names | collector.names


class _PriorDefinitionCollector(ast.NodeVisitor):
    def __init__(self, before_line: int) -> None:
        self.before_line = before_line
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store) and node.lineno < self.before_line:
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        if node.lineno < self.before_line:
            self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.lineno < self.before_line:
            self.names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name != "*"
            )

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.lineno < self.before_line:
            self.names.add(node.name)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.lineno < self.before_line:
            self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _unique_close_match(name: str, candidates: set[str]) -> str | None:
    ranked = sorted(
        (
            (SequenceMatcher(None, name, candidate).ratio(), candidate)
            for candidate in candidates
            if candidate != name
        ),
        reverse=True,
    )
    if not ranked or ranked[0][0] < 0.8:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.12:
        return None
    return ranked[0][1]


def _enclosing_function(
    functions: list[ast.FunctionDef | ast.AsyncFunctionDef],
    node: ast.AST,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    matches = [
        function
        for function in functions
        if function.lineno <= node.lineno <= (function.end_lineno or function.lineno)
    ]
    return min(
        matches,
        key=lambda function: (function.end_lineno or function.lineno) - function.lineno,
        default=None,
    )


def _node_offsets(source: str, node: ast.AST) -> tuple[int, int]:
    lines = source.splitlines(keepends=True)
    start = sum(len(line) for line in lines[:node.lineno - 1])
    end_line = node.end_lineno or node.lineno
    end = sum(len(line) for line in lines[:end_line - 1])
    start += _byte_column_to_character(lines[node.lineno - 1], node.col_offset)
    end += _byte_column_to_character(lines[end_line - 1], node.end_col_offset or node.col_offset)
    return start, end


def _byte_column_to_character(line: str, byte_column: int) -> int:
    return len(line.encode("utf-8")[:byte_column].decode("utf-8"))


def _non_overlapping_edits(edits: list[_Edit]) -> list[_Edit]:
    accepted: list[_Edit] = []
    for edit in sorted(edits, key=lambda item: (item.start, item.end)):
        if accepted and edit.start < accepted[-1].end:
            continue
        accepted.append(edit)
    return accepted


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""
