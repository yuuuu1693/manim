from __future__ import annotations

from pathlib import Path

import cv2
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PreviewWidget(QWidget):
    """Display rendered images and play rendered videos inside the Qt window."""

    IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp"}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.media_label = QLabel()
        self.media_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.media_label.setMinimumHeight(180)
        self.media_label.setStyleSheet("border: 1px solid #b8b8b8; color: #666;")

        self.play_button = QPushButton("播放")
        self.play_button.clicked.connect(self.toggle_playback)
        self.play_button.setEnabled(False)
        self.path_label = QLabel()
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        controls = QHBoxLayout()
        controls.addWidget(self.play_button)
        controls.addWidget(self.path_label, 1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.media_label, 1)
        layout.addLayout(controls)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._next_frame)
        self.capture: cv2.VideoCapture | None = None
        self.current_path: Path | None = None
        self.current_pixmap: QPixmap | None = None
        self.show_message("预览区域\n渲染最终帧或视频后将在这里显示")

    def load_media(self, path: str | Path) -> None:
        media_path = Path(path).expanduser().resolve()
        if not media_path.is_file():
            raise ValueError(f"预览文件不存在：{media_path}")
        self.stop()
        self.current_path = media_path
        self.path_label.setText(str(media_path))
        if media_path.suffix.lower() in self.IMAGE_SUFFIXES:
            pixmap = QPixmap(str(media_path))
            if pixmap.isNull():
                raise ValueError(f"无法读取预览图片：{media_path}")
            self.current_pixmap = pixmap
            self.play_button.setEnabled(False)
            self._display_pixmap(pixmap)
            return

        capture = cv2.VideoCapture(str(media_path))
        if not capture.isOpened():
            capture.release()
            raise ValueError(f"无法读取预览视频：{media_path}")
        self.capture = capture
        fps = capture.get(cv2.CAP_PROP_FPS)
        interval = round(1000 / fps) if fps and fps > 0 else 33
        self.timer.setInterval(max(1, interval))
        self.play_button.setEnabled(True)
        self.play_button.setText("暂停")
        self._next_frame()
        self.timer.start()

    def show_message(self, message: str) -> None:
        self.stop()
        self.current_path = None
        self.current_pixmap = None
        self.path_label.clear()
        self.media_label.clear()
        self.media_label.setText(message)

    def toggle_playback(self) -> None:
        if self.capture is None:
            return
        if self.timer.isActive():
            self.timer.stop()
            self.play_button.setText("播放")
        else:
            if self.capture.get(cv2.CAP_PROP_POS_FRAMES) >= self.capture.get(
                cv2.CAP_PROP_FRAME_COUNT
            ):
                self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            self.play_button.setText("暂停")
            self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        self.play_button.setEnabled(False)
        self.play_button.setText("播放")

    def _next_frame(self) -> None:
        if self.capture is None:
            return
        ok, frame = self.capture.read()
        if not ok:
            self.timer.stop()
            self.play_button.setText("重播")
            return
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        height, width, channels = rgb.shape
        image = QImage(
            rgb.data,
            width,
            height,
            channels * width,
            QImage.Format.Format_RGB888,
        ).copy()
        self.current_pixmap = QPixmap.fromImage(image)
        self._display_pixmap(self.current_pixmap)

    def _display_pixmap(self, pixmap: QPixmap) -> None:
        self.media_label.setPixmap(
            pixmap.scaled(
                self.media_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.current_pixmap is not None:
            self._display_pixmap(self.current_pixmap)

    def closeEvent(self, event) -> None:
        self.stop()
        super().closeEvent(event)
