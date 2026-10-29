from __future__ import annotations

import re

from manimlib.ai.models import ActionSpec, SceneObject, SceneSpec


OBJECT_PATTERNS = (
    ("circle", re.compile(r"圆(?:形)?")),
    ("square", re.compile(r"正方形|方形")),
    ("triangle", re.compile(r"三角形")),
)
DIRECTIONS = {"右": "RIGHT", "左": "LEFT", "上": "UP", "下": "DOWN"}
COLORS = {
    "红": "RED",
    "蓝": "BLUE",
    "绿": "GREEN",
    "黄": "YELLOW",
    "白": "WHITE",
    "黑": "BLACK",
    "橙": "ORANGE",
    "紫": "PURPLE",
}
POSITIONS = {
    "左侧": "LEFT",
    "左边": "LEFT",
    "右侧": "RIGHT",
    "右边": "RIGHT",
    "上方": "UP",
    "上面": "UP",
    "下方": "DOWN",
    "下面": "DOWN",
    "中心": "ORIGIN",
    "中央": "ORIGIN",
}


def parse_prompt(text: str) -> SceneSpec:
    """Parse the deterministic offline subset of Chinese scene descriptions."""
    text = text.strip()
    if not text:
        raise ValueError("动画描述不能为空")

    parts = re.split(
        r"让|然后|并(?:向|往|移动|平移|旋转|放大|缩放|变色)",
        text,
        maxsplit=1,
    )
    declaration_text = parts[0]
    action_text = parts[1] if len(parts) > 1 else text
    matches: list[tuple[int, str]] = []
    for object_type, pattern in OBJECT_PATTERNS:
        matches.extend(
            (match.start(), object_type)
            for match in pattern.finditer(declaration_text)
        )
    text_matches = list(
        re.finditer(r"(?:文字|文本)[“\"]([^”\"]+)[”\"]", declaration_text)
    )
    matches.extend((match.start(), "text") for match in text_matches)
    function_match = re.search(
        r"(?:函数\s*)?y\s*=\s*([^，。,；;\n]+?)(?:的?图像|曲线|$)",
        declaration_text,
        re.IGNORECASE,
    )
    axes_match = re.search(r"坐标轴|坐标系", declaration_text)
    if axes_match or function_match:
        matches.append(((axes_match or function_match).start(), "axes"))
    if function_match:
        matches.append((function_match.start(), "function_graph"))
    matches.sort(key=lambda item: item[0])

    counters: dict[str, int] = {}
    objects: list[SceneObject] = []
    for position, object_type in matches:
        counters[object_type] = counters.get(object_type, 0) + 1
        context = declaration_text[max(0, position - 12):position]
        properties: dict[str, object] = {}
        color = _last_mapping_value(context, COLORS)
        scene_position = _last_mapping_value(context, POSITIONS)
        if color:
            properties["color"] = color
        if scene_position:
            properties["position"] = scene_position
        if object_type == "text":
            match = next(item for item in text_matches if item.start() == position)
            properties["content"] = match.group(1)
        elif object_type == "function_graph":
            properties["expression"] = _normalize_expression(function_match.group(1))
            properties["axes"] = "axes_1"
            properties.setdefault("color", "BLUE")
        objects.append(
            SceneObject(
                f"{object_type}_{counters[object_type]}",
                object_type,
                properties,
            )
        )
    if not objects:
        raise ValueError("暂未识别到支持的图形（圆形、正方形或三角形）")

    actions = [ActionSpec("create", obj.name) for obj in objects]
    target = _resolve_target(action_text, objects)
    duration = _parse_duration(action_text)
    if "移动" in text or "平移" in text:
        direction = next(
            (value for key, value in DIRECTIONS.items() if key in action_text),
            "RIGHT",
        )
        parameters: dict[str, object] = {"direction": direction}
        if duration is not None:
            parameters["duration"] = duration
        actions.append(ActionSpec("move", target, parameters))
    if "旋转" in text:
        parameters = {"duration": duration} if duration is not None else {}
        actions.append(ActionSpec("rotate", target, parameters))
    match = re.search(r"(?:放大|缩放)(?:到|为)?\s*(\d+(?:\.\d+)?)\s*倍", text)
    if match:
        parameters = {"factor": float(match.group(1))}
        if duration is not None:
            parameters["duration"] = duration
        actions.append(ActionSpec("scale", target, parameters))
    color_match = re.search(r"(?:变成|变为|改成|改为)(红|蓝|绿|黄|白|黑|橙|紫)色?", action_text)
    if color_match:
        parameters = {"color": COLORS[color_match.group(1)]}
        if duration is not None:
            parameters["duration"] = duration
        actions.append(ActionSpec("set_color", target, parameters))
    return SceneSpec(tuple(objects), tuple(actions))


def parse_text(text: str) -> dict[str, list[dict[str, object]]]:
    """Compatibility adapter for the original generator API."""
    return parse_prompt(text).to_dict()


def _last_mapping_value(text: str, mapping: dict[str, str]) -> str | None:
    matches = [
        (text.rfind(key), value)
        for key, value in mapping.items()
        if key in text
    ]
    return max(matches, default=(-1, None))[1]


def _resolve_target(text: str, objects: list[SceneObject]) -> str:
    candidates: list[tuple[int, str]] = []
    for obj in objects:
        words = {
            "circle": ("圆", "圆形"),
            "square": ("正方形", "方形"),
            "triangle": ("三角形",),
            "text": ("文字", "文本"),
            "axes": ("坐标轴", "坐标系"),
            "function_graph": ("函数", "图像", "曲线"),
        }[obj.type]
        position = max((text.rfind(word) for word in words), default=-1)
        if position >= 0:
            candidates.append((position, obj.name))
    return max(candidates, default=(-1, objects[-1].name))[1]


def _parse_duration(text: str) -> float | None:
    match = re.search(r"(?:持续|用时|用)\s*(\d+(?:\.\d+)?)\s*秒", text)
    return float(match.group(1)) if match else None


def _normalize_expression(expression: str) -> str:
    return (
        expression.strip()
        .replace("＾", "^")
        .replace("^", "**")
        .replace("×", "*")
        .replace("÷", "/")
        .replace("²", "**2")
    )
