"""
audit_view.py - The "Audit log" tab of the Masters screen
=========================================================

WHAT THIS MODULE DOES
---------------------
Shows every change made to the masters, newest first, read from the
database's audit_log table (written by masters_repo.py). It is read-only:
there is no way to edit or delete an entry from the tool, and the database
itself refuses such changes.

    +----------------------------------------------------------------------+
    | [All masters v] [All actions v]  From [01-09-2026] To [28-09-2026]   |
    | [Search…]                                        [Export to Excel]   |
    | +------------------------------------------------------------------+ |
    | | Date & time | User | Master | Record | Action | Field | Old | New | |
    | |             |      |        |        |        |       |     |     | |
    | +------------------------------------------------------------------+ |
    | 124 entries                                                          |
    +----------------------------------------------------------------------+

Filters (all work together): master, action (Added / Edited / Activated /
Deactivated / Deleted), date range (default: the last 30 days) and a search
box that looks in the record, field, old and new values, user and source.

Actions are colour-coded: Added green, Edited blue, Deleted red,
Activated / Deactivated grey. Hovering a long old/new value shows it in
full. At most 5,000 entries are shown at once; "Export to Excel" writes
every entry matching the filters.

`refresh()` is called by the Masters page whenever a master changes, so
the log is always current.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QFileDialog, QHBoxLayout,
    QHeaderView, QLineEdit, QMessageBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.data.excel_io import export_audit
from app.data.master_defs import ALL_MASTERS
from app.data.masters_repo import MastersRepo
from app.theme import Colors
from app.widgets.common import button, label

ACTIONS = ("Added", "Edited", "Activated", "Deactivated", "Deleted")
ACTION_COLOURS = {"Added": Colors.GREEN, "Edited": Colors.BLUE,
                  "Deleted": Colors.RED}
SHOW_LIMIT = 5000
# (entry key, heading, width in px). Wider than the window: the table
# scrolls sideways; hover a long value to read it in full.
COLUMNS = (("at", "Date & time", 170), ("user", "User", 90),
           ("master", "Master", 145), ("record", "Record", 220),
           ("action", "Action", 110), ("field", "Field", 175),
           ("old_value", "Old value", 260), ("new_value", "New value", 260),
           ("source", "Source", 220))


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


class AuditLogView(QWidget):
    """Filterable, read-only list of master changes."""

    def __init__(self, repo: MastersRepo, toast, parent=None):
        super().__init__(parent)
        self.repo = repo
        self.toast = toast
        self.titles = {m.key: m.title for m in ALL_MASTERS}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(10)

        # --- filters ----------------------------------------------------
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.master_combo = QComboBox()
        self.master_combo.addItem("All masters", None)
        for m in ALL_MASTERS:
            self.master_combo.addItem(m.title, m.key)
        self.action_combo = QComboBox()
        self.action_combo.addItem("All actions", None)
        for a in ACTIONS:
            self.action_combo.addItem(a, a)
        today = date.today()
        self.from_date = QDateEdit(_qdate(today - timedelta(days=30)))
        self.to_date = QDateEdit(_qdate(today))
        for d in (self.from_date, self.to_date):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd-MM-yyyy")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search the log…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(220)

        bar.addWidget(self.master_combo)
        bar.addWidget(self.action_combo)
        bar.addWidget(label("From"))
        bar.addWidget(self.from_date)
        bar.addWidget(label("To"))
        bar.addWidget(self.to_date)
        bar.addWidget(self.search)
        bar.addStretch(1)
        export = button("Export to Excel", "Secondary")
        export.clicked.connect(self._export)
        bar.addWidget(export)
        lay.addLayout(bar)

        for w in (self.master_combo, self.action_combo):
            w.currentIndexChanged.connect(self.refresh)
        for d in (self.from_date, self.to_date):
            d.dateChanged.connect(self.refresh)
        self.search.textChanged.connect(self.refresh)

        # --- table ------------------------------------------------------
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([h for _, h, _ in COLUMNS])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setMinimumHeight(420)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i, (_, _, width) in enumerate(COLUMNS):
            hdr.setSectionResizeMode(i, QHeaderView.Interactive)
            self.table.setColumnWidth(i, width)
        lay.addWidget(self.table)

        self.count_label = label("", "Muted")
        lay.addWidget(self.count_label)
        self.refresh()

    # ------------------------------------------------------------------
    def show_latest(self) -> None:
        """Called after a master changes: make sure today's entries are
        inside the date range (the tool may have been open since
        yesterday), then reload."""
        today = _qdate(date.today())
        if self.to_date.date() < today:
            self.to_date.blockSignals(True)
            self.to_date.setDate(today)
            self.to_date.blockSignals(False)
        self.refresh()

    def _filters(self) -> dict:
        return dict(master=self.master_combo.currentData(),
                    action=self.action_combo.currentData(),
                    date_from=_pydate(self.from_date.date()),
                    date_to=_pydate(self.to_date.date()),
                    text=self.search.text())

    def refresh(self, *_) -> None:
        """Reload the entries matching the filters."""
        entries = self.repo.audit_entries(**self._filters(), limit=SHOW_LIMIT + 1)
        more = len(entries) > SHOW_LIMIT
        entries = entries[:SHOW_LIMIT]
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            for c, (key, _, _) in enumerate(COLUMNS):
                value = e.get(key) or ""
                if key == "at":
                    value = datetime.fromisoformat(value).strftime("%d-%m-%Y %H:%M:%S")
                elif key == "master":
                    value = self.titles.get(value, value)
                item = QTableWidgetItem(str(value))
                if key in ("old_value", "new_value", "record", "source") and value:
                    item.setToolTip(str(value))
                if key == "action":
                    item.setForeground(QBrush(QColor(
                        ACTION_COLOURS.get(value, Colors.SLATE))))
                self.table.setItem(r, c, item)
        n = len(entries)
        text = f"{n} entr{'ies' if n != 1 else 'y'}"
        if more:
            text = f"Showing the latest {SHOW_LIMIT:,} entries. Narrow the " \
                   "filters or export to see all."
        self.count_label.setText(text if n else "No changes match these filters.")

    def _export(self) -> None:
        """Write all entries matching the filters to an Excel file."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export audit log", f"Audit_log_{date.today():%d-%m-%Y}.xlsx",
            "Excel workbook (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        entries = self.repo.audit_entries(**self._filters())
        try:
            export_audit(entries, path, self.titles)
        except OSError as exc:
            QMessageBox.warning(self, "Export failed",
                                f"The file could not be written:\n{exc}\n\n"
                                "If it is open in Excel, close it and try again.")
            return
        self.toast(f"Audit log exported ({len(entries)} entries).")