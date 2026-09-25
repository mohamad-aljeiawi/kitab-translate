"""Building blocks the pages share.

The rule every row follows: text wraps, controls keep their size, and when the two
no longer fit side by side the controls move under the text. Nothing is given a
fixed position, so a narrow window reflows instead of overlapping, and the same
layouts mirror correctly when the app runs right to left.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QBoxLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    IconWidget,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TitleLabel,
    TransparentToolButton,
)

from .i18n import tr

#: Below this, a row's text is too cramped to share the line with its controls.
_MIN_TEXT_WIDTH = 260


def open_path(path: str | Path) -> None:
    """Open a file or folder with the system's handler (Explorer, xdg-open)."""
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def lead_align(label: QLabel) -> None:
    """Align to the reading start of the *interface*, whatever script the text is.

    A label aligns by the direction of its own text, so an Arabic book title sat on
    the right of an English window, apart from everything else in the row.
    """
    edge = (
        Qt.AlignmentFlag.AlignRight
        if label.layoutDirection() == Qt.LayoutDirection.RightToLeft
        else Qt.AlignmentFlag.AlignLeft
    )
    label.setAlignment(
        edge | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
    )


class _Elided:
    """Mixin: show as much of the text as fits, with the rest in a tooltip."""

    def _setup_elide(self, mode: Qt.TextElideMode) -> None:
        self._full = ""
        self._mode = mode
        self.setMinimumWidth(1)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_text(self, text: str) -> None:
        self._full = text or ""
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(
            self._full, self._mode, max(1, self.width())
        )
        QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")


class ElidedStrongLabel(_Elided, StrongBodyLabel):
    def __init__(self, text: str = "", parent=None, mode=Qt.TextElideMode.ElideMiddle):
        super().__init__(parent)
        self._setup_elide(mode)
        lead_align(self)
        self.set_text(text)


class ElidedCaptionLabel(_Elided, CaptionLabel):
    def __init__(self, text: str = "", parent=None, mode=Qt.TextElideMode.ElideRight):
        super().__init__(parent)
        self._setup_elide(mode)
        lead_align(self)
        self.set_text(text)


class _Wrapping:
    """Mixin: wrap to the width the layout gives, never demand one of our own.

    A word-wrapped label reports a minimum height as if it had to fit its text
    into almost no width -- one word per line -- and a scroll area sizes its page
    to that minimum, which left screens of empty space below the content. The
    minimum is one line; the layout asks heightForWidth for the real height.
    """

    def _setup_wrap(self) -> None:
        self.setWordWrap(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lead_align(self)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(0, self.fontMetrics().height())


class WrapBodyLabel(_Wrapping, BodyLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self._setup_wrap()


class WrapCaptionLabel(_Wrapping, CaptionLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self.setText(text)
        self._setup_wrap()


class OptionRow(QWidget):
    """Icon, title, a sentence of explanation, and the controls that act on it."""

    def __init__(self, icon, title: str, description: str = "", *controls, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(14)

        self.icon = IconWidget(icon, self)
        self.icon.setFixedSize(18, 18)
        outer.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        outer.addSpacing(2)

        self._content = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self._content.setSpacing(12)
        outer.addLayout(self._content, 1)

        text = QVBoxLayout()
        text.setSpacing(2)
        self.title = WrapBodyLabel(title, self)
        self.description = WrapCaptionLabel(description, self)
        self.description.setVisible(bool(description))
        text.addWidget(self.title)
        text.addWidget(self.description)
        self._content.addLayout(text, 1)

        self._controls = QHBoxLayout()
        self._controls.setSpacing(8)
        for control in controls:
            self.add_control(control)
        self._content.addLayout(self._controls, 0)

    def add_control(self, control: QWidget) -> None:
        self._controls.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_description(self, text: str) -> None:
        self.description.setText(text)
        self.description.setVisible(bool(text))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # 18px icon + margins; what is left is shared between text and controls.
        available = self.width() - 64
        stacked = available < self._controls.sizeHint().width() + _MIN_TEXT_WIDTH
        direction = (
            QBoxLayout.Direction.TopToBottom
            if stacked
            else QBoxLayout.Direction.LeftToRight
        )
        if self._content.direction() != direction:
            self._content.setDirection(direction)
            leading = Qt.AlignmentFlag.AlignLeading if stacked else Qt.AlignmentFlag(0)
            self._content.setAlignment(self._controls, leading)


class Section(QWidget):
    """A heading, then a card of rows separated by hairlines."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.heading = StrongBodyLabel(title, self)
        lead_align(self.heading)
        layout.addWidget(self.heading)
        self.card = CardWidget(self)
        self._rows = QVBoxLayout(self.card)
        self._rows.setContentsMargins(0, 4, 0, 4)
        self._rows.setSpacing(0)
        layout.addWidget(self.card)

    def add(self, widget: QWidget) -> QWidget:
        if self._rows.count():
            line = QFrame(self.card)
            line.setFrameShape(QFrame.Shape.HLine)
            line.setFixedHeight(1)
            line.setStyleSheet("background: rgba(128, 128, 128, 0.18); border: none;")
            self._rows.addWidget(line)
            widget._separator = line  # hidden together with its row
        self._rows.addWidget(widget)
        return widget


def show_row(row: QWidget, visible: bool) -> None:
    row.setVisible(visible)
    line = getattr(row, "_separator", None)
    if line is not None:
        line.setVisible(visible)


class Collapsible(QWidget):
    """A section whose body opens from a header row: for options most people skip."""

    toggled = Signal(bool)

    def __init__(self, title: str, description: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.header = CardWidget(self)
        header = QHBoxLayout(self.header)
        header.setContentsMargins(16, 12, 12, 12)
        header.setSpacing(14)
        icon = IconWidget(FluentIcon.SETTING, self.header)
        icon.setFixedSize(18, 18)
        header.addWidget(icon)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(WrapBodyLabel(title, self.header))
        text.addWidget(WrapCaptionLabel(description, self.header))
        header.addLayout(text, 1)
        self.arrow = IconWidget(FluentIcon.CHEVRON_DOWN_MED, self.header)
        self.arrow.setFixedSize(12, 12)
        header.addWidget(self.arrow)
        self.header.clicked.connect(lambda: self.set_open(not self._open))
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.header)

        self.body = Section("", self)
        self.body.heading.hide()
        self.body.hide()
        layout.addWidget(self.body)
        self._open = False

    def add(self, widget: QWidget) -> QWidget:
        return self.body.add(widget)

    def set_open(self, open_: bool) -> None:
        self._open = open_
        self.body.setVisible(open_)
        self.arrow.setIcon(FluentIcon.UP if open_ else FluentIcon.CHEVRON_DOWN_MED)
        self.toggled.emit(open_)


def make_switch(checked: bool = False) -> SwitchButton:
    switch = SwitchButton()
    switch.setOnText(tr("switch.on"))
    switch.setOffText(tr("switch.off"))
    switch.setChecked(checked)
    return switch


def make_combo(items: list[tuple[str, str]], value: str, width: int = 220) -> ComboBox:
    """A ComboBox of (value, label) pairs, with ``value`` selected."""
    combo = ComboBox()
    for data, label in items:
        combo.addItem(label, userData=data)
    combo.setCurrentIndex(max(0, combo.findData(value)))
    combo.setMinimumWidth(width)
    return combo


def tool_button(icon, tip: str) -> TransparentToolButton:
    from qfluentwidgets import ToolTipFilter

    button = TransparentToolButton(icon)
    button.setToolTip(tip)
    button.installEventFilter(ToolTipFilter(button))
    return button


class _PageView(QWidget):
    """The scrolling body of a page, sized by its real height at its real width.

    Left to itself, Qt adds up the *minimum* heights of every wrapped label, each
    measured as if it had no width at all, and the scroll area makes the page that
    tall: screens of empty space under the last option. Reporting no minimum makes
    the scroll area use heightForWidth, which is the height the content needs.
    """

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return QSize(0, 0)


class Page(QWidget):
    """A navigation target: a title, scrolling content, and an optional fixed footer.

    The footer stays put while the content scrolls, so the main action of a page is
    never below the fold.
    """

    def __init__(self, object_name: str, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName(object_name)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.scroll = ScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.enableTransparentBackground()
        self.view = _PageView()
        self.view.setObjectName("view")
        self.body = QVBoxLayout(self.view)
        self.body.setSizeConstraint(QVBoxLayout.SizeConstraint.SetNoConstraint)
        self.body.setContentsMargins(32, 20, 32, 24)
        self.body.setSpacing(16)
        self.body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.title = TitleLabel(title, self.view)
        lead_align(self.title)
        self.body.addWidget(self.title)
        self.scroll.setWidget(self.view)
        outer.addWidget(self.scroll, 1)

        self.footer = QWidget(self)
        self.footer_layout = QHBoxLayout(self.footer)
        self.footer_layout.setContentsMargins(32, 12, 32, 16)
        self.footer.hide()
        outer.addWidget(self.footer)

    def verticalScrollBar(self):  # noqa: N802 (kept for callers of the old API)
        return self.scroll.verticalScrollBar()


class EmptyState(QWidget):
    def __init__(
        self, icon, title: str, body: str, action: QWidget | None = None, parent=None
    ):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 48, 0, 48)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        picture = IconWidget(icon, self)
        picture.setFixedSize(QSize(40, 40))
        layout.addWidget(picture, 0, Qt.AlignmentFlag.AlignHCenter)
        heading = SubtitleLabel(title, self)
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(heading)
        text = CaptionLabel(body, self)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(text)
        if action is not None:
            layout.addSpacing(8)
            layout.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)
