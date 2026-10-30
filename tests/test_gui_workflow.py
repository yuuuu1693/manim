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


if __name__ == "__main__":
    unittest.main()
