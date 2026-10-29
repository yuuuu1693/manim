from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class PreviewWidget(QLabel):
    """Placeholder for the future embedded renderer preview."""

    def __init__(self, parent=None):
        super().__init__(
            "预览说明\n点击“运行预览”后，将打开 ManimGL 独立渲染窗口"
        )
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(180)
        self.setStyleSheet("border: 1px solid #b8b8b8; color: #666;")
