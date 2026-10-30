from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RenderRequest:
    script: Path
    scene: str
    python: Path = field(default_factory=lambda: Path(sys.executable))
    extra_args: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        script = Path(self.script).expanduser().resolve()
        python = Path(self.python).expanduser().resolve()
        object.__setattr__(self, "script", script)
        object.__setattr__(self, "python", python)
        if not script.is_file():
            raise ValueError(f"场景文件不存在：{script}")
        if not python.is_file():
            raise ValueError(f"Python 解释器不存在：{python}")
        if not self.scene.isidentifier():
            raise ValueError(f"场景类名称无效：{self.scene!r}")

    def command(self) -> list[str]:
        return [
            str(self.python),
            "-m",
            "manimlib",
            str(self.script),
            self.scene,
            *self.extra_args,
        ]


class RenderController:
    """Small process boundary that can be used without importing PySide6."""

    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None

    def start(self, request: RenderRequest) -> subprocess.Popen[str]:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError("已有渲染任务正在运行")
        env = os.environ.copy()
        project_root = _find_project_root(request.script.parent)
        if project_root is not None:
            existing = env.get("PYTHONPATH")
            env["PYTHONPATH"] = str(project_root) + (
                os.pathsep + existing if existing else ""
            )
        self.process = subprocess.Popen(
            request.command(),
            cwd=project_root or request.script.parent,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return self.process

    def stop(self) -> bool:
        if self.process is None or self.process.poll() is not None:
            return False
        self.process.terminate()
        return True


def _find_project_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / "manimlib").is_dir():
            return candidate
    return None


QUALITY_FLAGS = {
    "低清 480p": "-l",
    "中清 720p": "-m",
    "高清 1080p": "--hd",
}


def build_render_args(mode: str, quality: str) -> list[str]:
    """Translate user-facing render settings into ManimGL CLI arguments."""
    if mode == "实时预览":
        return []
    try:
        quality_flag = QUALITY_FLAGS[quality]
    except KeyError as exc:
        raise ValueError(f"未知渲染质量：{quality}") from exc
    if mode == "保存最终帧":
        return ["-s", "-w", quality_flag]
    if mode == "导出视频":
        return ["-w", quality_flag]
    raise ValueError(f"未知渲染模式：{mode}")


def get_preview_output_path(
    project_root: str | Path,
    file_name: str,
    mode: str,
) -> Path | None:
    """Return the deterministic output path used by GUI renders."""
    if not file_name or Path(file_name).name != file_name:
        raise ValueError("预览输出名称无效")
    if mode == "实时预览":
        return None
    suffixes = {"保存最终帧": ".png", "导出视频": ".mp4"}
    try:
        suffix = suffixes[mode]
    except KeyError as exc:
        raise ValueError(f"未知渲染模式：{mode}") from exc
    return Path(project_root).resolve() / "videos" / f"{file_name}{suffix}"
