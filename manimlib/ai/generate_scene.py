from __future__ import annotations

from pathlib import Path

from manimlib.ai.code_generator import generate_code
from manimlib.ai.prompt_parser import parse_prompt


def create_scene(prompt_text: str, output_path: str | Path) -> Path:
    """Generate a scene file at an explicit destination."""
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(generate_code(parse_prompt(prompt_text)), encoding="utf-8")
    return destination
