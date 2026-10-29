# ManimGL Animation Assistant

The optional desktop assistant adds natural-language scene generation, image
recognition, static checks, code editing, and render controls without changing
ManimGL's core rendering modules.

## Installation

From the repository root, create or activate a Python 3.10+ environment and run:

    python -m pip install -e ".[gui]"

The GUI dependency group installs PySide6 Essentials and OpenCV. FFmpeg remains
required for MP4 export.

## Start the application

    python run_gui.py

Example prompts:

    在左侧画一个红色圆形，让圆形向右移动持续2秒
    绘制函数 y=sin(x) 的图像
    创建文字“Hello Manim”，让文字变为蓝色

The application can generate and check source code, recognize basic geometric
images, open or export Python scenes, select a Scene subclass, preview the
animation, save a final PNG frame, or export an MP4 file.

## Current limitations

- Natural-language parsing is deterministic and rule-based; it is not yet
  connected to a large-language-model provider.
- Image recognition is intended for clear, non-overlapping circles, squares,
  and triangles on a light background.
- Preview is shown in ManimGL's external window rather than embedded in Qt.
- Static checks cover common unsafe and invalid patterns but are not a complete
  Python type checker.

## Tests

    python -m unittest tests.test_ai_plugins -v
