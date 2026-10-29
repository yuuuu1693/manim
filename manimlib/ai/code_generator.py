from __future__ import annotations

import ast

from manimlib.ai.models import ActionSpec, SceneObject, SceneSpec
from manimlib.ai.template_manager import render_action, render_object


def generate_code(spec: SceneSpec | dict[str, object], class_name: str = "GeneratedScene") -> str:
    """Generate deterministic ManimGL source from a validated scene spec."""
    if isinstance(spec, dict):
        spec = _scene_from_legacy_dict(spec)
    if not class_name.isidentifier():
        raise ValueError(f"Invalid class name: {class_name!r}")

    lines = [
        "from manimlib import *",
        "import numpy as np",
        "",
        "",
        f"class {class_name}(Scene):",
        "    def construct(self):",
    ]
    lines.extend(render_object(obj) for obj in spec.objects)
    if spec.objects and spec.actions:
        lines.append("")
    lines.extend(render_action(a.type, a.target, a.parameters) for a in spec.actions)
    if not spec.actions or spec.actions[-1].type != "wait":
        lines.append("        self.wait(1)")
    lines.append("")
    source = "\n".join(lines)
    ast.parse(source)
    return source


def _scene_from_legacy_dict(data: dict[str, object]) -> SceneSpec:
    raw_objects, raw_actions = data.get("objects", []), data.get("actions", [])
    if not isinstance(raw_objects, list) or not isinstance(raw_actions, list):
        raise ValueError("Scene data must contain object and action lists")

    counters: dict[str, int] = {}
    objects: list[SceneObject] = []
    for item in raw_objects:
        if not isinstance(item, dict):
            raise ValueError("Each object must be a mapping")
        kind = str(item.get("type", ""))
        counters[kind] = counters.get(kind, 0) + 1
        name = str(item.get("name") or f"{kind}_{counters[kind]}")
        properties = {key: value for key, value in item.items() if key not in {"name", "type"}}
        objects.append(SceneObject(name, kind, properties))

    default_target = objects[-1].name if objects else None
    actions: list[ActionSpec] = []
    for item in raw_actions:
        if not isinstance(item, dict):
            raise ValueError("Each action must be a mapping")
        kind = str(item.get("type", ""))
        target = item.get("target", default_target)
        parameters = {key: value for key, value in item.items() if key not in {"type", "target"}}
        actions.append(ActionSpec(kind, str(target) if target else None, parameters))
    return SceneSpec(tuple(objects), tuple(actions))
