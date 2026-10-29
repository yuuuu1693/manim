from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit


class LogPanel(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("生成、检查和渲染日志将在这里显示")

    def write(self, message: str) -> None:
        self.appendPlainText(message.rstrip())
