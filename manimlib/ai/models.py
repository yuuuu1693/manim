from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_OBJECTS = {
    "annulus",
    "arrow",
    "axes",
    "circle",
    "dot",
    "ellipse",
    "function_graph",
    "line",
    "rectangle",
    "square",
    "text",
    "triangle",
    "group",
    "irregular_triangle",
    "pyramid",
}
SUPPORTED_ACTIONS = {
    "create",
    "fade_in",
    "fade_out",
    "move",
    "rotate",
    "scale",
    "set_color",
    "wait",
}


@dataclass(frozen=True)
class SceneObject:
    name: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name.isidentifier():
            raise ValueError(f"Invalid object name: {self.name!r}")
        if self.type not in SUPPORTED_OBJECTS:
            raise ValueError(f"Unsupported object type: {self.type!r}")


@dataclass(frozen=True)
class ActionSpec:
    type: str
    target: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in SUPPORTED_ACTIONS:
            raise ValueError(f"Unsupported action type: {self.type!r}")
        if self.type != "wait" and not self.target:
            raise ValueError(f"Action {self.type!r} requires a target")


@dataclass(frozen=True)
class SceneSpec:
    objects: tuple[SceneObject, ...] = ()
    actions: tuple[ActionSpec, ...] = ()

    def __post_init__(self) -> None:
        names = [obj.name for obj in self.objects]
        if len(names) != len(set(names)):
            raise ValueError("Object names must be unique")
        known = set(names)
        for obj in self.objects:
            axes_name = obj.properties.get("axes")
            if axes_name is not None and axes_name not in known:
                raise ValueError(f"Unknown axes reference: {axes_name!r}")
            for key in ("inscribed_in", "centered_in", "tangent_to", "overlap_with"):
                reference = obj.properties.get(key)
                if reference is not None and reference not in known:
                    raise ValueError(f"Unknown {key} reference: {reference!r}")
            members = obj.properties.get("members")
            if members is not None:
                if not isinstance(members, (list, tuple)) or len(members) < 2:
                    raise ValueError("Group objects require at least two members")
                if any(member not in known or member == obj.name for member in members):
                    raise ValueError(f"Invalid group members: {members!r}")
        for action in self.actions:
            if action.target is not None and action.target not in known:
                raise ValueError(f"Unknown action target: {action.target!r}")

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "objects": [{"name": o.name, "type": o.type, **o.properties} for o in self.objects],
            "actions": [
                {"type": a.type, **({"target": a.target} if a.target else {}), **a.parameters}
                for a in self.actions
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SceneSpec":
        """Build and validate a scene specification from untrusted JSON data."""
        if not isinstance(data, dict):
            raise ValueError("SceneSpec 必须是 JSON 对象")
        raw_objects = data.get("objects", [])
        raw_actions = data.get("actions", [])
        if not isinstance(raw_objects, list) or not isinstance(raw_actions, list):
            raise ValueError("objects 和 actions 必须是数组")
        objects: list[SceneObject] = []
        for item in raw_objects:
            if not isinstance(item, dict):
                raise ValueError("场景对象必须是 JSON 对象")
            name = item.get("name")
            object_type = item.get("type")
            if not isinstance(name, str) or not isinstance(object_type, str):
                raise ValueError("场景对象缺少字符串 name 或 type")
            properties = {key: value for key, value in item.items() if key not in {"name", "type"}}
            objects.append(SceneObject(name, object_type, properties))
        actions: list[ActionSpec] = []
        for item in raw_actions:
            if not isinstance(item, dict):
                raise ValueError("动作必须是 JSON 对象")
            action_type = item.get("type")
            target = item.get("target")
            if not isinstance(action_type, str):
                raise ValueError("动作缺少字符串 type")
            if target is not None and not isinstance(target, str):
                raise ValueError("动作 target 必须是字符串")
            parameters = {key: value for key, value in item.items() if key not in {"type", "target"}}
            actions.append(ActionSpec(action_type, target, parameters))
        return cls(tuple(objects), tuple(actions))
