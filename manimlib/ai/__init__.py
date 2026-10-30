"""Natural-language scene generation helpers for ManimGL."""

from manimlib.ai.code_generator import generate_code
from manimlib.ai.image_parser import parse_image
from manimlib.ai.models import ActionSpec, SceneObject, SceneSpec
from manimlib.ai.prompt_parser import parse_prompt
from manimlib.ai.provider import (
    GenerationResult,
    OpenAICompatibleProvider,
    ProviderConfig,
    ProviderError,
    generate_scene_source,
    validate_generated_source,
)

__all__ = [
    "ActionSpec",
    "SceneObject",
    "SceneSpec",
    "GenerationResult",
    "OpenAICompatibleProvider",
    "ProviderConfig",
    "ProviderError",
    "generate_code",
    "generate_scene_source",
    "parse_image",
    "parse_prompt",
    "validate_generated_source",
]
