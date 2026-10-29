from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Diagnostic:
    rule: str
    severity: str
    message: str
    line: int | None = None
    column: int | None = None
    suggestion: str | None = None


def check_code(source: str) -> list[Diagnostic]:
    """Run a dependency-free validation gate for scene source."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [Diagnostic("python-syntax", "error", exc.msg, exc.lineno, exc.offset)]

    scenes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(_name(base).endswith("Scene") for base in node.bases)
    ]
    if not scenes:
        return [Diagnostic("scene-class", "error", "未找到 Scene 子类")]

    diagnostics: list[Diagnostic] = []
    for scene in scenes:
        if not any(
            isinstance(node, ast.FunctionDef) and node.name == "construct"
            for node in scene.body
        ):
            diagnostics.append(
                Diagnostic(
                    "construct-method",
                    "error",
                    f"场景类 {scene.name} 缺少 construct 方法",
                    scene.lineno,
                    scene.col_offset + 1,
                )
            )
    diagnostics.extend(_RuleVisitor().run(tree))
    return diagnostics


def detect_scene_names(source: str) -> list[str]:
    """Return scene subclasses in source order, or an empty list on syntax errors."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    return [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(_name(base).endswith("Scene") for base in node.bases)
    ]


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name(node.value)}.{node.attr}"
    return ""


class _RuleVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.diagnostics: list[Diagnostic] = []

    def run(self, tree: ast.AST) -> list[Diagnostic]:
        self.visit(tree)
        return self.diagnostics

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        exception_name = _name(node.type) if node.type is not None else ""
        if node.type is None or exception_name in {"Exception", "BaseException"}:
            self.diagnostics.append(
                Diagnostic(
                    "broad-except",
                    "warning",
                    "请捕获更具体的异常类型，避免隐藏真实错误",
                    node.lineno,
                    node.col_offset + 1,
                    "仅捕获预期异常，例如 ValueError、OSError 或 TypeError",
                )
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = _name(node.func)
        if call_name in {"eval", "exec", "compile", "__import__"}:
            self.diagnostics.append(
                Diagnostic(
                    "unsafe-dynamic-execution",
                    "error",
                    f"禁止在生成场景中调用 {call_name}",
                    node.lineno,
                    node.col_offset + 1,
                    "移除动态执行，改用经过验证的结构化场景模型",
                )
            )
        if call_name == "self.play" and not node.args:
            self.diagnostics.append(
                Diagnostic(
                    "empty-play",
                    "error",
                    "self.play 至少需要一个动画参数",
                    node.lineno,
                    node.col_offset + 1,
                    "向 self.play 传入 Animation，例如 ShowCreation(circle)",
                )
            )
        if call_name == "Transform" and len(node.args) < 2:
            self.diagnostics.append(
                Diagnostic(
                    "transform-arguments",
                    "error",
                    "Transform 需要源对象和目标对象",
                    node.lineno,
                    node.col_offset + 1,
                    "使用 Transform(source, target)",
                )
            )
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if _is_none(node.left) or _is_none(node.right):
            self.diagnostics.append(
                Diagnostic(
                    "none-binary-operation",
                    "error",
                    "None 不能直接参与二元运算",
                    node.lineno,
                    node.col_offset + 1,
                    "运算前检查值是否为 None，或提供明确的默认值",
                )
            )
        self.generic_visit(node)


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None
