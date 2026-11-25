from __future__ import annotations

import ast
import json
import re

from manimlib.ai.models import SceneObject


OBJECT_CONSTRUCTORS = {
    "annulus": "Annulus(inner_radius=0.8, outer_radius=1.5)",
    "arrow": "Arrow(LEFT, RIGHT)",
    "circle": "Circle()",
    "dot": "Dot()",
    "ellipse": "Ellipse(width=3, height=2)",
    "line": "Line(LEFT, RIGHT)",
    "rectangle": "Rectangle(width=3, height=2)",
    "square": "Square()",
    "triangle": "Triangle()",
}
ALLOWED_DIRECTIONS = {"RIGHT", "LEFT", "UP", "DOWN", "UR", "UL", "DR", "DL"}


def render_object(obj: SceneObject) -> str:
    if obj.type == "group":
        members = obj.properties.get("members")
        if not isinstance(members, (list, tuple)):
            raise ValueError("Group objects require members")
        constructor = f"VGroup({', '.join(_identifier(item, 'member') for item in members)})"
    elif obj.type == "axes":
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
    elif obj.type == "irregular_triangle":
        constructor = _irregular_triangle_constructor(obj)
    elif obj.type == "pyramid":
        constructor = _pyramid_constructor(obj)
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


def render_layout(obj: SceneObject) -> list[str]:
    """Render layout statements that require already-created peer objects."""
    lines: list[str] = []
    if reference := obj.properties.get("inscribed_in"):
        target = _identifier(reference, "inscribed_in")
        if obj.type == "square":
            lines.append(
                f"        {obj.name}.set_width({target}.get_width() / np.sqrt(2)).move_to({target})"
            )
        else:
            lines.append(f"        {obj.name}.move_to({target})")
    if reference := obj.properties.get("centered_in"):
        target = _identifier(reference, "centered_in")
        lines.append(f"        {obj.name}.move_to({target})")
    if reference := obj.properties.get("tangent_to"):
        target = _identifier(reference, "tangent_to")
        lines.append(f"        {obj.name}.next_to({target}, RIGHT, buff=0)")
    if reference := obj.properties.get("overlap_with"):
        target = _identifier(reference, "overlap_with")
        ratio = float(obj.properties.get("overlap_ratio", 0.5))
        if not 0 < ratio < 1:
            raise ValueError("overlap_ratio must be between 0 and 1")
        lines.append(
            f"        {obj.name}.next_to({target}, RIGHT, "
            f"buff=-min({target}.get_width(), {obj.name}.get_width()) * {ratio:g})"
        )
    return lines


def render_action(action_type: str, target: str | None, parameters: dict[str, object]) -> str:
    if action_type == "wait":
        duration = _positive_number(parameters.get("duration", 1), "duration")
        return f"        self.wait({duration:g})"
    if target is None:
        raise ValueError(f"Action {action_type!r} requires a target")
    if action_type == "create":
        return _play(f"ShowCreation({target})", parameters)
    if action_type == "fade_in":
        return _play(f"FadeIn({target})", parameters)
    if action_type == "fade_out":
        return _play(f"FadeOut({target})", parameters)
    if action_type == "move":
        direction = str(parameters.get("direction", "RIGHT"))
        if direction not in ALLOWED_DIRECTIONS:
            raise ValueError(f"Unsupported direction: {direction!r}")
        distance = _positive_number(parameters.get("distance", 1), "distance")
        vector = direction if distance == 1 else f"{direction} * {distance:g}"
        return _play(f"{target}.animate.shift({vector})", parameters)
    if action_type == "rotate":
        axis = parameters.get("axis")
        suffix = "" if axis is None else f", axis={_constant(axis, 'axis')}"
        return _play(f"Rotate({target}{suffix})", parameters)
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


def _irregular_triangle_constructor(obj: SceneObject) -> str:
    sides = obj.properties.get("side_lengths")
    if sides is None:
        points = ((-1.8, -1.0, 0.0), (1.6, -0.7, 0.0), (0.4, 1.5, 0.0))
    else:
        if not isinstance(sides, (list, tuple)) or len(sides) != 3:
            raise ValueError("side_lengths must contain three numbers")
        a, b, c = (float(value) for value in sides)
        if min(a, b, c) <= 0 or max(a, b, c) * 2 >= a + b + c:
            raise ValueError("Invalid triangle side lengths")
        x = (b * b + c * c - a * a) / (2 * c)
        y = (b * b - x * x) ** 0.5
        raw = ((0.0, 0.0, 0.0), (c, 0.0, 0.0), (x, y, 0.0))
        center_x = sum(point[0] for point in raw) / 3
        center_y = sum(point[1] for point in raw) / 3
        scale = 3.5 / max(a, b, c)
        points = tuple(
            ((px - center_x) * scale, (py - center_y) * scale, pz)
            for px, py, pz in raw
        )
    rendered = ", ".join(
        f"np.array([{x:g}, {y:g}, {z:g}])" for x, y, z in points
    )
    return f"Polygon({rendered})"


def _pyramid_constructor(obj: SceneObject) -> str:
    sides = int(obj.properties.get("base_sides", 4))
    apex = "np.array([0, 0, 1.6])"
    if sides == 3:
        base = (
            "np.array([-1.4, -0.8, -1])",
            "np.array([1.4, -0.8, -1])",
            "np.array([0, 1.4, -1])",
        )
    elif sides == 4:
        base = (
            "np.array([-1, -1, -1])",
            "np.array([1, -1, -1])",
            "np.array([1, 1, -1])",
            "np.array([-1, 1, -1])",
        )
    else:
        raise ValueError("Pyramid base_sides must be 3 or 4")
    faces = [f"Polygon({', '.join(base)})"]
    for index, point in enumerate(base):
        following = base[(index + 1) % len(base)]
        faces.append(f"Polygon({point}, {following}, {apex})")
    return f"VGroup3D({', '.join(faces)})"
