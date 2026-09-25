"""
review_page.py - "Scan review" screen
=====================================

WHAT THIS SCREEN DOES
---------------------
After the invoices are scanned, anything the tool could not handle on its own
is listed here so the user can fix it BEFORE the reports are generated:

    * an item matched by name because it has no SKU   -> Confirm
    * a missing car model / salesperson / payment mode -> choose from a list
    * an item that is not in the cost sheet            -> Add to master
    * an invoice from another firm (DNS Enterprises)   -> shown as Skipped
    * a PDF that could not be read                     -> Open file

Three tiles at the top show: files read, issues still open, files skipped.
Each row has a status pill ("Open" in amber, "Fixed" in green). Fixing a row
turns its pill green and lowers the open count; the sidebar badge follows.

Before any scan has run, the page shows an empty state that points the user
to the Generate reports page.

CURRENT BEHAVIOUR (v0.1.0 - UI preview)
---------------------------------------
The issues are the sample rows from sample_data.SCAN_ISSUES. Fixes are kept
on screen only; they are not yet saved to the masters or invoice data.

SIGNALS
-------
    openIssuesChanged(int) - number of issues still open (for sidebar badge)
    backRequested()        - user clicked "Continue to generate" / empty-state
                             button; main window returns to Generate page
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView, QLabel,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.pages.base import ScrollPage
from app.sample_data import SCAN_ISSUES
from app.theme import Colors
from app.widgets.common import Card, StatTile, button, label

# Status pill styles: (text, text colour, background colour)
PILLS = {
    "open": ("Open", Colors.AMBER, Colors.AMBER_TINT),
    "fixed": ("Fixed", Colors.GREEN, Colors.GREEN_TINT),
    "skipped": ("Skipped", Colors.SLATE, "#EEF2F7"),
}


def pill(kind: str) -> QWidget:
    """Return a small rounded status label centred in its table cell."""
    text, fg, bg = PILLS[kind]
    holder = QWidget()
    holder.setStyleSheet("background: transparent;")
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(6, 0, 6, 0)
    lbl = QLabel(text)
    lbl.setAlignment(Qt.AlignCenter)
    lbl.setStyleSheet(
        f"background: {bg}; color: {fg}; border-radius: 10px;"
        "padding: 2px 10px; font-weight: 600; font-size: 8.5pt;")
    lay.addWidget(lbl)
    lay.addStretch(1)
    return holder


def cell_holder(widget: QWidget) -> QWidget:
    """Wrap a control so it sits neatly inside a table cell with padding."""
    holder = QWidget()
    holder.setObjectName("CellHolder")
    holder.setStyleSheet("QWidget#CellHolder { background: transparent; }")
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(6, 3, 6, 3)
    lay.addWidget(widget)
    lay.addStretch(1)
    return holder


class ReviewPage(ScrollPage):
    """Lists scan issues and lets the user fix each one."""

    openIssuesChanged = Signal(int)
    backRequested = Signal()

    COL_INVOICE, COL_ISSUE, COL_FIX, COL_STATUS = range(4)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Scan review",
            "Fix anything the tool could not read or match before generating the reports.",
            parent,
        )
        # Two states: "empty" (no scan yet) and "results".
        self.states = QStackedWidget()
        self.states.addWidget(self._build_empty_state())
        self.states.addWidget(self._build_results())
        self.content.addWidget(self.states, 1)
        self._status: list[str] = []   # "open" / "fixed" / "skipped" per row

    # ------------------------------------------------------------------
    # Empty state
    # ------------------------------------------------------------------
    def _build_empty_state(self) -> QWidget:
        card = Card(padding=40)
        card.body.setAlignment(Qt.AlignCenter)
        title = label("No scan yet", "SectionTitle")
        title.setAlignment(Qt.AlignCenter)
        text = label("Choose the invoice folder and run a scan on the Generate "
                     "reports page. Any invoices that need attention will be listed here.",
                     "Muted", wrap=True)
        text.setAlignment(Qt.AlignCenter)
        text.setMaximumWidth(460)
        go = button("Go to Generate reports", "Primary")
        go.clicked.connect(self.backRequested.emit)
        card.body.addWidget(title, 0, Qt.AlignCenter)
        card.body.addWidget(text, 0, Qt.AlignCenter)
        card.body.addSpacing(8)
        card.body.addWidget(go, 0, Qt.AlignCenter)

        wrapper = QWidget()
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(card)
        lay.addStretch(1)
        return wrapper

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def _build_results(self) -> QWidget:
        wrapper = QWidget()
        lay = QVBoxLayout(wrapper)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(20)

        # Summary tiles
        tiles = QHBoxLayout()
        tiles.setSpacing(20)
        self.tile_read = StatTile("Files scanned", "0", Colors.INK)
        self.tile_open = StatTile("Need attention", "0", Colors.AMBER)
        self.tile_skip = StatTile("Skipped", "0", Colors.SLATE)
        for t in (self.tile_read, self.tile_open, self.tile_skip):
            tiles.addWidget(t, 1)
        lay.addLayout(tiles)

        # Issues table
        card = Card()
        head = QHBoxLayout()
        head.addWidget(label("Issues", "SectionTitle"))
        head.addStretch(1)
        export_btn = button("Export issues list", "Secondary")
        export_btn.clicked.connect(
            lambda: self.toast("Export will be added with the invoice reader."))
        head.addWidget(export_btn)
        card.body.addLayout(head)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Invoice", "Issue", "Fix", "Status"])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setFocusPolicy(Qt.NoFocus)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(self.COL_INVOICE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(self.COL_ISSUE, QHeaderView.Stretch)
        hdr.setSectionResizeMode(self.COL_FIX, QHeaderView.Fixed)
        hdr.setSectionResizeMode(self.COL_STATUS, QHeaderView.Fixed)
        self.table.setColumnWidth(self.COL_FIX, 240)
        self.table.setColumnWidth(self.COL_STATUS, 100)
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setDefaultSectionSize(46)
        card.body.addWidget(self.table)

        foot = QHBoxLayout()
        self.footer_note = label("", "Muted")
        foot.addWidget(self.footer_note, 1)
        cont = button("Continue to generate", "Primary")
        cont.clicked.connect(self.backRequested.emit)
        foot.addWidget(cont)
        card.body.addLayout(foot)

        lay.addWidget(card)
        lay.addStretch(1)
        return wrapper

    # ------------------------------------------------------------------
    # Loading and fixing issues
    # ------------------------------------------------------------------
    def load_issues(self, files_scanned: int) -> None:
        """Fill the table with the (sample) issues from the latest scan."""
        self.states.setCurrentIndex(1)
        self.tile_read.set_value(str(files_scanned))
        self.table.setRowCount(0)
        self._status = []

        for row, (invoice, issue, fix_type, options) in enumerate(SCAN_ISSUES):
            self.table.insertRow(row)
            inv_item = QTableWidgetItem(invoice)
            inv_item.setForeground(Qt.black)
            self.table.setItem(row, self.COL_INVOICE, inv_item)
            self.table.setItem(row, self.COL_ISSUE, QTableWidgetItem(issue))

            status = "skipped" if fix_type in ("skip", "open") else "open"
            self._status.append(status)
            self.table.setCellWidget(row, self.COL_FIX,
                                     self._fix_control(row, fix_type, options))
            self.table.setCellWidget(row, self.COL_STATUS, pill(status))

        self.table.setFixedHeight(
            self.table.horizontalHeader().height()
            + 46 * self.table.rowCount() + 4)
        self._update_counts()

    def _fix_control(self, row: int, fix_type: str, options: list[str]) -> QWidget:
        """Build the control shown in the Fix column for one issue."""
        if fix_type == "confirm":
            btn = button("Confirm match", "Ghost")
            btn.clicked.connect(lambda: (btn.setText("Confirmed"), btn.setEnabled(False),
                                         self._mark_fixed(row, "Match confirmed")))
            return cell_holder(btn)
        if fix_type == "choose":
            combo = QComboBox()
            combo.addItems(options)
            combo.setMinimumWidth(215)
            combo.currentIndexChanged.connect(
                lambda i: i > 0 and self._mark_fixed(row, f"Set to {combo.currentText()}"))
            return cell_holder(combo)
        if fix_type == "add":
            btn = button("Add to master", "Ghost")
            btn.clicked.connect(lambda: (btn.setText("Added"), btn.setEnabled(False),
                                         self._mark_fixed(row, "Item will be added to the cost sheet")))
            return cell_holder(btn)
        if fix_type == "open":
            btn = button("Open file", "Ghost")
            btn.clicked.connect(
                lambda: self.toast("Opening the PDF will work with the invoice reader."))
            return cell_holder(btn)
        # "skip" - nothing to do, show a muted note
        return cell_holder(label("No action needed", "Muted"))

    def _mark_fixed(self, row: int, message: str) -> None:
        """Turn a row's status pill green and update the counters."""
        if self._status[row] == "fixed":
            return
        self._status[row] = "fixed"
        self.table.setCellWidget(row, self.COL_STATUS, pill("fixed"))
        self._update_counts()
        self.toast(f"{self.table.item(row, self.COL_INVOICE).text()}: {message}")

    def _update_counts(self) -> None:
        open_count = self._status.count("open")
        self.tile_open.set_value(str(open_count))
        self.tile_skip.set_value(str(self._status.count("skipped")))
        self.footer_note.setText(
            "All issues resolved." if open_count == 0 else
            f"{open_count} issue{'s' if open_count != 1 else ''} still open. "
            "Open issues are left out of the affected reports.")
        self.openIssuesChanged.emit(open_count)
