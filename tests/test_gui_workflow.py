import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    from manimlib.gui.main_window import MainWindow
except ImportError:
    QSettings = None


@unittest.skipIf(QSettings is None, "PySide6 is not installed")
class GUIWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_safe_repair_updates_editor_and_supports_undo(self):
        source = """from manimlib import *

class DemoScene(Scene):
    def construct(self):
        circle = Circle()
        self.add(circel)
"""
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                str(Path(directory, "settings.ini")),
                QSettings.Format.IniFormat,
            )
            window = MainWindow(settings=settings)
            window.source_edit.setPlainText(source)
            window.repair_source()
            self.assertIn("self.add(circle)", window.source_edit.toPlainText())
            window.source_edit.undo()
            self.assertEqual(window.source_edit.toPlainText(), source)
            window.source_edit.document().setModified(False)
            window.close()

    def test_local_generation_runs_in_background_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(
                str(Path(directory, "settings.ini")),
                QSettings.Format.IniFormat,
            )
            window = MainWindow(settings=settings)
            window.generation_mode_combo.setCurrentText("本地规则")
            window.prompt_edit.setPlainText("画一个红色圆形")
            window.generate_source()
            worker = window.generation_worker
            self.assertIsNotNone(worker)
            self.assertTrue(worker.wait(5000))
            self.app.processEvents()
            self.assertIn("Circle().set_color(RED)", window.source_edit.toPlainText())
            self.assertTrue(window.generate_button.isEnabled())
            window.source_edit.document().setModified(False)
            window.close()

    def test_preview_widget_loads_rendered_image(self):
        from PySide6.QtGui import QColor, QImage
        from manimlib.gui.preview_widget import PreviewWidget

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "frame.png")
            image = QImage(80, 60, QImage.Format.Format_RGB32)
            image.fill(QColor("red"))
            self.assertTrue(image.save(str(path)))
            widget = PreviewWidget()
            widget.resize(320, 240)
            widget.load_media(path)
            self.assertEqual(widget.current_path, path.resolve())
            self.assertIsNotNone(widget.current_pixmap)
            self.assertFalse(widget.play_button.isEnabled())
            widget.close()

    def test_preview_widget_plays_video_frames(self):
        import cv2
        import numpy as np
        from manimlib.gui.preview_widget import PreviewWidget

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "preview.avi")
            writer = cv2.VideoWriter(
                str(path),
                cv2.VideoWriter_fourcc(*"MJPG"),
                10,
                (64, 48),
            )
            if not writer.isOpened():
                self.skipTest("OpenCV video writer is unavailable")
            for value in (40, 120, 220):
                writer.write(np.full((48, 64, 3), value, dtype=np.uint8))
            writer.release()

            widget = PreviewWidget()
            widget.resize(320, 240)
            widget.load_media(path)
            self.assertTrue(widget.play_button.isEnabled())
            self.assertTrue(widget.timer.isActive())
            self.assertIsNotNone(widget.current_pixmap)
            widget.toggle_playback()
            self.assertFalse(widget.timer.isActive())
            widget.close()


if __name__ == "__main__":
    unittest.main()
