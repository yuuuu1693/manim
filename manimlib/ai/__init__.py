"""Natural-language scene generation helpers for ManimGL."""

from manimlib.ai.code_generator import generate_code
from manimlib.ai.image_parser import parse_image
from manimlib.ai.models import ActionSpec, SceneObject, SceneSpec
from manimlib.ai.prompt_parser import parse_prompt

__all__ = [
    "ActionSpec",
    "SceneObject",
    "SceneSpec",
    "generate_code",
    "parse_image",
    "parse_prompt",
]
