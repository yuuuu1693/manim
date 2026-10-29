from __future__ import annotations

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


class PythonHighlighter(QSyntaxHighlighter):
    """Small dependency-free Python highlighter for the scene editor."""

    def __init__(self, document):
        super().__init__(document)
        self.rules = [
            (
                QRegularExpression(
                    r"\b(?:class|def|from|import|as|return|if|else|elif|for|while|"
                    r"in|try|except|finally|with|lambda|True|False|None)\b"
                ),
                _format("#7c3aed", bold=True),
            ),
            (QRegularExpression(r"\b(?:self|Scene|Circle|Square|Triangle|Text|Axes)\b"), _format("#075985")),
            (QRegularExpression(r"\b\d+(?:\.\d+)?\b"), _format("#b45309")),
            (QRegularExpression(r"#[^\n]*"), _format("#64748b", italic=True)),
            (QRegularExpression(r"'[^'\n]*'|\"[^\"\n]*\""), _format("#15803d")),
        ]

    def highlightBlock(self, text: str) -> None:
        for pattern, text_format in self.rules:
            iterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(
                    match.capturedStart(),
                    match.capturedLength(),
                    text_format,
                )


def _format(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    result = QTextCharFormat()
    result.setForeground(QColor(color))
    if bold:
        result.setFontWeight(QFont.Weight.Bold)
    result.setFontItalic(italic)
    return result
