from __future__ import annotations

from pathlib import Path

from manimlib.ai.models import ActionSpec, SceneObject, SceneSpec


MANIM_COLORS = {
    "RED": (255, 0, 0),
    "GREEN": (0, 180, 0),
    "BLUE": (0, 80, 255),
    "YELLOW": (255, 220, 0),
    "ORANGE": (255, 140, 0),
    "PURPLE": (150, 70, 200),
    "BLACK": (0, 0, 0),
}


def parse_image(image_path: str | Path) -> SceneSpec:
    """Recognize simple filled or outlined geometric shapes from an image."""
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("图片识别需要安装 opencv-python") from exc

    path = Path(image_path).expanduser().resolve()
    image = cv2.imread(str(path))
    if image is None:
        raise ValueError(f"无法读取图片：{path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, binary = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    contours, _ = cv2.findContours(
        binary,
        cv2.RETR_EXTERNAL,
        cv2.CHAIN_APPROX_SIMPLE,
    )
    height, width = gray.shape
    candidates: list[tuple[int, SceneObject]] = []
    counters: dict[str, int] = {}

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < max(150, width * height * 0.001):
            continue
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.035 * perimeter, True)
        sides = len(polygon)
        object_type: str | None = None
        if sides == 3:
            object_type = "triangle"
        elif sides == 4:
            _, _, box_width, box_height = cv2.boundingRect(polygon)
            ratio = box_width / max(box_height, 1)
            if 0.78 <= ratio <= 1.22:
                object_type = "square"
        elif sides >= 7:
            circularity = 4 * 3.141592653589793 * area / max(perimeter * perimeter, 1)
            if circularity >= 0.72:
                object_type = "circle"
        if object_type is None:
            continue

        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            continue
        center_x = int(moments["m10"] / moments["m00"])
        center_y = int(moments["m01"] / moments["m00"])
        counters[object_type] = counters.get(object_type, 0) + 1
        properties = {
            "position": _position(center_x, center_y, width, height),
            "color": _contour_color(image, contour, cv2, np),
        }
        candidates.append(
            (
                center_x,
                SceneObject(
                    f"{object_type}_{counters[object_type]}",
                    object_type,
                    properties,
                ),
            )
        )

    objects = tuple(item[1] for item in sorted(candidates, key=lambda item: item[0]))
    if not objects:
        raise ValueError("图片中没有识别到圆形、正方形或三角形")
    actions = tuple(ActionSpec("create", obj.name) for obj in objects)
    return SceneSpec(objects, actions)


def _position(x: int, y: int, width: int, height: int) -> str:
    horizontal = (x - width / 2) / max(width / 2, 1)
    vertical = (height / 2 - y) / max(height / 2, 1)
    if abs(horizontal) < 0.2 and abs(vertical) < 0.2:
        return "ORIGIN"
    if abs(horizontal) >= abs(vertical):
        return "RIGHT" if horizontal > 0 else "LEFT"
    return "UP" if vertical > 0 else "DOWN"


def _contour_color(image, contour, cv2, np) -> str:
    mask = np.zeros(image.shape[:2], dtype=np.uint8)
    cv2.drawContours(mask, [contour], -1, 255, thickness=-1)
    blue, green, red, _ = cv2.mean(image, mask=mask)
    rgb = (red, green, blue)
    return min(
        MANIM_COLORS,
        key=lambda name: sum(
            (rgb[index] - MANIM_COLORS[name][index]) ** 2
            for index in range(3)
        ),
    )
