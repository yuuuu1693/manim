from __future__ import annotations

from pathlib import Path

from manimlib.ai.provider import generate_scene_source


def create_scene(
    prompt_text: str,
    output_path: str | Path,
    mode: str = "auto",
) -> Path:
    """Generate a scene file at an explicit destination."""
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = generate_scene_source(prompt_text, mode=mode)
    destination.write_text(result.source, encoding="utf-8")
    return destination
