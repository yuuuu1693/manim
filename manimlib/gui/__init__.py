"""Optional PySide6 interface for the ManimGL assistant."""


def launch() -> None:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise RuntimeError(
            "PySide6 未安装，请执行 'pip install -e .[gui]' 后重试"
        ) from exc

    from manimlib.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.exec()


__all__ = ["launch"]
