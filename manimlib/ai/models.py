from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SUPPORTED_OBJECTS = {"circle", "square", "triangle", "text", "axes", "function_graph"}
SUPPORTED_ACTIONS = {"create", "move", "rotate", "scale", "set_color", "wait"}


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
