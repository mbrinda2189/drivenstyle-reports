"""
common.py - Shared widgets used across all pages
================================================

WHAT THIS MODULE DOES
---------------------
Provides the small, reusable pieces every screen is built from, so that all
pages look and behave the same way:

    label(text, name)      - Creates a QLabel with an objectName (for styling).
    button(text, kind)     - Creates a Primary / Secondary / Ghost / Danger
                             button with the right style and hand cursor.
    Card                   - White rounded panel with a soft shadow. Pages
                             group related controls inside cards.
    PageHeader             - Page title + one-line description at the top of
                             every page.
    StepHeader             - Numbered circle + title, used on the Generate
                             page where the steps really are a sequence.
                             The circle turns green when the step is done.
    AnimatedButton         - The primary (filled blue) button. Its background
                             colour glides smoothly between normal / hover /
                             pressed shades instead of snapping, which gives
                             the "smooth" feel the client asked for.
    PathPicker             - Read-only path box + Browse button. Opens a
                             folder or file dialog and emits `pathChanged`.
    StatTile               - A small card showing one number and its label
                             (used on the Scan Review page).
    Toast                  - A short confirmation message that fades in at
                             the bottom-right of the window and fades out.
    scroll_body(dialog)    - (v0.6.4) Gives a pop-up window a scrolling body
                             and a fixed button row, so nothing is pushed off
                             a small or zoomed-in screen.
    fit_to_screen(w, ...)  - Opens a window at its preferred size, but never
                             larger than the screen it is on.
    NoWheelComboBox /      - Drop-downs / date boxes that ignore the mouse
    NoWheelDateEdit          wheel until clicked, so scrolling a window
                             cannot change a value by accident.
"""

from __future__ import annotations

from PySide6.QtCore import (
    Property, QEasingCurve, QEvent, QPropertyAnimation, QTimer, Qt, Signal,
)
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFileDialog, QFrame, QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app.theme import Colors


# ---------------------------------------------------------------------------
# Pop-up windows that fit any screen (v0.6.4)
# ---------------------------------------------------------------------------
def scroll_body(dialog: QWidget, margins=(26, 22, 26, 12)
                ) -> tuple[QVBoxLayout, QHBoxLayout]:
    """
    Lay out `dialog` as a scrolling body above a fixed button row.
    Returns (body layout, button-row layout). On a laptop screen with
    Windows zoom at 125-150 %, the Import window was taller than the
    screen and its Import button could not be reached; with this, the body
    scrolls and the buttons always stay visible.
    """
    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setStyleSheet("QScrollArea { background: transparent; }")
    body = QWidget()
    body.setObjectName("DialogBody")
    body.setStyleSheet("#DialogBody { background: transparent; }")
    lay = QVBoxLayout(body)
    lay.setContentsMargins(*margins)
    lay.setSpacing(12)
    scroll.setWidget(body)
    outer.addWidget(scroll, 1)

    footer = QFrame()
    footer.setObjectName("DialogFooter")
    footer.setStyleSheet(f"#DialogFooter {{ border-top: 1px solid {Colors.LINE}; }}")
    btns = QHBoxLayout(footer)
    btns.setContentsMargins(margins[0], 12, margins[2], 16)
    btns.setSpacing(10)
    outer.addWidget(footer)
    return lay, btns


def fit_to_screen(widget: QWidget, width: int, height: int, margin: int = 80) -> None:
    """Resize to width x height, but no larger than the available screen."""
    screen = widget.screen() or QGuiApplication.primaryScreen()
    if screen is None:
        widget.resize(width, height)
        return
    avail = screen.availableGeometry()
    widget.resize(min(width, avail.width() - margin),
                  min(height, avail.height() - margin))


class NoWheelComboBox(QComboBox):
    """A drop-down that only reacts to the mouse wheel once clicked."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):                    # noqa: N802 (Qt name)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()                          # let the window scroll


class NoWheelDateEdit(QDateEdit):
    """A date box that only reacts to the mouse wheel once clicked."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, event):                    # noqa: N802 (Qt name)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def label(text: str, name: str | None = None, wrap: bool = False) -> QLabel:
    """Create a QLabel, optionally with an objectName used by the stylesheet."""
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


def button(text: str, kind: str = "Secondary") -> QPushButton:
    """
    Create a styled push button.

    kind = "Primary"   -> AnimatedButton (filled blue, smooth hover)
           "Secondary" -> outlined blue button
           "Ghost"     -> text-only blue button (used inside tables)
           "Danger"    -> red outlined button (remove / delete)
    """
    if kind == "Primary":
        return AnimatedButton(text)
    btn = QPushButton(text)
    btn.setObjectName(f"{kind}Button")
    btn.setCursor(Qt.PointingHandCursor)
    return btn


# ---------------------------------------------------------------------------
# Card
# ---------------------------------------------------------------------------
class Card(QFrame):
    """
    A white rounded panel with a very soft drop shadow.

    Usage:
        card = Card()
        card.body.addWidget(some_widget)

    `card.body` is a QVBoxLayout with comfortable padding already applied.
    """

    def __init__(self, parent: QWidget | None = None, padding: int = 20,
                 shadow: bool = True):
        super().__init__(parent)
        self.setObjectName("Card")

        if shadow:
            # Soft shadow: large blur, low opacity, pushed slightly down so
            # the card appears to float just above the page.
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(18)
            effect.setOffset(0, 2)
            effect.setColor(QColor(11, 37, 69, 22))
            self.setGraphicsEffect(effect)

        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(12)


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
class PageHeader(QWidget):
    """Title and a one-line description shown at the top of every page."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(label(title, "PageTitle"))
        lay.addWidget(label(subtitle, "PageSubtitle", wrap=True))


class StepHeader(QWidget):
    """
    Numbered step heading: a blue circle with the step number and a title.

    Call `set_done(True)` to turn the circle green with a tick, so the user
    can see at a glance which steps are complete.
    """

    def __init__(self, number: int, title: str, hint: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self._number = number
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.badge = label(str(number), "StepBadge")
        lay.addWidget(self.badge, 0, Qt.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.addWidget(label(title, "SectionTitle"))
        if hint:
            text_col.addWidget(label(hint, "Muted", wrap=True))
        lay.addLayout(text_col, 1)

    def set_done(self, done: bool) -> None:
        """Switch the badge between 'pending' (blue number) and 'done' (green tick)."""
        self.badge.setObjectName("StepBadgeDone" if done else "StepBadge")
        self.badge.setText("✓" if done else str(self._number))
        # Re-polish so the new objectName's style is applied immediately.
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)


# ---------------------------------------------------------------------------
# AnimatedButton
# ---------------------------------------------------------------------------
class AnimatedButton(QPushButton):
    """
    Primary action button whose background colour animates smoothly.

    Qt stylesheets cannot animate colour changes, so this class keeps the
    current colour in a Qt Property (`bgColor`) and uses a
    QPropertyAnimation to glide between:
        normal  (Colors.BLUE)
        hover   (Colors.BLUE_HOVER)
        pressed (Colors.BLUE_PRESSED)
    Each animation step rewrites this button's own small stylesheet.
    """

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setObjectName("PrimaryButton")
        self.setCursor(Qt.PointingHandCursor)
        self._color = QColor(Colors.BLUE)
        self._anim = QPropertyAnimation(self, b"bgColor", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._apply()

    # --- Qt property used by the animation ---------------------------------
    def _get_color(self) -> QColor:
        return self._color

    def _set_color(self, color: QColor) -> None:
        self._color = color
        self._apply()

    bgColor = Property(QColor, _get_color, _set_color)

    def _apply(self) -> None:
        """Write the current colour into the button's stylesheet."""
        if self.isEnabled():
            self.setStyleSheet(
                f"QPushButton#PrimaryButton {{ background: {self._color.name()}; }}")
        else:
            self.setStyleSheet("")  # fall back to the global :disabled style

    def _animate_to(self, hex_color: str) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._color)
        self._anim.setEndValue(QColor(hex_color))
        self._anim.start()

    # --- Mouse events trigger the colour changes ---------------------------
    def enterEvent(self, event):
        if self.isEnabled():
            self._animate_to(Colors.BLUE_HOVER)
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isEnabled():
            self._animate_to(Colors.BLUE)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if self.isEnabled():
            self._animate_to(Colors.BLUE_PRESSED)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self.isEnabled():
            self._animate_to(Colors.BLUE_HOVER if self.underMouse() else Colors.BLUE)
        super().mouseReleaseEvent(event)

    def changeEvent(self, event):
        """When the button is enabled/disabled, refresh its colour."""
        super().changeEvent(event)
        if event.type() == QEvent.EnabledChange:
            self._anim.stop()
            self._color = QColor(Colors.BLUE)
            self._apply()


# ---------------------------------------------------------------------------
# PathPicker
# ---------------------------------------------------------------------------
class PathPicker(QWidget):
    """
    A read-only text box showing a chosen path, with a Browse button.

    mode = "folder" -> opens a folder chooser
    mode = "file"   -> opens a file chooser filtered by `file_filter`

    Emits `pathChanged(str)` after the user picks something.
    """

    pathChanged = Signal(str)

    def __init__(self, placeholder: str, mode: str = "folder",
                 file_filter: str = "All files (*.*)",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.mode = mode
        self.file_filter = file_filter

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        self.edit = QLineEdit()
        self.edit.setReadOnly(True)
        self.edit.setPlaceholderText(placeholder)
        lay.addWidget(self.edit, 1)

        self.browse = button("Browse…", "Secondary")
        self.browse.clicked.connect(self._browse)
        lay.addWidget(self.browse)

    def path(self) -> str:
        return self.edit.text()

    def set_path(self, path: str) -> None:
        self.edit.setText(path)
        self.pathChanged.emit(path)

    def _browse(self) -> None:
        """Open the right kind of dialog and store the user's choice."""
        if self.mode == "folder":
            chosen = QFileDialog.getExistingDirectory(self, "Choose folder", self.path())
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, "Choose file", self.path(),
                                                    self.file_filter)
        if chosen:
            self.set_path(chosen)


# ---------------------------------------------------------------------------
# StatTile
# ---------------------------------------------------------------------------
class StatTile(Card):
    """
    A card showing one large number with a caption underneath.

    `accent` colours the number (e.g. green for OK, amber for issues).
    """

    def __init__(self, caption: str, value: str = "0",
                 accent: str = Colors.INK, parent: QWidget | None = None):
        super().__init__(parent, padding=16)
        self.value_label = label(value, "StatValue")
        self.value_label.setStyleSheet(f"color: {accent};")
        self.body.setSpacing(2)
        self.body.addWidget(self.value_label)
        self.body.addWidget(label(caption, "StatLabel"))

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


# ---------------------------------------------------------------------------
# Toast
# ---------------------------------------------------------------------------
class Toast(QLabel):
    """
    A brief confirmation message ("Changes saved") that fades in at the
    bottom-right of its parent window, stays for a moment, then fades out.

    Usage (from any page):  self.window().toast("Changes saved")
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setWordWrap(True)
        self.setMaximumWidth(400)
        self.hide()

        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.finished.connect(self._on_fade_finished)
        self._fading_out = False

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

    def show_message(self, text: str, duration_ms: int = 2600) -> None:
        """Display `text` for `duration_ms` milliseconds."""
        self.setText(text)
        self.adjustSize()
        parent = self.parentWidget()
        margin = 24
        self.move(parent.width() - self.width() - margin,
                  parent.height() - self.height() - margin)
        self.raise_()
        self.show()

        self._fading_out = False
        self._fade.stop()
        self._fade.setStartValue(self._effect.opacity() if self.isVisible() else 0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(duration_ms)

    def _fade_out(self) -> None:
        self._fading_out = True
        self._fade.stop()
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.start()

    def _on_fade_finished(self) -> None:
        if self._fading_out:
            self.hide()
