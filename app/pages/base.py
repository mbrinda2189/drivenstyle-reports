"""
base.py - Common frame for every page
=====================================

WHAT THIS MODULE DOES
---------------------
`ScrollPage` is the parent class of every screen. It provides:

    * a scroll area, so the page still works on small laptop screens,
    * consistent outer margins (32 px) and spacing between sections,
    * the page header (title + description) at the top,
    * `self.content` - the vertical layout pages add their cards to,
    * `self.toast(text)` - shows a fading confirmation message using the
      main window's Toast widget.

Pages never touch the scroll area directly; they only add to `self.content`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from app.widgets.common import PageHeader


class ScrollPage(QScrollArea):
    """Base class for pages: scrollable body with a header and content layout."""

    def __init__(self, title: str, subtitle: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        body = QWidget()
        body.setObjectName("PageBody")
        self.setWidget(body)

        self.content = QVBoxLayout(body)
        self.content.setContentsMargins(36, 30, 36, 30)
        self.content.setSpacing(20)
        self.content.addWidget(PageHeader(title, subtitle))

    def toast(self, text: str) -> None:
        """Show a short confirmation message at the bottom-right of the window."""
        win = self.window()
        if hasattr(win, "toast"):
            win.toast(text)
