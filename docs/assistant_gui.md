# ManimGL Animation Assistant

The optional desktop assistant adds natural-language scene generation, image
recognition, static checks, code editing, and render controls without changing
ManimGL's core rendering modules.

## Installation

From the repository root, create or activate a Python 3.10+ environment and run:

    python -m pip install -e ".[gui]"

The GUI dependency group installs PySide6 Essentials and OpenCV. FFmpeg remains
required for MP4 export.

## Optional model provider

The default **自动生成** mode remains fully offline when no provider is configured.
To enable any OpenAI-compatible chat-completions endpoint, set environment
variables before launching the GUI (never commit API keys to the repository):

    $env:MANIM_AI_API_KEY="your-api-key"
    $env:MANIM_AI_MODEL="your-model-name"
    $env:MANIM_AI_BASE_URL="https://provider.example/v1"
    $env:MANIM_AI_TIMEOUT="20"

Use **本地规则** to force deterministic offline generation or **大模型** to
require the configured provider. Provider output is accepted only after syntax,
Scene, static-error, import, and dangerous-call validation. In automatic mode,
provider errors fall back to local rules and are shown in the log.

## Start the application

    python run_gui.py

Example prompts:

    在左侧画一个红色圆形，让圆形向右移动持续2秒
    绘制函数 y=sin(x) 的图像
    创建文字“Hello Manim”，让文字变为蓝色

The application can generate and check source code, recognize basic geometric
images, open or export Python scenes, select a Scene subclass, preview the
animation, save a final PNG frame, or export an MP4 file. Saved PNG frames and
MP4 videos are loaded into the embedded preview panel; videos include
play/pause/replay controls.

Static checks report syntax errors, unsafe dynamic execution, invalid animation
calls, undefined variables, variables used before assignment, and unused
parameters. Each diagnostic includes a repair suggestion in the GUI log.
The **安全修复** action can correct a unique, high-confidence local-variable typo
and replace an empty `self.play()` with `pass`; all edits remain undoable with
Ctrl+Z. Ambiguous or semantic changes are deliberately left for manual review.

## Current limitations

- Offline generation supports a deterministic subset; broader requests require
  a separately configured OpenAI-compatible provider.
- Image recognition is intended for clear, non-overlapping circles, squares,
  and triangles on a light background.
- Interactive real-time preview uses ManimGL's external GPU window; rendered
  PNG and MP4 results are displayed inside Qt.
- Static checks cover common unsafe and invalid patterns but are not a complete
  Python type checker.

## Tests

    python -m unittest discover -s tests -p "test_*.py" -v
