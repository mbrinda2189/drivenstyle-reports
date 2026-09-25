"""
sidebar.py - Left navigation sidebar
====================================

WHAT THIS MODULE DOES
---------------------
Draws the deep-navy sidebar on the left of the window:

    +------------------------+
    |  DRIVE N STYLE         |   <- brand wordmark with a sky-blue rule
    |  Monthly reports       |
    |                        |
    |  Generate reports      |   <- navigation buttons (one per page)
    |  Scan review        7  |      the active one has a light-blue bar
    |  Masters               |      on its left edge; a count badge can
    |  Monthly inputs        |      be shown next to a title
    |  History               |
    |                        |
    |  Version 0.1.0         |   <- version footer
    +------------------------+

Only one navigation button can be active at a time (QButtonGroup, exclusive).
When the user clicks one, the sidebar emits `pageRequested(index)` and the
main window switches the page. The main window can also call
`set_active(index)` when a page is opened from code (e.g. "Review issues").
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from app import __version__
from app.theme import Colors


class NavButton(QPushButton):
    """
    One sidebar entry: title on the left, optional count badge on the right.

    The badge is a separate QLabel placed inside the button so it can have
    its own rounded amber background.
    """

    def __init__(self, title: str):
        super().__init__(title)
        self.setObjectName("SidebarButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)

        inner = QHBoxLayout(self)
        inner.setContentsMargins(0, 0, 16, 0)
        inner.addStretch(1)
        self.badge = QLabel("")
        self.badge.setStyleSheet(
            f"background: {Colors.AMBER}; color: white; border-radius: 9px;"
            "padding: 1px 7px; font-size: 8.5pt; font-weight: 700;")
        self.badge.hide()
        inner.addWidget(self.badge)

    def set_badge(self, text: str) -> None:
        self.badge.setText(text)
        self.badge.setVisible(bool(text))


class Sidebar(QFrame):
    """The navigation sidebar. Emits pageRequested(int) on click."""

    pageRequested = Signal(int)

    def __init__(self, items: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(232)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 30, 0, 18)
        lay.setSpacing(0)

        # --- Brand wordmark ---------------------------------------------
        # "DRIVE N STYLE" in letter-spaced bold white, echoing the client's
        # invoice logo. A thin sky-blue rule underneath ties it to the theme.
        brand = QLabel("DRIVE N STYLE")
        brand.setObjectName("BrandTitle")
        brand.setContentsMargins(22, 0, 0, 0)
        lay.addWidget(brand)

        rule_row = QHBoxLayout()
        rule_row.setContentsMargins(22, 8, 0, 8)
        rule = QFrame()
        rule.setFixedSize(36, 3)
        rule.setStyleSheet(f"background: {Colors.SKY}; border-radius: 1px;")
        rule_row.addWidget(rule)
        rule_row.addStretch(1)
        lay.addLayout(rule_row)

        sub = QLabel("Monthly reports")
        sub.setObjectName("BrandSubtitle")
        sub.setContentsMargins(22, 0, 0, 0)
        lay.addWidget(sub)
        lay.addSpacing(36)

        # --- Navigation buttons ------------------------------------------
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: list[NavButton] = []
        for index, title in enumerate(items):
            btn = NavButton(title)
            self.group.addButton(btn, index)
            self.buttons.append(btn)
            lay.addWidget(btn)
        self.group.idClicked.connect(self.pageRequested.emit)
        self.buttons[0].setChecked(True)

        lay.addStretch(1)

        # --- Footer ------------------------------------------------------
        footer = QLabel(f"Version {__version__}  ·  UI preview")
        footer.setObjectName("SidebarFooter")
        footer.setContentsMargins(22, 0, 0, 0)
        lay.addWidget(footer)

    def set_active(self, index: int) -> None:
        """Highlight button `index` without emitting pageRequested."""
        self.buttons[index].setChecked(True)

    def set_badge(self, index: int, text: str) -> None:
        """Show (or clear, with "") a small count badge on a sidebar entry."""
        self.buttons[index].set_badge(text)
