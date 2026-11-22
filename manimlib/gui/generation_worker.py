from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import QThread, Signal

from manimlib.ai import ProviderError, generate_scene_source


class GenerationWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        prompt: str,
        mode: str,
        environ: Mapping[str, str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.prompt = prompt
        self.mode = mode
        self.environ = dict(environ) if environ is not None else None

    def run(self) -> None:
        try:
            result = generate_scene_source(
                self.prompt,
                mode=self.mode,
                environ=self.environ,
            )
        except (ProviderError, ValueError) as exc:
            self.failed.emit(str(exc))
            return
        except Exception:
            self.failed.emit("生成过程发生未预期错误，请查看配置后重试")
            return
        self.succeeded.emit(result)
