from __future__ import annotations

import sys
import json
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from manimlib.ai import generate_code, parse_image, parse_prompt
from manimlib.code_checker import check_code, detect_scene_names
from manimlib.gui.log_panel import LogPanel
from manimlib.gui.preview_widget import PreviewWidget
from manimlib.gui.render_controller import build_render_args
from manimlib.gui.syntax_highlighter import PythonHighlighter


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ManimGL 动画助手")
        self.resize(1100, 760)
        self.project_root = Path(__file__).resolve().parents[2]
        self.generated_file = self.project_root / "generated" / "gui_generated_scene.py"
        self.render_process = QProcess(self)
        self.render_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self.render_process.readyReadStandardOutput.connect(self._read_render_output)
        self.render_process.started.connect(self._render_started)
        self.render_process.finished.connect(self._render_finished)
        self.render_process.errorOccurred.connect(self._render_error)
        self.settings = QSettings("ManimGLAssistant", "DesktopGUI")
        self.history: list[str] = []
        self._build_ui()
        self._restore_settings()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)

        layout.addWidget(QLabel("动画需求"))
        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "例如：在左侧画一个红色圆形，让圆形向右移动持续2秒"
        )
        self.prompt_edit.setMaximumHeight(100)
        layout.addWidget(self.prompt_edit)

        buttons = QHBoxLayout()
        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(220)
        self.history_combo.setPlaceholderText("最近生成记录")
        self.history_combo.textActivated.connect(self.prompt_edit.setPlainText)
        buttons.addWidget(self.history_combo)
        generate_button = QPushButton("生成代码")
        generate_button.clicked.connect(self.generate_source)
        image_button = QPushButton("识别图片")
        image_button.clicked.connect(self.generate_from_image)
        check_button = QPushButton("检查代码")
        check_button.clicked.connect(self.check_source)
        open_button = QPushButton("打开代码")
        open_button.clicked.connect(self.open_source)
        export_button = QPushButton("导出源码")
        export_button.clicked.connect(self.export_source)
        self.render_button = QPushButton("运行预览")
        self.render_button.clicked.connect(self.render_scene)
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.stop_render)
        self.stop_button.setEnabled(False)
        buttons.addWidget(generate_button)
        buttons.addWidget(image_button)
        buttons.addWidget(check_button)
        buttons.addWidget(open_button)
        buttons.addWidget(export_button)
        buttons.addWidget(self.render_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        render_options = QHBoxLayout()
        render_options.addWidget(QLabel("场景"))
        self.scene_combo = QComboBox()
        self.scene_combo.setMinimumWidth(150)
        render_options.addWidget(self.scene_combo)
        render_options.addWidget(QLabel("模式"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["实时预览", "保存最终帧", "导出视频"])
        render_options.addWidget(self.mode_combo)
        render_options.addWidget(QLabel("质量"))
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["低清 480p", "中清 720p", "高清 1080p"])
        render_options.addWidget(self.quality_combo)
        output_button = QPushButton("打开输出目录")
        output_button.clicked.connect(self.open_output_directory)
        render_options.addWidget(output_button)
        render_options.addStretch()
        layout.addLayout(render_options)

        splitter = QSplitter()
        self.source_edit = QPlainTextEdit()
        self.source_edit.setPlaceholderText("生成的 ManimGL 场景代码")
        self.highlighter = PythonHighlighter(self.source_edit.document())
        self.source_edit.document().modificationChanged.connect(self._update_title)
        splitter.addWidget(self.source_edit)
        splitter.addWidget(PreviewWidget())
        splitter.setSizes([700, 400])
        layout.addWidget(splitter, 1)

        self.log_panel = LogPanel()
        self.log_panel.setMaximumHeight(150)
        layout.addWidget(self.log_panel)
        self.setCentralWidget(root)

    def generate_source(self) -> None:
        try:
            spec = parse_prompt(self.prompt_edit.toPlainText())
            source = generate_code(spec)
        except ValueError as exc:
            QMessageBox.warning(self, "生成失败", str(exc))
            self.log_panel.write(f"生成失败：{exc}")
            return
        self.source_edit.setPlainText(source)
        self.source_edit.document().setModified(True)
        self._record_prompt(self.prompt_edit.toPlainText())
        self.log_panel.write("代码生成完成")
        self.check_source()

    def generate_from_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择几何图片",
            str(self.project_root),
            "图片文件 (*.png *.jpg *.jpeg *.bmp);;所有文件 (*)",
        )
        if not path:
            return
        try:
            source = generate_code(parse_image(path))
        except (ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "图片识别失败", str(exc))
            self.log_panel.write(f"图片识别失败：{exc}")
            return
        self.source_edit.setPlainText(source)
        self.source_edit.document().setModified(True)
        self.log_panel.write(f"图片识别完成：{path}")
        self.check_source()

    def open_source(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "打开 ManimGL 场景",
            str(self.project_root),
            "Python 文件 (*.py);;所有文件 (*)",
        )
        if not path:
            return
        try:
            source = Path(path).read_text(encoding="utf-8-sig")
        except OSError as exc:
            QMessageBox.critical(self, "打开失败", str(exc))
            return
        self.source_edit.setPlainText(source)
        self.source_edit.document().setModified(False)
        self.log_panel.write(f"已打开：{path}")
        self.check_source()

    def export_source(self) -> None:
        source = self.source_edit.toPlainText()
        if not source.strip():
            QMessageBox.warning(self, "没有代码", "请先生成或输入场景代码")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出 ManimGL 场景",
            str(self.project_root / "generated_scene.py"),
            "Python 文件 (*.py)",
        )
        if not path:
            return
        try:
            Path(path).write_text(source.rstrip() + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.log_panel.write(f"源码已导出：{path}")
        self.source_edit.document().setModified(False)

    def check_source(self) -> list:
        source = self.source_edit.toPlainText()
        self._refresh_scene_names(source)
        diagnostics = check_code(source)
        if not diagnostics:
            self.log_panel.write("代码检查通过")
            return []
        for item in diagnostics:
            location = f"第 {item.line} 行" if item.line else "全局"
            self.log_panel.write(
                f"[{item.severity.upper()}] {location} {item.rule}: {item.message}"
            )
            if item.suggestion:
                self.log_panel.write(f"  建议：{item.suggestion}")
        return diagnostics

    def _refresh_scene_names(self, source: str) -> None:
        current = self.scene_combo.currentText()
        names = detect_scene_names(source)
        self.scene_combo.clear()
        self.scene_combo.addItems(names)
        if current in names:
            self.scene_combo.setCurrentText(current)

    def render_scene(self) -> None:
        if self.render_process.state() != QProcess.ProcessState.NotRunning:
            QMessageBox.information(self, "渲染任务", "已有渲染任务正在运行")
            return
        source = self.source_edit.toPlainText().strip()
        if not source:
            QMessageBox.warning(self, "没有代码", "请先生成或输入场景代码")
            return
        diagnostics = self.check_source()
        errors = [item for item in diagnostics if item.severity == "error"]
        if errors:
            QMessageBox.warning(self, "检查未通过", "请先修复错误，再运行预览")
            return
        scene_name = self.scene_combo.currentText().strip()
        if not scene_name:
            QMessageBox.warning(self, "没有场景", "代码中没有可运行的 Scene 子类")
            return
        try:
            self.generated_file.parent.mkdir(parents=True, exist_ok=True)
            self.generated_file.write_text(source + "\n", encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "保存失败", str(exc))
            self.log_panel.write(f"保存失败：{exc}")
            return

        self.log_panel.write(f"场景已保存：{self.generated_file}")
        mode = self.mode_combo.currentText()
        quality = self.quality_combo.currentText()
        try:
            render_args = build_render_args(mode, quality)
        except ValueError as exc:
            QMessageBox.warning(self, "渲染设置", str(exc))
            return
        self.log_panel.write(f"正在启动 ManimGL：{mode}，{quality}")
        self.render_process.setWorkingDirectory(str(self.project_root))
        self.render_process.start(
            sys.executable,
            [
                "-m",
                "manimlib",
                str(self.generated_file),
                scene_name,
                *render_args,
            ],
        )

    def open_output_directory(self) -> None:
        output = self.project_root / "videos"
        output.mkdir(parents=True, exist_ok=True)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(output))):
            QMessageBox.warning(self, "打开失败", f"无法打开输出目录：{output}")

    def stop_render(self) -> None:
        if self.render_process.state() == QProcess.ProcessState.NotRunning:
            return
        self.log_panel.write("正在停止渲染任务…")
        self.render_process.terminate()
        QTimer.singleShot(3000, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self.render_process.state() != QProcess.ProcessState.NotRunning:
            self.render_process.kill()

    def _read_render_output(self) -> None:
        output = bytes(self.render_process.readAllStandardOutput()).decode(
            "utf-8",
            errors="replace",
        )
        if output:
            self.log_panel.write(output)

    def _render_started(self) -> None:
        self.render_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.log_panel.write("渲染进程已启动")

    def _render_finished(self, exit_code: int, _exit_status) -> None:
        self._read_render_output()
        self.render_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        if exit_code == 0:
            self.log_panel.write("预览运行完成")
        else:
            self.log_panel.write(f"渲染进程退出，代码：{exit_code}")

    def _render_error(self, error) -> None:
        self.log_panel.write(f"渲染进程错误：{error}")

    def _record_prompt(self, prompt: str) -> None:
        prompt = prompt.strip()
        if not prompt:
            return
        self.history = [prompt, *[item for item in self.history if item != prompt]][:20]
        self._refresh_history()

    def _refresh_history(self) -> None:
        self.history_combo.clear()
        self.history_combo.addItems(self.history)

    def _restore_settings(self) -> None:
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)
        self.prompt_edit.setPlainText(str(self.settings.value("last_prompt", "")))
        self.source_edit.setPlainText(str(self.settings.value("last_source", "")))
        try:
            history = json.loads(str(self.settings.value("history", "[]")))
        except json.JSONDecodeError:
            history = []
        self.history = [str(item) for item in history if str(item).strip()][:20]
        self._refresh_history()
        self._refresh_scene_names(self.source_edit.toPlainText())
        mode = str(self.settings.value("render_mode", "实时预览"))
        quality = str(self.settings.value("render_quality", "低清 480p"))
        scene_name = str(self.settings.value("scene_name", ""))
        if self.mode_combo.findText(mode) >= 0:
            self.mode_combo.setCurrentText(mode)
        if self.quality_combo.findText(quality) >= 0:
            self.quality_combo.setCurrentText(quality)
        if self.scene_combo.findText(scene_name) >= 0:
            self.scene_combo.setCurrentText(scene_name)
        self.source_edit.document().setModified(False)

    def _save_settings(self) -> None:
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("last_prompt", self.prompt_edit.toPlainText())
        self.settings.setValue("last_source", self.source_edit.toPlainText())
        self.settings.setValue("history", json.dumps(self.history, ensure_ascii=False))
        self.settings.setValue("render_mode", self.mode_combo.currentText())
        self.settings.setValue("render_quality", self.quality_combo.currentText())
        self.settings.setValue("scene_name", self.scene_combo.currentText())
        self.settings.sync()

    def _update_title(self, modified: bool) -> None:
        marker = " *" if modified else ""
        self.setWindowTitle(f"ManimGL 动画助手{marker}")

    def closeEvent(self, event) -> None:
        if self.render_process.state() != QProcess.ProcessState.NotRunning:
            self.stop_render()
        if self.source_edit.document().isModified():
            answer = QMessageBox.question(
                self,
                "尚未导出",
                "代码有未导出的修改，仍要关闭吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._save_settings()
        event.accept()
