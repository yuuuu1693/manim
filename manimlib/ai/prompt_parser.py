from __future__ import annotations

import re

from manimlib.ai.models import ActionSpec, SceneObject, SceneSpec


OBJECT_PATTERNS = (
    ("annulus", re.compile(r"圆环|环形")),
    ("ellipse", re.compile(r"椭圆(?:形)?")),
    ("circle", re.compile(r"(?<!椭)圆(?!点|环)(?:形)?")),
    ("rectangle", re.compile(r"长方形|矩形")),
    ("square", re.compile(r"正方形|(?<!长)方形")),
    ("triangle", re.compile(r"三角形")),
    ("arrow", re.compile(r"箭头")),
    ("line", re.compile(r"直线|线段")),
    ("dot", re.compile(r"圆点|点")),
)
DIRECTIONS = (
    ("右上", "UR"),
    ("左上", "UL"),
    ("右下", "DR"),
    ("左下", "DL"),
    ("右", "RIGHT"),
    ("左", "LEFT"),
    ("上", "UP"),
    ("下", "DOWN"),
)
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
    "右上角": "UR",
    "左上角": "UL",
    "右下角": "DR",
    "左下角": "DL",
}


def parse_prompt(text: str) -> SceneSpec:
    """Parse the deterministic offline subset of Chinese scene descriptions."""
    text = text.strip()
    if not text:
        raise ValueError("动画描述不能为空")

    parts = re.split(
        r"让|然后|并(?:向|往|移动|平移|旋转|放大|缩放|变色|淡入|淡出)",
        text,
        maxsplit=1,
    )
    declaration_text = parts[0] or text
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
        raise ValueError(
            "暂未识别到支持的图形（点、线、箭头、圆形、方形、三角形或椭圆）"
        )

    objects = _apply_geometric_relationships(text, objects)
    group_target = None
    if len(objects) >= 2 and re.search(
        r"(?:作为|组成|视为)?(?:一个)?整体|组合后|组合起来|居中组合",
        text,
    ):
        members = tuple(obj.name for obj in objects if obj.type not in {"axes", "group"})
        if len(members) >= 2:
            group_target = "group_1"
            objects.append(SceneObject(group_target, "group", {"members": members}))

    initial_action = "fade_in" if re.search(r"淡入|渐显", text) else "create"
    actions = [
        ActionSpec(initial_action, obj.name)
        for obj in objects
        if obj.type != "group"
    ]
    target = group_target or _resolve_target(action_text, objects)
    duration = _parse_duration(action_text)
    if "移动" in text or "平移" in text:
        direction = _parse_movement_direction(text)
        parameters: dict[str, object] = {"direction": direction}
        distance_match = re.search(
            r"(?:移动|平移)\s*(\d+(?:\.\d+)?)\s*(?:个)?单位",
            text,
        )
        if distance_match:
            parameters["distance"] = float(distance_match.group(1))
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
    if re.search(r"淡出|消失", action_text):
        parameters = {"duration": duration} if duration is not None else {}
        actions.append(ActionSpec("fade_out", target, parameters))
    wait_match = re.search(r"(?:等待|停留)\s*(\d+(?:\.\d+)?)\s*秒", text)
    if wait_match:
        actions.append(
            ActionSpec("wait", parameters={"duration": float(wait_match.group(1))})
        )
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
            "annulus": ("圆环", "环形"),
            "square": ("正方形", "方形"),
            "triangle": ("三角形",),
            "rectangle": ("长方形", "矩形"),
            "ellipse": ("椭圆", "椭圆形"),
            "dot": ("圆点", "点"),
            "line": ("直线", "线段"),
            "arrow": ("箭头",),
            "text": ("文字", "文本"),
            "axes": ("坐标轴", "坐标系"),
            "function_graph": ("函数", "图像", "曲线"),
            "group": ("整体", "组合"),
        }[obj.type]
        position = max((text.rfind(word) for word in words), default=-1)
        if position >= 0:
            candidates.append((position, obj.name))
    return max(candidates, default=(-1, objects[-1].name))[1]


def _apply_geometric_relationships(
    text: str,
    objects: list[SceneObject],
) -> list[SceneObject]:
    """Attach deterministic layout relationships to recognized objects."""
    updated = list(objects)

    def first(kind: str) -> SceneObject | None:
        return next((obj for obj in updated if obj.type == kind), None)

    def replace_properties(name: str, **properties: object) -> None:
        for index, obj in enumerate(updated):
            if obj.name == name:
                updated[index] = SceneObject(
                    obj.name,
                    obj.type,
                    {**obj.properties, **properties},
                )
                return

    circle = first("circle")
    square = first("square")
    if circle and square and re.search(r"正方形(?:严格)?内接(?:于)?(?:一个)?圆", text):
        replace_properties(square.name, inscribed_in=circle.name)

    visible = [obj for obj in updated if obj.type not in {"axes", "group"}]
    overlap = re.search(
        r"(?:按|以)?\s*(\d+(?:\.\d+)?)\s*%\s*(?:的比例)?重叠|"
        r"重叠\s*(\d+(?:\.\d+)?)\s*%",
        text,
    )
    if len(visible) >= 2 and overlap:
        ratio = float(overlap.group(1) or overlap.group(2)) / 100
        if not 0 < ratio < 1:
            raise ValueError("图形重叠比例必须大于0%且小于100%")
        replace_properties(
            visible[1].name,
            overlap_with=visible[0].name,
            overlap_ratio=ratio,
        )
    elif len(visible) >= 2 and "相切" in text:
        replace_properties(visible[1].name, tangent_to=visible[0].name)

    annulus = first("annulus")
    if annulus and re.search(r"(?:圆环.*(?:中心|中央|居中|组合)|(?:中心|中央|居中).*圆环)", text):
        inner = next((obj for obj in visible if obj.name != annulus.name), None)
        if inner:
            replace_properties(inner.name, centered_in=annulus.name)
    return updated


def _parse_duration(text: str) -> float | None:
    match = re.search(r"(?:持续|用时|用)\s*(\d+(?:\.\d+)?)\s*秒", text)
    return float(match.group(1)) if match else None


def _parse_movement_direction(text: str) -> str:
    words = "右上|左上|右下|左下|右|左|上|下"
    match = re.search(
        rf"(?:向|往)\s*({words})\s*(?:移动|平移)|(?:移动|平移)\s*(?:向|往)?\s*({words})",
        text,
    )
    if match:
        word = match.group(1) or match.group(2)
        return dict(DIRECTIONS)[word]
    return "RIGHT"


def _normalize_expression(expression: str) -> str:
    return (
        expression.strip()
        .replace("＾", "^")
        .replace("^", "**")
        .replace("×", "*")
        .replace("÷", "/")
        .replace("²", "**2")
    )
