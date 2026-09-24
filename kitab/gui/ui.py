"""Small pieces the pages share."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QVBoxLayout, QWidget
from qfluentwidgets import ScrollArea, SettingCard, TitleLabel

ENGINE_LABELS = {
    "google": "Google Translate — free, no key",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "openailiked": "OpenAI-compatible server",
}

LANGUAGES = [("auto", "Detect automatically"), ("en", "English"), ("ja", "Japanese")]

#: Shown in the reasoning menu. "" sends nothing: the model's own default.
REASONING_LABELS = {
    "": "Reasoning: model default",
    "none": "Reasoning: none (fastest)",
    "minimal": "Reasoning: minimal",
    "low": "Reasoning: low",
    "medium": "Reasoning: medium",
    "high": "Reasoning: high",
    "xhigh": "Reasoning: extra high",
    "max": "Reasoning: max",
}

INPUT_SUFFIXES = (".pdf", ".epub", ".md", ".markdown", ".txt", ".html", ".htm")

STAGE_LABELS = {
    "starting": "Starting",
    "extract": "Reading the book",
    "ocr": "Recognising pages",
    "glossary": "Building the glossary",
    "translate": "Translating",
    "rebuild": "Assembling",
    "epub": "Writing EPUB",
    "pdf": "Printing PDF",
}


def engine_label(name: str) -> str:
    return ENGINE_LABELS.get(name, name)


def setting_row(icon, title: str, content: str | None, *widgets: QWidget):
    """A settings card with ``widgets`` on its right-hand side."""
    card = SettingCard(icon, title, content)
    for widget in widgets:
        card.hBoxLayout.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight)
        card.hBoxLayout.addSpacing(8)
    card.hBoxLayout.addSpacing(8)
    return card


class Page(ScrollArea):
    """A scrolling page with a title, the shape every navigation target shares."""

    def __init__(self, object_name: str, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.view = QWidget(self)
        self.view.setObjectName("view")
        self.body = QVBoxLayout(self.view)
        self.body.setContentsMargins(36, 24, 36, 36)
        self.body.setSpacing(12)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title = TitleLabel(title, self.view)
        self.body.addWidget(self.title)
        self.body.addSpacing(4)

        self.setWidget(self.view)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()


def open_path(path: str | Path) -> None:
    """Open a file or folder with the system's handler (Explorer, xdg-open)."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
