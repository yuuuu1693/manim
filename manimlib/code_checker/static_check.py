from __future__ import annotations

import ast
import builtins
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
    diagnostics.extend(_scope_diagnostics(tree))
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


def _scope_diagnostics(tree: ast.Module) -> list[Diagnostic]:
    module_symbols, wildcard_modules = _module_symbols(tree)
    wildcard_symbols: set[str] = set()
    unknown_wildcard = False
    for module_name in wildcard_modules:
        if module_name == "manimlib":
            try:
                module = __import__(module_name)
                wildcard_symbols.update(vars(module))
            except ImportError:
                unknown_wildcard = True
        else:
            unknown_wildcard = True

    known_names = module_symbols | wildcard_symbols | set(dir(builtins))
    diagnostics: list[Diagnostic] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            diagnostics.extend(
                _check_function_scope(node, known_names, unknown_wildcard)
            )
        elif isinstance(node, ast.ClassDef):
            class_names = known_names | {node.name}
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    diagnostics.extend(
                        _check_function_scope(member, class_names, unknown_wildcard)
                    )
    return diagnostics


def _module_symbols(tree: ast.Module) -> tuple[set[str], set[str]]:
    symbols: set[str] = set()
    wildcard_modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            symbols.add(node.name)
        elif isinstance(node, ast.Import):
            symbols.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    wildcard_modules.add(node.module or "")
                else:
                    symbols.add(alias.asname or alias.name)
        else:
            symbols.update(
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
            )
    return symbols, wildcard_modules


def _check_function_scope(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    known_names: set[str],
    unknown_wildcard: bool,
) -> list[Diagnostic]:
    collector = _FunctionScopeCollector()
    for statement in node.body:
        collector.visit(statement)

    arguments = _argument_names(node.args)
    local_names = arguments | collector.stores
    diagnostics: list[Diagnostic] = []

    first_load: dict[str, ast.Name] = {}
    loaded_names: set[str] = set()
    for loaded in collector.loads:
        loaded_names.add(loaded.id)
        first_load.setdefault(loaded.id, loaded)

    for argument in sorted(arguments - {"self", "cls"}):
        if not argument.startswith("_") and argument not in loaded_names:
            diagnostics.append(
                Diagnostic(
                    "unused-parameter",
                    "warning",
                    f"参数 {argument} 未被使用",
                    node.lineno,
                    node.col_offset + 1,
                    f"删除参数 {argument}，或将其重命名为 _{argument} 表示有意保留",
                )
            )

    first_store = collector.first_store
    for name, loaded in first_load.items():
        if name in arguments:
            continue
        if name in collector.global_names:
            if name in known_names or unknown_wildcard:
                continue
        elif name in local_names:
            store_line = first_store.get(name)
            assignment_load = collector.assignment_loads.get(name)
            if (
                store_line is not None
                and (
                    loaded.lineno < store_line
                    or (
                        assignment_load is loaded
                        and store_line == loaded.lineno
                    )
                )
            ):
                diagnostics.append(
                    Diagnostic(
                        "used-before-assignment",
                        "error",
                        f"变量 {name} 在赋值前被使用",
                        loaded.lineno,
                        loaded.col_offset + 1,
                        f"在第 {loaded.lineno} 行之前为 {name} 赋值",
                    )
                )
            continue
        elif name in known_names or unknown_wildcard:
            continue

        diagnostics.append(
            Diagnostic(
                "undefined-variable",
                "error",
                f"变量 {name} 未定义",
                loaded.lineno,
                loaded.col_offset + 1,
                f"检查 {name} 是否拼写错误，或在使用前创建该变量",
            )
        )

    return diagnostics


def _argument_names(arguments: ast.arguments) -> set[str]:
    result = {
        argument.arg
        for argument in [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
    }
    if arguments.vararg is not None:
        result.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        result.add(arguments.kwarg.arg)
    return result


class _FunctionScopeCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.loads: list[ast.Name] = []
        self.stores: set[str] = set()
        self.first_store: dict[str, int] = {}
        self.global_names: set[str] = set()
        self.assignment_loads: dict[str, ast.Name] = {}

    def visit_Assign(self, node: ast.Assign) -> None:
        target_names = {
            child.id
            for target in node.targets
            for child in ast.walk(target)
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
        }
        for child in ast.walk(node.value):
            if (
                isinstance(child, ast.Name)
                and isinstance(child.ctx, ast.Load)
                and child.id in target_names
            ):
                self.assignment_loads.setdefault(child.id, child)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is not None:
            for child in ast.walk(node.value):
                if (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id == node.target.id
                ):
                    self.assignment_loads.setdefault(child.id, child)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name):
            loaded = ast.copy_location(
                ast.Name(id=node.target.id, ctx=ast.Load()),
                node.target,
            )
            self.loads.append(loaded)
            self.assignment_loads.setdefault(node.target.id, loaded)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            self.loads.append(node)
        elif isinstance(node.ctx, (ast.Store, ast.Del)):
            self.stores.add(node.id)
            self.first_store.setdefault(node.id, node.lineno)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.stores.add(name)
            self.first_store.setdefault(name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                name = alias.asname or alias.name
                self.stores.add(name)
                self.first_store.setdefault(name, node.lineno)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.stores.add(node.name)
            self.first_store.setdefault(node.name, node.lineno)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.global_names.update(node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.stores.add(node.name)
        self.first_store.setdefault(node.name, node.lineno)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.stores.add(node.name)
        self.first_store.setdefault(node.name, node.lineno)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        # Lambdas introduce a nested scope; they are checked when promoted to a
        # named helper rather than attributing their parameters to the parent.
        return
