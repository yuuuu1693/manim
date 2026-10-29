from __future__ import annotations

import ast
import json
import re

from manimlib.ai.models import SceneObject


OBJECT_CONSTRUCTORS = {"circle": "Circle()", "square": "Square()", "triangle": "Triangle()"}
ALLOWED_DIRECTIONS = {"RIGHT", "LEFT", "UP", "DOWN"}


def render_object(obj: SceneObject) -> str:
    if obj.type == "axes":
        constructor = "Axes(x_range=(-5, 5, 1), y_range=(-3, 3, 1))"
    elif obj.type == "function_graph":
        axes = _identifier(obj.properties.get("axes"), "axes")
        expression = _safe_expression(obj.properties.get("expression"))
        constructor = f"{axes}.get_graph(lambda x: {expression}, x_range=(-5, 5))"
    elif obj.type == "text":
        content = obj.properties.get("content")
        if not isinstance(content, str) or not content:
            raise ValueError("Text objects require non-empty content")
        constructor = f"Text({json.dumps(content, ensure_ascii=False)})"
    else:
        try:
            constructor = OBJECT_CONSTRUCTORS[obj.type]
        except KeyError as exc:
            raise ValueError(f"No template for object type: {obj.type!r}") from exc

    expression = constructor
    color = obj.properties.get("color")
    if color is not None:
        expression += f".set_color({_constant(color, 'color')})"
    position = obj.properties.get("position")
    if position is not None:
        expression += f".move_to({_constant(position, 'position')})"
    return f"        {obj.name} = {expression}"


def render_action(action_type: str, target: str | None, parameters: dict[str, object]) -> str:
    if action_type == "wait":
        duration = _positive_number(parameters.get("duration", 1), "duration")
        return f"        self.wait({duration:g})"
    if target is None:
        raise ValueError(f"Action {action_type!r} requires a target")
    if action_type == "create":
        return _play(f"ShowCreation({target})", parameters)
    if action_type == "move":
        direction = str(parameters.get("direction", "RIGHT"))
        if direction not in ALLOWED_DIRECTIONS:
            raise ValueError(f"Unsupported direction: {direction!r}")
        return _play(f"{target}.animate.shift({direction})", parameters)
    if action_type == "rotate":
        return _play(f"Rotate({target})", parameters)
    if action_type == "scale":
        factor = _positive_number(parameters.get("factor", 1), "factor")
        return _play(f"{target}.animate.scale({factor:g})", parameters)
    if action_type == "set_color":
        color = _constant(parameters.get("color", "WHITE"), "color")
        return _play(f"{target}.animate.set_color({color})", parameters)
    raise ValueError(f"No template for action type: {action_type!r}")


def _positive_number(value: object, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc
    if number <= 0:
        raise ValueError(f"{field_name} must be positive")
    return number


def _play(expression: str, parameters: dict[str, object]) -> str:
    duration = parameters.get("duration")
    if duration is None:
        return f"        self.play({expression})"
    return f"        self.play({expression}, run_time={_positive_number(duration, 'duration'):g})"


def _constant(value: object, field_name: str) -> str:
    constant = str(value)
    if not constant.isidentifier() or constant.upper() != constant:
        raise ValueError(f"Unsafe {field_name} constant: {constant!r}")
    return constant


def _identifier(value: object, field_name: str) -> str:
    identifier = str(value)
    if not identifier.isidentifier():
        raise ValueError(f"Unsafe {field_name} identifier: {identifier!r}")
    return identifier


def _safe_expression(value: object) -> str:
    expression = str(value).strip()
    if not expression:
        raise ValueError("Function graph requires an expression")
    expression = re.sub(
        r"\b(sin|cos|tan|exp|log|sqrt)\b",
        r"np.\1",
        expression,
    )
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid function expression: {value!r}") from exc
    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Call,
        ast.Name,
        ast.Load,
        ast.Attribute,
        ast.Constant,
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.Pow,
        ast.Mod,
        ast.USub,
        ast.UAdd,
    )
    for node in ast.walk(tree):
        if not isinstance(node, allowed_nodes):
            raise ValueError(f"Unsupported function expression element: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in {"x", "np"}:
            raise ValueError(f"Unsupported name in function expression: {node.id!r}")
        if isinstance(node, ast.Attribute):
            if not isinstance(node.value, ast.Name) or node.value.id != "np":
                raise ValueError("Only approved numpy functions are allowed")
            if node.attr not in {"sin", "cos", "tan", "exp", "log", "sqrt"}:
                raise ValueError(f"Unsupported function: {node.attr!r}")
    return expression
