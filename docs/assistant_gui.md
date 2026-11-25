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

Alternatively, click **AI 配置** in the application. The API address, model,
and timeout are saved for later launches. The API key uses a masked field and
is kept in memory only for the current launch; it is never written to QSettings.

Use **本地规则** to force deterministic offline generation or **大模型** to
require the configured provider. Provider output is accepted only after syntax,
Scene, static-error, import, and dangerous-call validation. In automatic mode,
invalid model code is returned to the provider once with the validation error for
automatic repair. If the repair still fails, automatic mode falls back to local
rules and shows the reason in the log.

## Start the application

    python run_gui.py

Example prompts:

    在左侧画一个红色圆形，让圆形向右移动持续2秒
    绘制函数 y=sin(x) 的图像
    创建文字“Hello Manim”，让文字变为蓝色
    创建一个蓝色圆点，让圆点向右上移动2个单位持续3秒然后淡出

Offline templates support circles, squares, triangles, rectangles, ellipses,
dots, lines, arrows, annuli, text, axes, and function graphs. Supported actions include
creation, fade-in/out, movement in eight directions, rotation, scaling, color
changes, and timed waits.

Deterministic composition rules also support a square inscribed in a circle,
percentage-based overlap, automatic tangency, centering a shape inside an
annulus, and grouping multiple shapes so that movement and scaling apply to the
whole composition.

Example composition prompts:

    创建一个圆和一个正方形，让正方形内接圆
    创建一个圆和一个正方形，让两个图形按50%重叠
    创建一个圆和一个正方形，让两个图形相切
    创建一个圆环和一个正方形，让它们自动居中组合
    创建一个圆和一个正方形，将两个图形作为一个整体向右移动2个单位并缩放2倍

The application can generate and check source code, recognize basic geometric
images, open or export Python scenes, select a Scene subclass, preview the
animation, save a final PNG frame, or export an MP4 file. Saved PNG frames and
MP4 videos are loaded into the embedded preview panel; videos include
play/pause/replay controls.

Static checks report syntax errors, unsafe dynamic execution and indirect access
to dangerous Python built-ins, invalid animation
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
