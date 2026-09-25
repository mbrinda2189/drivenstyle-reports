"""
masters_page.py - "Masters" screen
==================================

WHAT THIS SCREEN DOES
---------------------
Shows and edits the rates the reports are calculated from. The client's
cost sheet and labour charges rarely change, so they are loaded once and
kept in the tool; this screen is where occasional changes are made.

Four tabs, each an editable table (`MasterTable`):

    Cost sheet              SKU | Item name | Category | Cost (Rs.) | Effective from
    Labour charges          SKU | Item name | Labour (Rs.) | Effective from
    Packages                Package | Items included | Price (Rs.)
    Executives & incentive  Executive | Incentive type | Rate | Effective from

Toolbar on each tab: search box, Import Excel, Export, Add row, Remove,
Save changes.

RATE CHANGES AND EFFECTIVE DATES
--------------------------------
When a money/rate cell is changed, a small dialog asks "Effective from?"
(defaulting to the 1st of next month). The old rate is kept for earlier
months, so re-running an earlier month's reports still uses the rate that
applied then, and the month-on-month trend stays correct. In this preview
the date is written into the row; the rate history itself will be stored in
the SQLite database when the logic is built.

Changed rows are tinted light blue and counted ("3 unsaved changes") until
the user clicks Save changes.

CURRENT BEHAVIOUR (v0.1.0 - UI preview)
---------------------------------------
Rows come from sample_data.py (placeholder figures). Edits, add, remove and
search all work on screen. Save, Import and Export show a message only.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDateEdit, QDialog, QHBoxLayout, QHeaderView,
    QLineEdit, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
    QWidget,
)

from app.pages.base import ScrollPage
from app.sample_data import COST_SHEET, EXECUTIVES, LABOUR_CHARGES, PACKAGES
from app.theme import Colors
from app.utils import format_inr, parse_inr
from app.widgets.common import Card, button, label


@dataclass
class Column:
    """
    Describes one table column.

    kind:
        "text"  - free text
        "money" - amount in rupees, shown with Indian grouping, right-aligned;
                  editing it triggers the Effective-from dialog
        "rate"  - a number (e.g. incentive %), right-aligned; also triggers
                  the Effective-from dialog
        "date"  - effective date (dd-mm-yyyy), set by the dialog, read-only
    """
    header: str
    kind: str = "text"
    width: int = 0          # 0 = stretch to fill


# ---------------------------------------------------------------------------
# Effective-date dialog
# ---------------------------------------------------------------------------
class EffectiveDateDialog(QDialog):
    """Asks from which date a changed rate applies."""

    def __init__(self, item_name: str, old: str, new: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Rate change")
        self.setModal(True)
        self.setMinimumWidth(400)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 22, 24, 20)
        lay.setSpacing(12)
        lay.addWidget(label("When does this rate apply from?", "SectionTitle"))
        lay.addWidget(label(f"{item_name}\n{old}  →  {new}", "Muted", wrap=True))

        # Default: 1st of next month (rates usually change at month start).
        today = QDate.currentDate()
        first_next = QDate(today.year(), today.month(), 1).addMonths(1)
        self.date_edit = QDateEdit(first_next)
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("dd-MM-yyyy")
        lay.addWidget(self.date_edit)
        lay.addWidget(label("Months before this date keep the old rate.", "Muted"))

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = button("Cancel", "Secondary")
        cancel.clicked.connect(self.reject)
        ok = button("Apply rate", "Primary")
        ok.clicked.connect(self.accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def date_text(self) -> str:
        return self.date_edit.date().toString("dd-MM-yyyy")


# ---------------------------------------------------------------------------
# MasterTable - one editable master with its toolbar
# ---------------------------------------------------------------------------
class MasterTable(QWidget):
    """An editable master table with search, add/remove and change tracking."""

    CHANGED_BG = QColor(Colors.BLUE_TINT)

    def __init__(self, title: str, columns: list[Column], rows: list[tuple],
                 name_col: int, page: ScrollPage):
        super().__init__()
        self.title = title
        self.columns = columns
        self.name_col = name_col          # column used to name the row in dialogs
        self.page = page                  # used for toast messages
        self._loading = False             # True while filling the table
        self._changed_rows: set[int] = set()   # rows edited or added
        self._removed = 0                       # rows removed since last save
        self._old_values: dict[tuple[int, int], str] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 14, 0, 0)
        lay.setSpacing(12)

        # --- Toolbar -----------------------------------------------------
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search {title.lower()}…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search)
        bar.addStretch(1)
        for text, handler in (
            ("Import Excel", lambda: self.page.toast(
                "Import will be enabled once the client's sheet format is confirmed.")),
            ("Export", lambda: self.page.toast("Export will be added with the masters database.")),
        ):
            b = button(text, "Secondary")
            b.clicked.connect(handler)
            bar.addWidget(b)
        add_btn = button("Add row", "Secondary")
        add_btn.clicked.connect(self._add_row)
        bar.addWidget(add_btn)
        self.remove_btn = button("Remove", "Danger")
        self.remove_btn.clicked.connect(self._remove_row)
        bar.addWidget(self.remove_btn)
        lay.addLayout(bar)

        # --- Table -------------------------------------------------------
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels([c.header for c in columns])
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed
                                   | QAbstractItemView.AnyKeyPressed)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setMinimumHeight(380)
        hdr = self.table.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for i, col in enumerate(columns):
            if col.width:
                hdr.setSectionResizeMode(i, QHeaderView.Fixed)
                self.table.setColumnWidth(i, col.width)
            else:
                hdr.setSectionResizeMode(i, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(self._remember_old_value)
        lay.addWidget(self.table)

        # --- Footer: change counter + save --------------------------------
        foot = QHBoxLayout()
        self.changes_label = label("Double-click a cell to edit.", "Muted")
        foot.addWidget(self.changes_label, 1)
        self.save_btn = button("Save changes", "Primary")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(False)
        foot.addWidget(self.save_btn)
        lay.addLayout(foot)

        self._load(rows)

    # ------------------------------------------------------------------
    # Filling and formatting cells
    # ------------------------------------------------------------------
    def _make_item(self, col: Column, value) -> QTableWidgetItem:
        """Create a table cell with the right text, alignment and editability."""
        if col.kind == "money":
            text = format_inr(float(value))
        elif col.kind == "rate":
            text = f"{float(value):g}"
        else:
            text = str(value)
        item = QTableWidgetItem(text)
        if col.kind in ("money", "rate"):
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if col.kind == "date":
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            item.setForeground(QBrush(QColor(Colors.SLATE)))
            item.setToolTip("Set automatically when a rate is changed.")
        return item

    def _load(self, rows: list[tuple]) -> None:
        self._loading = True
        self.table.setRowCount(0)
        for values in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, (col, value) in enumerate(zip(self.columns, values)):
                self.table.setItem(r, c, self._make_item(col, value))
        self._loading = False

    # ------------------------------------------------------------------
    # Editing
    # ------------------------------------------------------------------
    def _remember_old_value(self, row: int, col: int, *_):
        """Store the value of the cell the user moves to, so a change can be
        shown as 'old → new' and reverted if the dialog is cancelled."""
        item = self.table.item(row, col)
        if item is not None:
            self._old_values[(row, col)] = item.text()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        """Validate the edit, ask for an effective date for rates, mark the row."""
        if self._loading:
            return
        row, col = item.row(), item.column()
        spec = self.columns[col]
        old_text = self._old_values.get((row, col), "")

        if spec.kind in ("money", "rate"):
            value = parse_inr(item.text())
            if value is None or value < 0:
                self._set_text(item, old_text)
                self.page.toast("Enter a valid amount, e.g. 2400 or 2,400.00")
                return
            new_text = format_inr(value) if spec.kind == "money" else f"{value:g}"
            self._set_text(item, new_text)
            if new_text == old_text:
                return

            date_col = self._date_column()
            if date_col is not None and old_text:
                name = self.table.item(row, self.name_col)
                dlg = EffectiveDateDialog(name.text() if name else "Item",
                                          old_text, new_text, self)
                if dlg.exec() != QDialog.Accepted:
                    self._set_text(item, old_text)      # user cancelled: undo
                    return
                self._set_text(self.table.item(row, date_col), dlg.date_text())

        self._old_values[(row, col)] = item.text()
        self._mark_changed(row)

    def _set_text(self, item: QTableWidgetItem, text: str) -> None:
        """Change a cell's text without triggering _on_item_changed again."""
        self._loading = True
        item.setText(text)
        self._loading = False

    def _date_column(self) -> int | None:
        for i, c in enumerate(self.columns):
            if c.kind == "date":
                return i
        return None

    def _mark_changed(self, row: int) -> None:
        """Tint the row light blue and update the unsaved-changes counter."""
        self._changed_rows.add(row)
        self._loading = True
        for c in range(self.table.columnCount()):
            it = self.table.item(row, c)
            if it:
                it.setBackground(self.CHANGED_BG)
        self._loading = False
        self._update_change_label()

    def _update_change_label(self) -> None:
        """Show how many edits (changed/added rows + removals) are unsaved."""
        n = len(self._changed_rows) + self._removed
        self.changes_label.setText(f"{n} unsaved change{'s' if n != 1 else ''}")
        self.save_btn.setEnabled(n > 0)

    def _add_row(self) -> None:
        """Append an empty row (today's date as effective date) and start editing."""
        self._loading = True
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, col in enumerate(self.columns):
            if col.kind in ("money", "rate"):
                value = 0
            elif col.kind == "date":
                value = QDate.currentDate().toString("dd-MM-yyyy")
            else:
                value = ""
            self.table.setItem(r, c, self._make_item(col, value))
        self._loading = False
        self._mark_changed(r)
        self.table.scrollToBottom()
        self.table.setCurrentCell(r, self.name_col)
        self.table.editItem(self.table.item(r, self.name_col))

    def _remove_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            self.page.toast("Select a row to remove.")
            return
        name = self.table.item(row, self.name_col).text() or "Row"
        self.table.removeRow(row)
        # Row numbers above the removed row shift down by one.
        self._changed_rows = {r - 1 if r > row else r
                              for r in self._changed_rows if r != row}
        self._removed += 1
        self._update_change_label()
        self.save_btn.setEnabled(True)
        self.page.toast(f"{name} removed. Save changes to keep this.")

    def _save(self) -> None:
        """Clear the change markers (the database save comes in a later version)."""
        self._loading = True
        for r in range(self.table.rowCount()):
            for c in range(self.table.columnCount()):
                it = self.table.item(r, c)
                if it:
                    it.setBackground(QBrush())
        self._loading = False
        self._changed_rows.clear()
        self._removed = 0
        self.changes_label.setText("All changes saved.")
        self.save_btn.setEnabled(False)
        self.page.toast(f"{self.title} saved.")

    def _filter(self, text: str) -> None:
        """Hide rows that do not contain the search text in any column."""
        needle = text.strip().lower()
        for r in range(self.table.rowCount()):
            match = not needle or any(
                needle in (self.table.item(r, c).text().lower()
                           if self.table.item(r, c) else "")
                for c in range(self.table.columnCount()))
            self.table.setRowHidden(r, not match)


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------
class MastersPage(ScrollPage):
    """Tabs holding the four master tables."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(
            "Masters",
            "Costs, labour charges, packages and incentives used to calculate the reports.",
            parent,
        )
        notice = label(
            "Showing sample figures. The client's cost sheet and labour charges "
            "will replace these once received.", wrap=True)
        notice.setStyleSheet(
            f"background: {Colors.AMBER_TINT}; color: {Colors.AMBER};"
            "border-radius: 6px; padding: 9px 12px;")
        self.content.addWidget(notice)

        card = Card()
        tabs = QTabWidget()
        tabs.setDocumentMode(False)
        card.body.addWidget(tabs)
        self.content.addWidget(card, 1)

        tabs.addTab(MasterTable(
            "Cost sheet",
            [Column("SKU", width=110), Column("Item name"),
             Column("Category", width=110), Column("Cost (₹)", "money", 130),
             Column("Effective from", "date", 130)],
            COST_SHEET, name_col=1, page=self), "Cost sheet")

        tabs.addTab(MasterTable(
            "Labour charges",
            [Column("SKU", width=110), Column("Item name"),
             Column("Labour (₹)", "money", 130),
             Column("Effective from", "date", 130)],
            LABOUR_CHARGES, name_col=1, page=self), "Labour charges")

        tabs.addTab(MasterTable(
            "Packages",
            [Column("Package", width=180), Column("Items included"),
             Column("Price (₹)", "money", 130)],
            PACKAGES, name_col=0, page=self), "Packages")

        tabs.addTab(MasterTable(
            "Executives",
            [Column("Executive"), Column("Incentive type", width=180),
             Column("Rate", "rate", 100),
             Column("Effective from", "date", 130)],
            EXECUTIVES, name_col=0, page=self), "Executives && incentive")  # "&&" shows a literal "&"
