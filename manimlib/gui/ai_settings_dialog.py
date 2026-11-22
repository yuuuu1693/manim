from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from manimlib.ai.provider import ProviderConfig, ProviderError


class AISettingsDialog(QDialog):
    """Edit provider settings without persisting the API key to disk."""

    def __init__(
        self,
        values: Mapping[str, str] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("大模型配置")
        self.setMinimumWidth(480)
        current = dict(values or {})

        layout = QVBoxLayout(self)
        notice = QLabel("API 密钥只保留在本次软件运行期间，不会写入配置文件。")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        form = QFormLayout()
        self.base_url_edit = QLineEdit(
            current.get("MANIM_AI_BASE_URL", "https://api.openai.com/v1")
        )
        self.model_edit = QLineEdit(current.get("MANIM_AI_MODEL", ""))
        self.api_key_edit = QLineEdit(current.get("MANIM_AI_API_KEY", ""))
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("仅保存在内存中")
        self.timeout_edit = QLineEdit(current.get("MANIM_AI_TIMEOUT", "20"))
        form.addRow("API 地址", self.base_url_edit)
        form.addRow("模型名称", self.model_edit)
        form.addRow("API 密钥", self.api_key_edit)
        form.addRow("超时（秒）", self.timeout_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def provider_environ(self) -> dict[str, str]:
        return {
            "MANIM_AI_BASE_URL": self.base_url_edit.text().strip(),
            "MANIM_AI_MODEL": self.model_edit.text().strip(),
            "MANIM_AI_API_KEY": self.api_key_edit.text().strip(),
            "MANIM_AI_TIMEOUT": self.timeout_edit.text().strip(),
        }

    def _validate_and_accept(self) -> None:
        try:
            config = ProviderConfig.from_env(self.provider_environ())
        except ProviderError as exc:
            QMessageBox.warning(self, "配置无效", str(exc))
            return
        if config is None:
            QMessageBox.warning(self, "配置不完整", "请填写模型名称和 API 密钥")
            return
        self.accept()
